#!/usr/bin/env bash
set -euo pipefail

root=${1:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
output=${2:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
release_tag=${3:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
generated_at=${4:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
release_repository=${5:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
template_repository=${6:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
template_ref=${7:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
go_version=${8:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
ndk_version=${9:?usage: package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>}
compression_level=${XZ_COMPRESSION_LEVEL:-9}

mkdir -p "$output"
manifest="$output/kernel-index.json"
entries='[]'
shell_abi=$(jq -r '.shellAbi' kernel-builder.json)

shopt -s nullglob
cores=("$root"/*/*/libmihomocore.so)
for core in "${cores[@]}"; do
  relative=${core#"$root/"}
  channel=${relative%%/*}
  rest=${relative#*/}
  abi=${rest%%/*}
  test "$abi" = "arm64-v8a"
  properties=${core%/*}/core-version.properties
  source_metadata=${core%/*}/source.json
  test -f "$properties"
  test -f "$source_metadata"
  name=$(jq -r --arg id "$channel" '.channels[] | select(.id == $id) | .name' kernel-builder.json)
  commit=$(awk -F= '$1 == "core.commit" { print $2 }' "$properties")
  version=$(awk -F= '$1 == "core.displayVersion" { print $2 }' "$properties")
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]]
  test -n "$version"
  source_repository=$(jq -r '.repository' "$source_metadata")
  source_ref=$(jq -r '.ref' "$source_metadata")
  source_commit=$(jq -r '.commit' "$source_metadata")
  template_commit=$(jq -r '.templateCommit' "$source_metadata")
  asset="kernel-${channel}.so.xz"
  xz -"$compression_level"e -c "$core" > "$output/$asset"
  sha=$(sha256sum "$output/$asset" | awk '{ print $1 }')
  printf '%s  %s\n' "$sha" "$asset" > "$output/$asset.sha256"
  size_bytes=$(stat -c '%s' "$output/$asset")
  download_url="https://github.com/${release_repository}/releases/download/${release_tag}/${asset}"
  checksum_url="${download_url}.sha256"
  entries=$(jq -c \
    --arg id "$channel" \
    --arg name "$name" \
    --arg abi "$abi" \
    --argjson shellAbi "$shell_abi" \
    --arg asset "$asset" \
    --arg sha256 "$sha" \
    --arg commit "$commit" \
    --arg version "$version" \
    --arg repository "$source_repository" \
    --arg ref "$source_ref" \
    --arg sourceCommit "$source_commit" \
    --arg templateCommit "$template_commit" \
    --arg downloadUrl "$download_url" \
    --arg checksumUrl "$checksum_url" \
    --argjson sizeBytes "$size_bytes" \
    '. + [{id: $id, name: $name, version: $version, commit: $commit, abi: $abi, shellAbi: $shellAbi, asset: $asset, downloadUrl: $downloadUrl, checksumUrl: $checksumUrl, sha256: $sha256, sizeBytes: $sizeBytes, compression: "xz", sourceRepository: $repository, sourceRef: $ref, sourceCommit: $sourceCommit, templateCommit: $templateCommit}]' \
    <<<"$entries")
done

test "$(jq 'length' <<<"$entries")" -gt 0
jq -n \
  --argjson shellAbi "$shell_abi" \
  --arg abi "arm64-v8a" \
  --arg releaseTag "$release_tag" \
  --arg releaseUrl "https://github.com/${release_repository}/releases/tag/${release_tag}" \
  --arg manifestUrl "https://github.com/${release_repository}/releases/download/${release_tag}/kernel-index.json" \
  --arg generatedAt "$generated_at" \
  --arg templateRepository "$template_repository" \
  --arg templateRef "$template_ref" \
  --arg goVersion "$go_version" \
  --arg ndkVersion "$ndk_version" \
  --argjson compressionLevel "$compression_level" \
  --argjson kernels "$entries" \
  '{schemaVersion: 3, generatedAt: $generatedAt, release: {tag: $releaseTag, url: $releaseUrl, manifestUrl: $manifestUrl}, defaultKernel: "alpha", abi: $abi, shellAbi: $shellAbi, template: {repository: $templateRepository, ref: $templateRef}, toolchain: {go: $goVersion, ndk: $ndkVersion, compression: "xz", compressionLevel: $compressionLevel}, kernels: $kernels}' \
  > "$manifest"

jq empty "$manifest"
(
  cd "$output"
  for file in *.so.xz kernel-index.json; do
    sha256sum "$file"
  done > kernel-checksums.txt
  sha256sum kernel-index.json > kernel-index.json.sha256
)
echo "Packaged $(jq '.kernels | length' "$manifest") kernel assets in $output"
