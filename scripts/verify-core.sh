#!/usr/bin/env bash
set -euo pipefail

core=${1:?usage: verify-core.sh <libmihomocore.so> [abi]}
abi=${2:-}

test -s "$core"
readelf -h "$core" | rg -q 'Type:[[:space:]]+DYN[[:space:]]+\(Shared object file\)'
readelf -Ws "$core" | rg -q '[[:space:]]MihomoMain$'

test "$abi" = "arm64-v8a"
readelf -h "$core" | rg -q 'AArch64'

echo "Verified $core${abi:+ ($abi)}"
