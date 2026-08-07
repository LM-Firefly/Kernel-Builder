#!/usr/bin/env bash
set -euo pipefail

root=${1:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at>}
output=${2:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at>}
release_tag=${3:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at>}
generated_at=${4:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at>}

mkdir -p "$output"
manifest="$output/kernels.json"
entries='[]'

shopt -s nullglob
cores=("$root"/*/*/libmihomocore.so)
for core in "${cores[@]}"; do
  relative=${core#"$root/"}
  channel=${relative%%/*}
  rest=${relative#*/}
  abi=${rest%%/*}
  properties=${core%/*}/core-version.properties
  label=$(jq -r --arg id "$channel" '.channels[] | select(.id == $id) | .label' kernel-builder.json)
  commit=$(awk -F= '$1 == "core.commit" { print $2 }' "$properties")
  version=$(awk -F= '$1 == "core.displayVersion" { print $2 }' "$properties")
  asset="kernel-${channel}-${abi}.so.xz"
  xz -9e -c "$core" > "$output/$asset"
  sha=$(sha256sum "$output/$asset" | awk '{ print $1 }')
  entries=$(jq -c \
    --arg channel "$channel" \
    --arg label "$label" \
    --arg abi "$abi" \
    --arg asset "$asset" \
    --arg sha256 "$sha" \
    --arg commit "$commit" \
    --arg version "$version" \
    '. + [{channel: $channel, label: $label, abi: $abi, asset: $asset, sha256: $sha256, commit: $commit, version: $version}]' \
    <<<"$entries")
done

test "$(jq 'length' <<<"$entries")" -gt 0
jq -n \
  --argjson schemaVersion 1 \
  --argjson shellAbi "$(jq '.shellAbi' kernel-builder.json)" \
  --arg releaseTag "$release_tag" \
  --arg generatedAt "$generated_at" \
  --argjson kernels "$entries" \
  '{schemaVersion: $schemaVersion, shellAbi: $shellAbi, releaseTag: $releaseTag, generatedAt: $generatedAt, kernels: $kernels}' \
  > "$manifest"

jq empty "$manifest"
echo "Packaged $(jq '.kernels | length' "$manifest") kernel assets in $output"
