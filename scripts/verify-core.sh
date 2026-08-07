#!/usr/bin/env bash
set -euo pipefail

core=${1:?usage: verify-core.sh <libmihomocore.so> [abi]}
abi=${2:-}

test -s "$core"

match_readelf() {
  if command -v rg >/dev/null 2>&1; then
    rg -q "$1"
  else
    grep -Eq "$1"
  fi
}

readelf -h "$core" | match_readelf 'Type:[[:space:]]+DYN[[:space:]]+\(Shared object file\)'
readelf -Ws "$core" | match_readelf '[[:space:]]MihomoMain$'

test "$abi" = "arm64-v8a"
readelf -h "$core" | match_readelf 'AArch64'

echo "Verified $core${abi:+ ($abi)}"
