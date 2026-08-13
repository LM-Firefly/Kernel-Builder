#!/usr/bin/env python3
"""Python implementation of the Kernel-Builder automation."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ABI = "arm64-v8a"
CHANNELS = ["alpha", "meta", "smart"]
REQUIRED_ENV = (
    "TEMPLATE_REPOSITORY", "TEMPLATE_REF", "ANDROID_NDK_VERSION",
    "ANDROID_MIN_SDK", "ANDROID_ABI", "JAVA_VERSION", "GO_VERSION",
    "GO_DOWNLOAD_BASE_URL", "RELEASE_TAG", "RELEASE_NAME",
    "RELEASE_PRERELEASE", "RELEASE_MAKE_LATEST", "COMPRESSION",
    "COMPRESSION_LEVEL",
)


def error(message: str) -> None:
    raise RuntimeError(message)


def redact_credentials(value: str) -> str:
    return re.sub(r"(https://)[^\s/@]+@", r"\1***@", value)


def command(args: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        detail = redact_credentials((result.stderr or result.stdout or "").strip())
        display_args = [redact_credentials(arg) for arg in args]
        error(f"Command failed ({result.returncode}): {' '.join(display_args)}\n{detail}")
    return (result.stdout or "").strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        error(f"Invalid JSON {path}: {exc}")
    if not isinstance(value, dict):
        error(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        error(f"Missing environment file: {path}")
    values: dict[str, str] = {}
    key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            error(f"Invalid dotenv entry in {path}: {raw}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key_pattern.fullmatch(key):
            error(f"Invalid dotenv key in {path}: {key}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def write_outputs(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, separators=(",", ":"))
            output.write(f"{key}={value}\n")


def validate_config(args: argparse.Namespace) -> None:
    values = read_dotenv(Path(args.env))
    for key in REQUIRED_ENV:
        values[key] = os.environ.get(key, values.get(key, ""))
    overrides = {
        "TEMPLATE_REPOSITORY": "INPUT_TEMPLATE_REPOSITORY",
        "TEMPLATE_REF": "INPUT_TEMPLATE_REF",
        "GO_VERSION": "INPUT_GO_VERSION",
        "GO_DOWNLOAD_BASE_URL": "INPUT_GO_DOWNLOAD_BASE_URL",
        "ANDROID_NDK_VERSION": "INPUT_ANDROID_NDK_VERSION",
        "ANDROID_MIN_SDK": "INPUT_ANDROID_MIN_SDK",
        "JAVA_VERSION": "INPUT_JAVA_VERSION",
    }
    for key, input_name in overrides.items():
        if os.environ.get(input_name):
            values[key] = os.environ[input_name]
    missing = [key for key in REQUIRED_ENV if not values.get(key)]
    if missing:
        error(f"Missing required .env key(s): {', '.join(missing)}")
    if values["ANDROID_ABI"] != ABI:
        error(f"Only ANDROID_ABI={ABI} is supported")
    if values["COMPRESSION"] != "xz":
        error("Only COMPRESSION=xz is supported")
    if values["RELEASE_TAG"] != "kernel":
        error("RELEASE_TAG must be kernel")
    if values["RELEASE_PRERELEASE"] not in {"true", "false"}:
        error("RELEASE_PRERELEASE must be true or false")
    if values["RELEASE_MAKE_LATEST"] not in {"true", "false"}:
        error("RELEASE_MAKE_LATEST must be true or false")
    if values["RELEASE_PRERELEASE"] == values["RELEASE_MAKE_LATEST"] == "true":
        error("RELEASE_PRERELEASE and RELEASE_MAKE_LATEST cannot both be true")
    if not re.fullmatch(r"[0-9]", values["COMPRESSION_LEVEL"]):
        error("COMPRESSION_LEVEL must be a digit from 0 to 9")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", values["RELEASE_TAG"]):
        error(f"Invalid release tag: {values['RELEASE_TAG']}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", values["TEMPLATE_REPOSITORY"]):
        error(f"Invalid template repository: {values['TEMPLATE_REPOSITORY']}")
    if not values["TEMPLATE_REF"] or re.search(r"\s", values["TEMPLATE_REF"]):
        error("TEMPLATE_REF must be non-empty and contain no whitespace")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", values["ANDROID_NDK_VERSION"]):
        error(f"Invalid Android NDK version: {values['ANDROID_NDK_VERSION']}")
    if not re.fullmatch(r"[0-9]+", values["ANDROID_MIN_SDK"]):
        error(f"Invalid Android minimum SDK: {values['ANDROID_MIN_SDK']}")
    if not values["JAVA_VERSION"] or re.search(r"\s", values["JAVA_VERSION"]):
        error("JAVA_VERSION must be non-empty and contain no whitespace")
    if not values["GO_DOWNLOAD_BASE_URL"].startswith("https://"):
        error("GO_DOWNLOAD_BASE_URL must use HTTPS")

    config = read_json(Path(args.config))
    if (
        config.get("schemaVersion") != 1
        or not isinstance(config.get("shellAbi"), int)
        or config["shellAbi"] < 1
        or config.get("abis") != [ABI]
    ):
        error("Invalid kernel-builder.json schema, shell ABI, or target ABI")
    channels = config.get("channels", [])
    if sorted(channel.get("id") for channel in channels) != CHANNELS:
        error("kernel-builder.json must contain alpha, meta, and smart channels")
    for channel in channels:
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", channel.get("id", ""))
            or not channel.get("name")
            or not re.match(r"^(https://|git@).+", channel.get("repository", ""))
            or not channel.get("ref")
            or re.search(r"\s", channel.get("ref", ""))
            or not isinstance(channel.get("suffix"), str)
            or not isinstance(channel.get("patches"), str)
            or not channel["patches"].startswith("patches/")
        ):
            error(f"Invalid channel: {channel.get('id')}")
        patch_dir = Path(args.config).parent / channel.get("patches", "")
        if not patch_dir.is_dir():
            error(f"Missing patch directory: {patch_dir}")

    repository = os.environ.get("INPUT_KERNEL_REPOSITORY", "")
    ref = os.environ.get("INPUT_KERNEL_REF", "")
    if repository and not re.match(r"^(https://|git@).+", repository):
        error(f"Invalid kernel repository override: {repository}")
    if ref and re.search(r"\s", ref):
        error("Kernel ref override cannot contain whitespace")
    matrix = []
    for channel in channels:
        item = dict(channel)
        if repository:
            item["repository"] = repository
        if ref:
            item["ref"] = ref
        matrix.append(item)
    write_outputs(Path(args.github_output), {
        "matrix": matrix,
        "template_repository": values["TEMPLATE_REPOSITORY"],
        "template_ref": values["TEMPLATE_REF"],
        "android_ndk_version": values["ANDROID_NDK_VERSION"],
        "android_min_sdk": values["ANDROID_MIN_SDK"],
        "android_abi": values["ANDROID_ABI"],
        "java_version": values["JAVA_VERSION"],
        "go_version": values["GO_VERSION"],
        "go_download_base_url": values["GO_DOWNLOAD_BASE_URL"],
        "release_tag": values["RELEASE_TAG"],
        "release_name": values["RELEASE_NAME"],
        "release_prerelease": values["RELEASE_PRERELEASE"],
        "release_make_latest": values["RELEASE_MAKE_LATEST"],
        "compression_level": values["COMPRESSION_LEVEL"],
    })
    print(f"Validated {args.config} for {ABI}")


def authenticated_url(repository: str, token: str) -> str:
    if token and repository.startswith("https://github.com/"):
        return repository.replace("https://", f"https://x-access-token:{token}@", 1)
    return repository


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
    write_json(Path(args.output), {
        "id": args.channel_id,
        "repository": args.repository,
        "ref": args.ref,
        "commit": commit,
    })


def verify_native_source(args: argparse.Namespace) -> None:
    root = Path(args.root)
    required = (
        "scripts/native-build.py", "scripts/native/cli.py",
        "lib/native/go/native/entry.go", "lib/native/go/go.mod",
        "lib/native/shell/CMakeLists.txt", "lib/native/shell/shell.c",
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
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    command(["git", "-C", str(target), "init", "--quiet"])
    command(["git", "-C", str(target), "remote", "add", "origin", authenticated_url(args.repository, args.token)])
    command(["git", "-C", str(target), "fetch", "--depth=1", "origin", args.ref])
    command(["git", "-C", str(target), "checkout", "--detach", "--quiet", "FETCH_HEAD"])
    actual = command(["git", "-C", str(target), "rev-parse", "HEAD"], capture=True)
    expected = read_json(Path(args.expected))["commit"]
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
    graph = json.loads(command(["go", "mod", "edit", "-json"], module_dir, capture=True))
    for requirement in graph.get("Require", []):
        if requirement.get("Indirect"):
            command(["go", "mod", "edit", f"-droprequire={requirement['Path']}"], module_dir)
    command(["go", "mod", "tidy"], module_dir)


def record_metadata(args: argparse.Namespace) -> None:
    root = Path(args.root)
    source_dir = root / "lib/mihomo/mihomo"
    source_commit = command(["git", "-C", str(source_dir), "rev-parse", "HEAD"], capture=True)
    expected = read_json(Path(args.expected))["commit"]
    if source_commit != expected:
        error(f"Kernel commit mismatch: {source_commit} != {expected}")
    template_commit = command(["git", "rev-parse", "HEAD"], root, capture=True)
    write_json(root / "jniLibs" / args.abi / "source.json", {
        "repository": args.repository,
        "ref": args.ref,
        "commit": source_commit,
        "templateCommit": template_commit,
    })


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
        if any(parts[index:index + 2] == (args.channel, args.abi) for index in range(len(parts) - 1)):
            candidates.append(core.parent)
    if len(candidates) != 1:
        error(f"Expected one core for {args.channel}, found {len(candidates)}")
    copy_artifact(argparse.Namespace(source=str(candidates[0]), target=args.target))


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def valid_arm64_core(path: Path) -> bool:
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        return False
    file_type, machine = struct.unpack_from("<HH", data, 16)
    if file_type != 3 or machine != 183:
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
        strings = data[strings_offset:strings_offset + strings_size]
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
    if args.abi != ABI or not valid_arm64_core(core):
        error(f"Invalid Android ARM64 core: {core}")
    source_files = list(root.rglob("source.json"))
    if len(source_files) != 1:
        error(f"Expected one source.json under {root}, found {len(source_files)}")
    source = read_json(source_files[0])
    for key in ("commit", "templateCommit"):
        if not re.fullmatch(r"[0-9a-f]{40}", source.get(key, "")):
            error(f"Invalid {key} in {source_files[0]}")
    print(f"Verified {core} ({args.abi})")


def locate_core(root: Path, channel: str, abi: str) -> Path:
    candidates = []
    for path in root.rglob("libmihomocore.so"):
        parts = path.parts
        if any(parts[index:index + 2] == (channel, abi) for index in range(len(parts) - 1)):
            candidates.append(path)
    if len(candidates) != 1:
        error(f"Expected one verified core for {channel}, found {len(candidates)}")
    return candidates[0]


def verify_release_directory(directory: Path) -> None:
    manifest_path = directory / "kernel-index.json"
    manifest = read_json(manifest_path)
    if manifest.get("schemaVersion") != 3:
        error("Unsupported kernel index schema")
    if manifest.get("defaultKernel") != "alpha" or manifest.get("abi") != ABI:
        error("Invalid default kernel or ABI")
    kernels = manifest.get("kernels", [])
    if sorted(kernel.get("id") for kernel in kernels) != CHANNELS:
        error("Release must contain alpha, meta, and smart kernels")
    expected_assets = {f"kernel-{channel}.so.xz" for channel in CHANNELS}
    for kernel in kernels:
        commit = kernel.get("commit", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            error(f"Invalid commit for {kernel.get('id')}")
        if kernel.get("version") != f"{kernel['id']}-{commit[:8]}":
            error(f"Invalid version for {kernel.get('id')}: {kernel.get('version')}")
        if (
            not kernel.get("name")
            or kernel.get("abi") != ABI
            or not str(kernel.get("asset", "")).endswith(".so.xz")
            or kernel.get("compression") != "xz"
            or not str(kernel.get("downloadUrl", "")).startswith("https://")
            or not re.fullmatch(r"[0-9a-f]{64}", kernel.get("sha256", ""))
            or not isinstance(kernel.get("sizeBytes"), int)
            or kernel["sizeBytes"] <= 0
            or not kernel.get("sourceRepository")
            or not kernel.get("sourceRef")
        ):
            error(f"Invalid release metadata for {kernel.get('id')}")
        for key in ("sourceCommit", "templateCommit"):
            if not re.fullmatch(r"[0-9a-f]{40}", kernel.get(key, "")):
                error(f"Invalid {key} for {kernel.get('id')}")
        asset_name = kernel.get("asset", "")
        asset = directory / asset_name
        if asset_name not in expected_assets or not asset.is_file():
            error(f"Missing or unexpected asset: {asset}")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        if digest != kernel.get("sha256") or asset.stat().st_size != kernel.get("sizeBytes"):
            error(f"Checksum or size mismatch: {asset}")
        with lzma.open(asset, "rb") as compressed:
            compressed.read(1)
    print(f"Verified release assets in {directory}")


def package_release(args: argparse.Namespace) -> None:
    root = Path(args.root)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    config = read_json(ROOT / "kernel-builder.json")
    preset = int(args.compression_level) | lzma.PRESET_EXTREME
    entries = []
    for channel in config["channels"]:
        channel_id = channel["id"]
        core = locate_core(root, channel_id, args.abi)
        source_dir = core.parent
        properties = read_properties(source_dir / "core-version.properties")
        source = read_json(source_dir / "source.json")
        core_commit = properties.get("core.commit", "")
        version = properties.get("core.displayVersion", "")
        source_commit = source.get("commit", "")
        template_commit = source.get("templateCommit", "")
        if not re.fullmatch(r"[0-9a-f]{7,40}", core_commit) or not version:
            error(f"Invalid core version metadata: {source_dir}")
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            error(f"Invalid source commit: {source_dir}")
        if not source_commit.startswith(core_commit):
            error(f"Source commit does not match core commit: {source_dir}")
        if not re.fullmatch(r"[0-9a-f]{40}", template_commit):
            error(f"Invalid template commit: {source_dir}")
        asset_name = f"kernel-{channel_id}.so.xz"
        asset = output / asset_name
        with core.open("rb") as source_file:
            with lzma.open(asset, "wb", format=lzma.FORMAT_XZ, preset=preset) as compressed:
                shutil.copyfileobj(source_file, compressed)
        entries.append({
            "id": channel_id,
            "name": channel["name"],
            "version": version,
            "commit": source_commit,
            "abi": args.abi,
            "shellAbi": config["shellAbi"],
            "asset": asset_name,
            "downloadUrl": (
                f"https://github.com/{args.release_repository}/releases/download/"
                f"{args.release_tag}/{asset_name}"
            ),
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            "sizeBytes": asset.stat().st_size,
            "compression": "xz",
            "sourceRepository": source["repository"],
            "sourceRef": source["ref"],
            "sourceCommit": source_commit,
            "templateCommit": template_commit,
        })
    manifest = {
        "schemaVersion": 3,
        "generatedAt": args.generated_at,
        "release": {
            "tag": args.release_tag,
            "url": f"https://github.com/{args.release_repository}/releases/tag/{args.release_tag}",
            "manifestUrl": (
                f"https://github.com/{args.release_repository}/releases/download/"
                f"{args.release_tag}/kernel-index.json"
            ),
        },
        "defaultKernel": "alpha",
        "abi": args.abi,
        "shellAbi": config["shellAbi"],
        "template": {"repository": args.template_repository, "ref": args.template_ref},
        "toolchain": {
            "go": args.go_version,
            "ndk": args.ndk_version,
            "compression": "xz",
            "compressionLevel": int(args.compression_level),
        },
        "kernels": entries,
    }
    write_json(output / "kernel-index.json", manifest)
    verify_release_directory(output)
    (output / "RELEASE_NOTES.md").write_text(f"{args.generated_at}\n", encoding="utf-8")
    if args.github_output:
        write_outputs(Path(args.github_output), {"release_tag": args.release_tag})
    print(f"Packaged {len(entries)} kernel assets in {output}")


def notify_telegram(args: argparse.Namespace) -> None:
    if not args.bot_token or not args.chat_id:
        print("Telegram notification skipped: BOT_TOKEN and CHAT_ID are required.")
        return
    release_url = f"https://github.com/{args.repository}/releases/tag/{args.release_tag}"
    data = urllib.parse.urlencode({
        "chat_id": args.chat_id,
        "disable_web_page_preview": "true",
        "text": f"{args.release_name}\nTag: {args.release_tag}\nRelease: {release_url}",
    }).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{args.bot_token}/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            error(f"Telegram request failed: HTTP {response.status}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    item = commands.add_parser("validate-config")
    item.add_argument("--env", required=True)
    item.add_argument("--config", required=True)
    item.add_argument("--github-output", required=True)
    item.set_defaults(handler=validate_config)

    item = commands.add_parser("detect-upstream")
    item.add_argument("--channel-id", required=True)
    item.add_argument("--repository", required=True)
    item.add_argument("--ref", required=True)
    item.add_argument("--token", default="")
    item.add_argument("--output", required=True)
    item.set_defaults(handler=detect_upstream)

    item = commands.add_parser("verify-native-source")
    item.add_argument("--root", required=True)
    item.set_defaults(handler=verify_native_source)

    item = commands.add_parser("configure-template")
    item.add_argument("--root", required=True)
    item.add_argument("--sdk", required=True)
    item.add_argument("--ndk", required=True)
    item.set_defaults(handler=configure_template)

    item = commands.add_parser("fetch-source")
    item.add_argument("--root", required=True)
    item.add_argument("--repository", required=True)
    item.add_argument("--ref", required=True)
    item.add_argument("--token", default="")
    item.add_argument("--expected", required=True)
    item.set_defaults(handler=fetch_source)

    item = commands.add_parser("apply-patches")
    item.add_argument("--source", required=True)
    item.add_argument("--target", required=True)
    item.set_defaults(handler=apply_patches)

    item = commands.add_parser("resolve-go-dependencies")
    item.add_argument("--root", required=True)
    item.set_defaults(handler=resolve_go_dependencies)

    item = commands.add_parser("record-metadata")
    item.add_argument("--root", required=True)
    item.add_argument("--abi", required=True)
    item.add_argument("--repository", required=True)
    item.add_argument("--ref", required=True)
    item.add_argument("--expected", required=True)
    item.set_defaults(handler=record_metadata)

    item = commands.add_parser("copy-artifact")
    item.add_argument("--source", required=True)
    item.add_argument("--target", required=True)
    item.set_defaults(handler=copy_artifact)

    item = commands.add_parser("stage-verified-artifact")
    item.add_argument("--root", required=True)
    item.add_argument("--channel", required=True)
    item.add_argument("--abi", required=True)
    item.add_argument("--target", required=True)
    item.set_defaults(handler=stage_verified_artifact)

    item = commands.add_parser("verify-core")
    item.add_argument("--root", required=True)
    item.add_argument("--abi", required=True)
    item.set_defaults(handler=verify_core)

    item = commands.add_parser("package-release")
    item.add_argument("--root", required=True)
    item.add_argument("--output", required=True)
    item.add_argument("--release-tag", required=True)
    item.add_argument(
        "--generated-at",
        default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    item.add_argument("--release-repository", required=True)
    item.add_argument("--template-repository", required=True)
    item.add_argument("--template-ref", required=True)
    item.add_argument("--go-version", required=True)
    item.add_argument("--ndk-version", required=True)
    item.add_argument("--abi", default=ABI)
    item.add_argument("--compression-level", default="9")
    item.add_argument("--github-output")
    item.set_defaults(handler=package_release)

    item = commands.add_parser("verify-release")
    item.add_argument("--directory", required=True)
    item.set_defaults(handler=lambda args: verify_release_directory(Path(args.directory)))

    item = commands.add_parser("notify-telegram")
    item.add_argument("--bot-token", default=os.environ.get("BOT_TOKEN", ""))
    item.add_argument("--chat-id", default=os.environ.get("CHAT_ID", ""))
    item.add_argument("--release-name", required=True)
    item.add_argument("--release-tag", required=True)
    item.add_argument("--repository", required=True)
    item.set_defaults(handler=notify_telegram)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        args.handler(args)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
