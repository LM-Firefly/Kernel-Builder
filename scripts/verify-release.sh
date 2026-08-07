#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:?usage: verify-release.sh <release-dir>}
manifest="$release_dir/kernel-index.json"

test -f "$manifest"
jq empty "$manifest"
jq -e '
  .schemaVersion == 3 and
  .defaultKernel == "alpha" and
  .abi == "arm64-v8a" and
  (([.kernels[].id] | sort) == ["alpha", "meta", "smart"]) and
  (.kernels | type == "array" and length > 0) and
  all(.kernels[];
    (.id | type == "string" and length > 0) and
    (.name | type == "string" and length > 0) and
    .abi == "arm64-v8a" and
    (.asset | endswith(".so.xz")) and
    (.sha256 | test("^[0-9a-f]{64}$")) and
    (.downloadUrl | startswith("https://")) and
    (.sizeBytes | type == "number" and . > 0) and
    (.sourceCommit | test("^[0-9a-f]{40}$")) and
    (.templateCommit | test("^[0-9a-f]{40}$"))
  )
' "$manifest" >/dev/null

while IFS=$'\t' read -r asset sha size_bytes; do
  test -n "$asset"
  case "$asset" in
    kernel-alpha.so.xz | kernel-meta.so.xz | kernel-smart.so.xz) ;;
    *) echo "Unexpected kernel asset name: $asset" >&2; exit 1 ;;
  esac
  test -f "$release_dir/$asset"
  actual=$(sha256sum "$release_dir/$asset" | awk '{ print $1 }')
  test "$actual" = "$sha"
  test "$(stat -c '%s' "$release_dir/$asset")" = "$size_bytes"
  xz -t "$release_dir/$asset"
done < <(jq -r '.kernels[] | [.asset, .sha256, .sizeBytes] | @tsv' "$manifest")
echo "Verified release assets in $release_dir"
