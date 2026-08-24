"""Configuration validation command."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from .common import ABI, OFFICIAL_CHANNELS, REQUIRED_ENV, error, read_dotenv, read_json, repository_identity, write_outputs

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
        "RELEASE_TAG": "INPUT_RELEASE_TAG",
        "RELEASE_NAME": "INPUT_RELEASE_NAME",
        "RELEASE_PRERELEASE": "INPUT_RELEASE_PRERELEASE",
        "RELEASE_MAKE_LATEST": "INPUT_RELEASE_MAKE_LATEST",
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
    if values["RELEASE_PRERELEASE"] not in {"true", "false"}:
        error("RELEASE_PRERELEASE must be true or false")
    if values["RELEASE_MAKE_LATEST"] not in {"true", "false"}:
        error("RELEASE_MAKE_LATEST must be true or false")
    if values["RELEASE_PRERELEASE"] == values["RELEASE_MAKE_LATEST"] == "true":
        error("RELEASE_PRERELEASE and RELEASE_MAKE_LATEST cannot both be true")
    if not re.fullmatch(r"[0-9]", values["COMPRESSION_LEVEL"]):
        error("COMPRESSION_LEVEL must be a digit from 0 to 9")
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", values["TEMPLATE_REPOSITORY"]
    ):
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

    mode = os.environ.get("INPUT_RELEASE_MODE", "official") or "official"
    if mode not in {"official", "custom"}:
        error("RELEASE_MODE must be official or custom")

    config = read_json(Path(args.config))
    if (
        config.get("schemaVersion") != 1
        or not isinstance(config.get("shellAbi"), int)
        or config["shellAbi"] < 1
        or config.get("abis") != [ABI]
    ):
        error("Invalid kernel-builder.json schema, shell ABI, or target ABI")
    channels = config.get("channels", [])
    if not isinstance(channels, list) or not channels:
        error("kernel-builder.json must contain at least one channel")
    ids = [channel.get("id") for channel in channels]
    if len(set(ids)) != len(ids):
        error("Channel ids must be unique")
    if mode == "official" and set(ids) != OFFICIAL_CHANNELS:
        error("Official releases must contain exactly alpha, meta, smart, and ebpf channels")
    if mode == "custom" and not channels:
        error("Custom releases require at least one configured channel")
    patches = config.get("patches", "")
    if not isinstance(patches, str) or not patches.startswith("patches/"):
        error("Invalid shared patch directory")
    patch_dir = Path(args.config).parent / patches
    if not patch_dir.is_dir():
        error(f"Missing patch directory: {patch_dir}")
    for channel in channels:
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", channel.get("id", ""))
            or not channel.get("name")
            or not re.match(r"^(https://|git@).+", channel.get("repository", ""))
            or not channel.get("ref")
            or re.search(r"\s", channel.get("ref", ""))
            or not isinstance(channel.get("suffix"), str)
            or not isinstance(channel.get("buildTags"), str)
            or not channel.get("buildTags")
            or not isinstance(channel.get("capabilities"), list)
            or any(
                not isinstance(capability, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", capability)
                for capability in channel.get("capabilities", [])
            )
            or len(channel.get("capabilities", []))
            != len(set(channel.get("capabilities", [])))
        ):
            error(f"Invalid channel: {channel.get('id')}")

    repository = os.environ.get("INPUT_KERNEL_REPOSITORY", "")
    ref = os.environ.get("INPUT_KERNEL_REF", "")
    custom_repository = os.environ.get("INPUT_CUSTOM_KERNEL_REPOSITORY", "")
    custom_ref = os.environ.get("INPUT_CUSTOM_KERNEL_REF", "")
    if repository and not re.match(r"^(https://|git@).+", repository):
        error(f"Invalid kernel repository override: {repository}")
    if custom_repository and not re.match(r"^(https://|git@).+", custom_repository):
        error(f"Invalid custom kernel repository: {custom_repository}")
    if ref and re.search(r"\s", ref):
        error("Kernel ref override cannot contain whitespace")
    if custom_ref and re.search(r"\s", custom_ref):
        error("Custom kernel ref cannot contain whitespace")

    if mode == "custom":
        if not repository and not custom_repository:
            error("Custom mode requires the kernel_repository input")
        selected_repository = custom_repository or repository
        base_channel = next(
            (
                channel
                for channel in channels
                if repository_identity(channel["repository"])
                == repository_identity(selected_repository)
            ),
            channels[0],
        )
        item = dict(base_channel)
        item["id"] = os.environ.get("INPUT_CUSTOM_CHANNEL_ID", "") or "custom"
        item["name"] = (
            os.environ.get("INPUT_CUSTOM_CHANNEL_NAME", "") or "Custom Kernel"
        )
        item["repository"] = selected_repository
        item["ref"] = custom_ref or ref or item["ref"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", item["id"]):
            error(f"Invalid custom channel id: {item['id']}")
        custom_version = os.environ.get("INPUT_CUSTOM_VERSION", "")
        if custom_version and re.search(r"\s", custom_version):
            error("Custom version cannot contain whitespace")
        channels = [item]
    else:
        channels = [dict(channel) for channel in channels]
        custom_version = ""
        for channel in channels:
            # The template already prefixes the version with the channel id.
            # Passing the same suffix again produces values such as
            # ebpf-ebpf-<commit> and makes an otherwise valid build fail.
            if channel["suffix"] == f"-{channel['id']}":
                channel["suffix"] = ""
    for channel in channels:
        channel["patches"] = patches

    tag = values["RELEASE_TAG"]
    if not os.environ.get("INPUT_RELEASE_TAG") and os.environ.get("GITHUB_RUN_ID"):
        tag = f"{tag}-{os.environ['GITHUB_RUN_ID']}"
    if mode == "custom" and not tag:
        error("Custom releases require a release tag")
    if mode == "custom" and not os.environ.get("INPUT_RELEASE_MAKE_LATEST"):
        values["RELEASE_MAKE_LATEST"] = "false"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        error(f"Invalid release tag: {tag}")
    default_kernel = config.get("defaultKernel", "alpha")
    if mode == "custom":
        default_kernel = channels[0]["id"]
    elif default_kernel not in {item["id"] for item in channels}:
        error(f"Configured default kernel is not present: {default_kernel}")
    write_outputs(
        Path(args.github_output),
        {
            "matrix": channels,
            "template_repository": values["TEMPLATE_REPOSITORY"],
            "template_ref": values["TEMPLATE_REF"],
            "android_ndk_version": values["ANDROID_NDK_VERSION"],
            "android_min_sdk": values["ANDROID_MIN_SDK"],
            "android_abi": values["ANDROID_ABI"],
            "java_version": values["JAVA_VERSION"],
            "go_version": values["GO_VERSION"],
            "go_download_base_url": values["GO_DOWNLOAD_BASE_URL"],
            "release_mode": mode,
            "release_tag": tag,
            "release_name": values["RELEASE_NAME"],
            "release_prerelease": values["RELEASE_PRERELEASE"],
            "release_make_latest": values["RELEASE_MAKE_LATEST"],
            "custom_version": custom_version,
            "compression_level": values["COMPRESSION_LEVEL"],
        },
    )
    print(f"Validated {args.config} for {ABI} ({mode} release)")


