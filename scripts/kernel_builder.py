#!/usr/bin/env python3
"""CLI entry point for Kernel-Builder commands."""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

try:
    from builder.common import ABI, release_version
    from builder.config import validate_config
    from builder.notify import notify_telegram
    from builder.release import compress_core, package_release, verify_release_directory
    from builder.source import (
        apply_patches, configure_template, copy_artifact, detect_upstream,
        fetch_source, record_metadata, resolve_go_dependencies,
        stage_verified_artifact, verify_core, verify_native_source,
    )
except ModuleNotFoundError:
    from scripts.builder.common import ABI, release_version
    from scripts.builder.config import validate_config
    from scripts.builder.notify import notify_telegram
    from scripts.builder.release import compress_core, package_release, verify_release_directory
    from scripts.builder.source import (
        apply_patches, configure_template, copy_artifact, detect_upstream,
        fetch_source, record_metadata, resolve_go_dependencies,
        stage_verified_artifact, verify_core, verify_native_source,
    )


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
    item.add_argument("--generated-at", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    item.add_argument("--release-repository", required=True)
    item.add_argument("--release-mode", choices=("official", "custom"), required=True)
    item.add_argument("--channels-json", required=True)
    item.add_argument("--version-override", default="")
    item.add_argument("--builder-repository", required=True)
    item.add_argument("--builder-workflow", required=True)
    item.add_argument("--builder-run-id", required=True)
    item.add_argument("--builder-sha", required=True)
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
