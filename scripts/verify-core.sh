#!/usr/bin/env bash
set -euo pipefail

core=${1:?usage: verify-core.sh <libmihomocore.so> [abi]}
abi=${2:-}

test -s "$core"
readelf -h "$core" | rg -q 'Type:[[:space:]]+DYN[[:space:]]+\(Shared object file\)'
readelf -Ws "$core" | rg -q '[[:space:]]MihomoMain$'

case "$abi" in
  arm64-v8a) readelf -h "$core" | rg -q 'AArch64' ;;
  armeabi-v7a) readelf -h "$core" | rg -q 'ARM' ;;
  x86) readelf -h "$core" | rg -q 'Intel 80386' ;;
  x86_64) readelf -h "$core" | rg -q 'Advanced Micro Devices X86-64' ;;
  "") ;;
  *) echo "Unsupported ABI: $abi" >&2; exit 2 ;;
esac

echo "Verified $core${abi:+ ($abi)}"
