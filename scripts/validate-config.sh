#!/usr/bin/env bash
set -euo pipefail

env_file=${1:-.env}
config_file=${2:-kernel-builder.json}

source "$(dirname "$0")/load-env.sh" "$env_file"

require_env() {
  local name=$1
  test -n "${!name:-}" || {
    echo "Missing required .env key: $name" >&2
    exit 1
  }
}

for key in TEMPLATE_REPOSITORY TEMPLATE_REF ANDROID_NDK_VERSION ANDROID_MIN_SDK \
  ANDROID_ABI JAVA_VERSION GO_VERSION GO_DOWNLOAD_BASE_URL \
  RELEASE_TAG RELEASE_NAME RELEASE_PRERELEASE RELEASE_MAKE_LATEST COMPRESSION COMPRESSION_LEVEL; do
  require_env "$key"
done

test "$ANDROID_ABI" = "arm64-v8a" || {
  echo "Only ANDROID_ABI=arm64-v8a is supported" >&2
  exit 1
}
test "$COMPRESSION" = "xz" || {
  echo "Only COMPRESSION=xz is supported by the current application loader" >&2
  exit 1
}
case "$RELEASE_PRERELEASE:$RELEASE_MAKE_LATEST" in
  true:false | false:true | false:false) ;;
  *)
    echo "RELEASE_PRERELEASE and RELEASE_MAKE_LATEST must be true or false" >&2
    exit 1
    ;;
esac
case "$COMPRESSION_LEVEL" in
  [0-9]) ;;
  *)
    echo "COMPRESSION_LEVEL must be a single digit from 0 to 9" >&2
    exit 1
    ;;
esac
case "$RELEASE_TAG" in
  [A-Za-z0-9._-]*) ;;
  *)
    echo "RELEASE_TAG contains unsupported characters: $RELEASE_TAG" >&2
    exit 1
    ;;
esac

jq -e '
  .schemaVersion == 1 and
  (.shellAbi | type == "number" and . >= 1) and
  .abis == ["arm64-v8a"] and
  (.channels | type == "array" and length > 0) and
  (([.channels[].id] | unique | length) == ([.channels[].id] | length)) and
  all(.channels[];
    (.id | test("^[a-z0-9][a-z0-9-]*$")) and
    (.label | type == "string" and length > 0) and
    (.repository | type == "string" and test("^(https://|git@).+")) and
    (.ref | type == "string" and length > 0) and
    (.suffix | type == "string") and
    (.patches | type == "string" and startswith("patches/"))
  )
' "$config_file" >/dev/null

while IFS= read -r patch_dir; do
  test -d "$patch_dir" || {
    echo "Configured patch directory does not exist: $patch_dir" >&2
    exit 1
  }
done < <(jq -r '.channels[].patches' "$config_file")

echo "Validated $config_file for ${ANDROID_ABI}"
