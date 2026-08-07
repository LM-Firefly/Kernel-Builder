#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:?usage: verify-release.sh <release-dir>}
manifest="$release_dir/kernels.json"
checksums="$release_dir/checksums.txt"

test -f "$manifest"
test -f "$checksums"
jq empty "$manifest"
jq -e '
  .schemaVersion == 2 and
  .abi == "arm64-v8a" and
  (.kernels | type == "array" and length > 0) and
  all(.kernels[];
    .abi == "arm64-v8a" and
    (.asset | endswith(".so.xz")) and
    (.sha256 | test("^[0-9a-f]{64}$")) and
    (.downloadUrl | startswith("https://"))
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
  sha256sum --check --status checksums.txt
  sha256sum --check --status kernels.json.sha256
)
echo "Verified release assets in $release_dir"
