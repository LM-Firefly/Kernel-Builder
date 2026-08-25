"""Source acquisition, template checks, and artifact commands."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
from pathlib import Path

from .common import ALL_ABIS, HEX_COMMIT, authenticated_url, command, error, read_json, write_json

def detect_upstream(args: argparse.Namespace) -> None:
    rows = command(
        ["git", "ls-remote", authenticated_url(args.repository, args.token), args.ref],
        capture=True,
    ).splitlines()
    if not rows:
        error(f"Unable to resolve upstream ref: {args.repository} {args.ref}")
    commit = rows[0].split()[0]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        error(f"Invalid upstream commit: {commit}")
    write_json(
        Path(args.output),
        {
            "id": args.channel_id,
            "repository": args.repository,
            "ref": args.ref,
            "commit": commit,
        },
    )

def verify_native_source(args: argparse.Namespace) -> None:
    root = Path(args.root)
    required = (
        "scripts/native-build.py",
        "scripts/native/cli.py",
        "lib/native/go/native/entry.go",
        "lib/native/go/go.mod",
        "lib/native/shell/CMakeLists.txt",
        "lib/native/shell/shell.c",
        "kernel.properties",
    )
    for relative in required:
        if not (root / relative).is_file():
            error(f"Missing native source contract file: {root / relative}")

def configure_template(args: argparse.Namespace) -> None:
    Path(args.root, "local.properties").write_text(
        f"sdk.dir={args.sdk}\nndk.dir={args.sdk}/ndk/{args.ndk}\n",
        encoding="utf-8",
    )

def fetch_source(args: argparse.Namespace) -> None:
    target = Path(args.root, "lib/mihomo/mihomo")
    expected = read_json(Path(args.expected)).get("commit", "")
    if not HEX_COMMIT.fullmatch(expected):
        error(f"Invalid expected kernel commit: {expected}")
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as exc:
            error(f"Unable to remove existing source tree {target}: {exc}")
    target.mkdir(parents=True)
    command(["git", "-C", str(target), "init", "--quiet"])
    command(
        [
            "git",
            "-C",
            str(target),
            "remote",
            "add",
            "origin",
            authenticated_url(args.repository, args.token),
        ]
    )
    # Fetch the commit resolved by detect-upstream, not the mutable branch.
    # Otherwise a branch update between jobs causes intermittent mismatches.
    command(["git", "-C", str(target), "fetch", "--depth=1", "origin", expected])
    command(["git", "-C", str(target), "checkout", "--detach", "--quiet", "FETCH_HEAD"])
    actual = command(["git", "-C", str(target), "rev-parse", "HEAD"], capture=True)
    if actual != expected:
        error(f"Kernel commit mismatch: {expected} != {actual}")
    command(["git", "-C", str(target), "remote", "set-url", "origin", args.repository])

def apply_patches(args: argparse.Namespace) -> None:
    source = Path(args.source)
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)

def resolve_go_dependencies(args: argparse.Namespace) -> None:
    module_dir = Path(args.root, "lib/native/go")
    try:
        graph = json.loads(
            command(["go", "mod", "edit", "-json"], module_dir, capture=True)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        error(f"Unable to inspect Go dependencies: {exc}")
    for requirement in graph.get("Require", []):
        if requirement.get("Indirect"):
            command(
                ["go", "mod", "edit", f"-droprequire={requirement['Path']}"], module_dir
            )
    command(["go", "mod", "tidy"], module_dir)

def record_metadata(args: argparse.Namespace) -> None:
    root = Path(args.root)
    source_dir = root / "lib/mihomo/mihomo"
    source_commit = command(
        ["git", "-C", str(source_dir), "rev-parse", "HEAD"], capture=True
    )
    expected = read_json(Path(args.expected))["commit"]
    if source_commit != expected:
        error(f"Kernel commit mismatch: {source_commit} != {expected}")
    template_commit = command(["git", "rev-parse", "HEAD"], root, capture=True)
    write_json(
        root / "jniLibs" / args.abi / "source.json",
        {
            "repository": args.repository,
            "ref": args.ref,
            "commit": source_commit,
            "templateCommit": template_commit,
        },
    )

def copy_artifact(args: argparse.Namespace) -> None:
    source = Path(args.source)
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("libmihomocore.so", "core-version.properties", "source.json"):
        path = source / name
        if not path.is_file():
            error(f"Missing artifact file: {path}")
        shutil.copy2(path, target / name)

def stage_verified_artifact(args: argparse.Namespace) -> None:
    root = Path(args.root)
    candidates = []
    for core in root.rglob("libmihomocore.so"):
        parts = core.parts
        if any(
            parts[index : index + 2] == (args.channel, args.abi)
            for index in range(len(parts) - 1)
        ):
            candidates.append(core.parent)
    if len(candidates) != 1:
        error(f"Expected one core for {args.channel}, found {len(candidates)}")
    copy_artifact(argparse.Namespace(source=str(candidates[0]), target=args.target))

ABI_ELF_MACHINE = {
    "armeabi-v7a": (1, 40),   # ELFCLASS32, EM_ARM
    "arm64-v8a": (2, 183),    # ELFCLASS64, EM_AARCH64
    "x86": (1, 3),            # ELFCLASS32, EM_386
    "x86_64": (2, 62),        # ELFCLASS64, EM_X86_64
}

def valid_core(path: Path, abi: str) -> bool:
    expected_class, expected_machine = ABI_ELF_MACHINE.get(abi, (0, 0))
    if not expected_class:
        return False
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b"\x7fELF":
        return False
    elf_class = data[4]
    if elf_class != expected_class:
        return False
    file_type, machine = struct.unpack_from("<HH", data, 16)
    if file_type != 3 or machine != expected_machine:
        return False
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_size, section_count = struct.unpack_from("<HH", data, 58)
    if not section_offset or not section_size or not section_count:
        return False
    sections: list[tuple[int, int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * section_size
        if offset + 64 > len(data):
            return False
        section_type = struct.unpack_from("<I", data, offset + 4)[0]
        data_offset, data_size = struct.unpack_from("<QQ", data, offset + 24)
        link = struct.unpack_from("<I", data, offset + 40)[0]
        entry_size = struct.unpack_from("<Q", data, offset + 56)[0]
        sections.append((section_type, data_offset, data_size, link, entry_size))
    for section_type, data_offset, data_size, link, entry_size in sections:
        if section_type not in (2, 11) or not entry_size or link >= len(sections):
            continue
        _, strings_offset, strings_size, _, _ = sections[link]
        strings = data[strings_offset : strings_offset + strings_size]
        for index in range(data_size // entry_size):
            symbol_offset = data_offset + index * entry_size
            if symbol_offset + 4 > len(data):
                continue
            name_offset = struct.unpack_from("<I", data, symbol_offset)[0]
            name_end = strings.find(b"\0", name_offset)
            if name_end >= 0 and strings[name_offset:name_end] == b"MihomoMain":
                return True
    return False

def verify_core(args: argparse.Namespace) -> None:
    root = Path(args.root)
    cores = list(root.rglob("libmihomocore.so"))
    if len(cores) != 1:
        error(f"Expected one core under {root}, found {len(cores)}")
    core = cores[0]
    if args.abi not in ALL_ABIS or not valid_core(core, args.abi):
        error(f"Invalid Android core for {args.abi}: {core}")
    source_files = list(root.rglob("source.json"))
    if len(source_files) != 1:
        error(f"Expected one source.json under {root}, found {len(source_files)}")
    source = read_json(source_files[0])
    for key in ("commit", "templateCommit"):
        if not re.fullmatch(r"[0-9a-f]{40}", source.get(key, "")):
            error(f"Invalid {key} in {source_files[0]}")
    print(f"Verified {core} ({args.abi})")
