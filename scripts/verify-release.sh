#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:?usage: verify-release.sh <release-dir>}
manifest="$release_dir/kernel-index.json"
checksums="$release_dir/kernel-checksums.txt"

test -f "$manifest"
test -f "$checksums"
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
    (.checksumUrl | startswith("https://")) and
    (.sizeBytes | type == "number" and . > 0) and
    (.sourceCommit | test("^[0-9a-f]{40}$")) and
    (.templateCommit | test("^[0-9a-f]{40}$"))
  )
' "$manifest" >/dev/null

while IFS=$'\t' read -r asset sha; do
  test -n "$asset"
  test -f "$release_dir/$asset"
  actual=$(sha256sum "$release_dir/$asset" | awk '{ print $1 }')
  test "$actual" = "$sha"
  xz -t "$release_dir/$asset"
  printf '%s  %s\n' "$sha" "$asset" | sha256sum --check --status -
  (
    cd "$release_dir"
    sha256sum --check --status "$asset.sha256"
  )
done < <(jq -r '.kernels[] | [.asset, .sha256] | @tsv' "$manifest")

(
  cd "$release_dir"
  sha256sum --check --status kernel-checksums.txt
  sha256sum --check --status kernel-index.json.sha256
)
echo "Verified release assets in $release_dir"
