"""Shared constants and low-level helpers for kernel builder commands."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ABI = "arm64-v8a"
ALL_ABIS = ("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
OFFICIAL_CHANNELS = {"alpha", "meta", "smart", "ebpf"}
HEX_COMMIT = re.compile(r"[0-9a-f]{40}")
REQUIRED_ENV = (
    "TEMPLATE_REPOSITORY", "TEMPLATE_REF", "ANDROID_NDK_VERSION",
    "ANDROID_MIN_SDK", "JAVA_VERSION", "GO_VERSION",
    "GO_DOWNLOAD_BASE_URL", "RELEASE_TAG", "RELEASE_NAME",
    "RELEASE_PRERELEASE", "RELEASE_MAKE_LATEST", "COMPRESSION",
    "COMPRESSION_LEVEL",
)

def error(message: str) -> NoReturn:
    raise RuntimeError(message)

def redact_credentials(value: str) -> str:
    return re.sub(r"(https://)[^\s/@]+@", r"\1***@", value)

def repository_identity(value: str) -> str:
    identity = value.strip().rstrip("/")
    if identity.endswith(".git"):
        identity = identity[:-4]
    return identity.lower()

def release_version(channel_id: str, source_commit: str, override: str = "") -> str:
    """Return a stable version that cannot be changed by template branch suffixes."""
    if override:
        if re.search(r"\s", override):
            error("Version override cannot contain whitespace")
        return override
    if not HEX_COMMIT.fullmatch(source_commit):
        error(f"Invalid source commit for {channel_id}: {source_commit}")
    return f"{channel_id}-{source_commit[:8]}"

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
        error(
            f"Command failed ({result.returncode}): {' '.join(display_args)}\n{detail}"
        )
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
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

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

def authenticated_url(repository: str, token: str) -> str:
    if token and repository.startswith("https://github.com/"):
        return repository.replace("https://", f"https://x-access-token:{token}@", 1)
    return repository

def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values

def streams_equal(left: Any, right: Any) -> bool:
    """Compare binary streams in bounded memory."""
    while True:
        left_chunk = left.read(1024 * 1024)
        right_chunk = right.read(1024 * 1024)
        if left_chunk != right_chunk:
            return False
        if not left_chunk:
            return True
