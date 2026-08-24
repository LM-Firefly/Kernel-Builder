"""Release indexing, compression, manifest generation, and verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import zipfile
from pathlib import Path

from .common import ABI, OFFICIAL_CHANNELS, ROOT, error, read_json, read_properties, release_version, streams_equal, write_json, write_outputs

def index_cores(root: Path, abi: str) -> dict[str, Path]:
    """Index verified cores once instead of recursively scanning per channel."""
    indexed: dict[str, Path] = {}
    for path in root.rglob("libmihomocore.so"):
        parts = path.parts
        for index in range(len(parts) - 1):
            if parts[index + 1] != abi:
                continue
            channel = parts[index]
            if channel in indexed:
                error(f"Expected one verified core for {channel}, found multiple")
            indexed[channel] = path
            break
    return indexed

def compress_core(source: Path, target: Path, preset: int) -> tuple[str, int]:
    """Compress a core and checksum the final archive without loading it."""
    with source.open("rb") as source_file, lzma.open(
        target, "wb", format=lzma.FORMAT_XZ, preset=preset
    ) as compressed:
        while chunk := source_file.read(1024 * 1024):
            compressed.write(chunk)
    with target.open("rb") as compressed_file:
        digest = hashlib.file_digest(compressed_file, "sha256").hexdigest()
    return digest, target.stat().st_size

def verify_release_directory(directory: Path) -> None:
    manifest = read_json(directory / "kernel-index.json")
    release = manifest.get("release", {})
    kind = release.get("kind", "official")
    if (
        manifest.get("schemaVersion") != 3
        or manifest.get("abi") != ABI
        or kind not in {"official", "custom"}
    ):
        error("Unsupported kernel index schema, ABI, or release kind")
    kernels = manifest.get("kernels", [])
    ids = [kernel.get("id") for kernel in kernels]
    if not ids or len(ids) != len(set(ids)):
        error("Release kernel ids must be unique and non-empty")
    if kind == "official" and set(ids) != OFFICIAL_CHANNELS:
        error("Official releases must contain exactly alpha, meta, smart, and ebpf kernels")
    if kind == "custom" and len(ids) != 1:
        error("Custom releases must contain exactly one kernel")
    if manifest.get("defaultKernel") not in ids:
        error("Invalid default kernel")
    expected_assets = {f"kernel-{channel}.so.xz" for channel in ids}
    for kernel in kernels:
        commit = kernel.get("commit", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            error(f"Invalid commit for {kernel.get('id')}")
        if (
            kind == "official"
            and kernel.get("version") != f"{kernel['id']}-{commit[:8]}"
        ):
            error(f"Invalid version for {kernel.get('id')}: {kernel.get('version')}")
        if (
            not kernel.get("name")
            or kernel.get("abi") != ABI
            or kernel.get("asset") not in expected_assets
            or kernel.get("compression") != "xz"
            or not str(kernel.get("downloadUrl", "")).startswith("https://")
            or not re.fullmatch(r"[0-9a-f]{64}", kernel.get("sha256", ""))
            or not isinstance(kernel.get("sizeBytes"), int)
            or kernel["sizeBytes"] <= 0
            or not kernel.get("sourceRepository")
            or not kernel.get("sourceRef")
            or not isinstance(kernel.get("capabilities"), list)
            or any(
                not isinstance(capability, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", capability)
                for capability in kernel.get("capabilities", [])
            )
        ):
            error(f"Invalid release metadata for {kernel.get('id')}")
        for key in ("sourceCommit", "templateCommit"):
            if not re.fullmatch(r"[0-9a-f]{40}", kernel.get(key, "")):
                error(f"Invalid {key} for {kernel.get('id')}")
        asset_name = kernel.get("asset", "")
        asset = directory / asset_name
        if asset_name not in expected_assets or not asset.is_file():
            error(f"Missing or unexpected asset: {asset}")
        with asset.open("rb") as asset_file:
            digest = hashlib.file_digest(asset_file, "sha256").hexdigest()
        if digest != kernel.get("sha256") or asset.stat().st_size != kernel.get(
            "sizeBytes"
        ):
            error(f"Checksum or size mismatch: {asset}")
        with lzma.open(asset, "rb") as compressed:
            compressed.read(1)
    if kind == "custom":
        plugin = release.get("plugin", {})
        plugin_path = directory / plugin.get("asset", "")
        if plugin.get("asset") != "kernel-plugin.zip" or not plugin_path.is_file():
            error("Custom release must contain kernel-plugin.zip")
        try:
            with zipfile.ZipFile(plugin_path) as archive:
                if set(archive.namelist()) != {"kernel-index.json", *expected_assets}:
                    error("Custom plugin contains unexpected files")
                if json.loads(archive.read("kernel-index.json")) != manifest:
                    error("Custom plugin manifest does not match release manifest")
                for asset_name in expected_assets:
                    with archive.open(asset_name, "r") as archived, (directory / asset_name).open("rb") as local:
                        if not streams_equal(archived, local):
                            error(f"Custom plugin asset mismatch: {asset_name}")
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            error(f"Invalid custom plugin: {exc}")
    print(f"Verified release assets in {directory}")

def package_release(args: argparse.Namespace) -> None:
    root = Path(args.root)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    config = read_json(ROOT / "kernel-builder.json")
    try:
        compression_level = int(args.compression_level)
        if not 0 <= compression_level <= 9:
            error("Compression level must be between 0 and 9")
        # PRESET_EXTREME is several times slower for a negligible size gain on
        # native libraries. Keep the configured level, but use the normal
        # encoder so release packaging remains predictable.
        preset = compression_level
        channels = json.loads(args.channels_json)
    except (ValueError, json.JSONDecodeError) as exc:
        error(f"Invalid release packaging input: {exc}")
    kind = args.release_mode
    if (
        kind not in {"official", "custom"}
        or not isinstance(channels, list)
        or not channels
    ):
        error("Invalid release packaging mode or channel matrix")
    if any(
        not isinstance(channel, dict)
        or not isinstance(channel.get("id"), str)
        or not isinstance(channel.get("name"), str)
        or not channel.get("name")
        or not isinstance(channel.get("capabilities", []), list)
        for channel in channels
    ):
        error("Invalid release channel metadata")
    channel_ids = [channel["id"] for channel in channels]
    if len(channel_ids) != len(set(channel_ids)):
        error("Release channel ids must be unique")
    plugin_url = f"https://github.com/{args.release_repository}/releases/download/{args.release_tag}/kernel-plugin.zip"
    if kind == "official" and set(channel_ids) != OFFICIAL_CHANNELS:
        error("Official releases must contain exactly alpha, meta, smart, and ebpf channels")
    if kind == "custom" and len(channels) != 1:
        error("Custom releases must contain exactly one kernel channel")
    core_index = index_cores(root, args.abi)
    entries = []
    for channel in channels:
        channel_id = channel["id"]
        core = core_index.get(channel_id)
        if core is None:
            error(f"Expected one verified core for {channel_id}, found none")
        source_dir = core.parent
        properties = read_properties(source_dir / "core-version.properties")
        source = read_json(source_dir / "source.json")
        core_commit = properties.get("core.commit", "")
        source_commit = source.get("commit", "")
        template_commit = source.get("templateCommit", "")
        version = release_version(
            channel_id,
            source_commit,
            args.version_override or properties.get("core.displayVersion", "")
            if kind == "custom"
            else "",
        )
        if not re.fullmatch(r"[0-9a-f]{7,40}", core_commit) or not version:
            error(f"Invalid core version metadata: {source_dir}")
        if not re.fullmatch(
            r"[0-9a-f]{40}", source_commit
        ) or not source_commit.startswith(core_commit):
            error(f"Invalid source commit: {source_dir}")
        if not re.fullmatch(r"[0-9a-f]{40}", template_commit):
            error(f"Invalid template commit: {source_dir}")
        asset_name = f"kernel-{channel_id}.so.xz"
        asset = output / asset_name
        sha256, size_bytes = compress_core(core, asset, preset)
        entries.append(
            {
                "id": channel_id,
                "name": channel["name"],
                "version": version,
                "commit": source_commit,
                "abi": args.abi,
                "shellAbi": config["shellAbi"],
                "asset": asset_name,
                "downloadUrl": plugin_url
                if kind == "custom"
                else f"https://github.com/{args.release_repository}/releases/download/{args.release_tag}/{asset_name}",
                "sha256": sha256,
                "sizeBytes": size_bytes,
                "compression": "xz",
                "capabilities": channel.get("capabilities", []),
                "sourceRepository": source["repository"],
                "sourceRef": source["ref"],
                "sourceCommit": source_commit,
                "templateCommit": template_commit,
            }
        )
    manifest = {
        "schemaVersion": 3,
        "generatedAt": args.generated_at,
        "release": {
            "kind": kind,
            "tag": args.release_tag,
            "url": f"https://github.com/{args.release_repository}/releases/tag/{args.release_tag}",
            "manifestUrl": plugin_url
            if kind == "custom"
            else f"https://github.com/{args.release_repository}/releases/download/{args.release_tag}/kernel-index.json",
            **(
                {"plugin": {"asset": "kernel-plugin.zip", "downloadUrl": plugin_url}}
                if kind == "custom"
                else {}
            ),
        },
        "builder": {
            "repository": args.builder_repository,
            "workflow": args.builder_workflow,
            "runId": args.builder_run_id,
            "commit": args.builder_sha,
            "format": "kernel-plugin-v1" if kind == "custom" else "kernel-release-v1",
        },
        "defaultKernel": channels[0]["id"]
        if kind == "custom"
        else config.get("defaultKernel", "alpha"),
        "abi": args.abi,
        "shellAbi": config["shellAbi"],
        "template": {"repository": args.template_repository, "ref": args.template_ref},
        "toolchain": {
            "go": args.go_version,
            "ndk": args.ndk_version,
            "compression": "xz",
            "compressionLevel": compression_level,
        },
        "kernels": entries,
    }
    write_json(output / "kernel-index.json", manifest)
    release_record = {
        "schemaVersion": 1,
        "kind": kind,
        "tag": args.release_tag,
        "generatedAt": args.generated_at,
        "kernelCount": len(entries),
        "assets": [entry["asset"] for entry in entries],
        "manifest": "kernel-index.json",
    }
    write_json(output / "kernel-release.json", release_record)
    (output / "RELEASE_NOTES.md").write_text(
        f"Kernel release {args.release_tag} generated at {args.generated_at}.\n",
        encoding="utf-8",
    )
    if kind == "custom":
        with zipfile.ZipFile(
            output / "kernel-plugin.zip", "w", compression=zipfile.ZIP_STORED
        ) as archive:
            archive.write(output / "kernel-index.json", "kernel-index.json")
            for entry in entries:
                archive.write(output / entry["asset"], entry["asset"])
    verify_release_directory(output)
    if args.github_output:
        write_outputs(Path(args.github_output), {"release_tag": args.release_tag})
    print(f"Packaged {len(entries)} kernel assets in {output}")

