# Kernel Builder

YumeBox Kernel Builder is an independent repository for building and publishing downloadable
`libmihomocore.so` kernels. It does not build the YumeBox APK or publish application releases.

## Repository Boundaries

- `YumeBox` is the source repository for the CGO adapter, Go entrypoint, PIE launcher, and native
  build script.
- `Kernel-Builder` contains channel configuration, upstream patches, verification, packaging, and
  the release workflow.

The workflow checks out the YumeBox repository and ref configured by `TEMPLATE_REPOSITORY` and
`TEMPLATE_REF`. It then replaces `lib/mihomo/mihomo` with the selected upstream kernel source,
copies the channel patches, and runs:

```text
kotlin scripts/native-build.main.kts --go
```

The YumeBox template is required. Its `lib/native/go` CGO adapter exports `MihomoMain`, and its
`lib/native/shell` launcher is built alongside the core. The upstream mihomo repository alone is
not sufficient. Kernel-Builder does not keep a second copy of these files.

Only Android `arm64-v8a` `libmihomocore.so` files are published.

## Configuration

`.env` contains the default toolchain and release settings. `kernel-builder.json` defines the fixed
`alpha`, `meta`, and `smart` channels, including repository, ref, suffix, and patch directory.

Use GitHub Actions secrets for private sources:

- `TEMPLATE_REPOSITORY_TOKEN`
- `KERNEL_REPOSITORY_TOKEN`

Manual workflow runs can override the template repository/ref, kernel URL/ref, Go version/download
URL, Java, NDK, minimum SDK, and release tag. Blank inputs use the repository defaults. A manual
kernel URL or ref is applied to all three matrix channels.

## Workflow

The `detect-upstream`, `build-core`, and `verify-core` jobs run as a three-channel matrix with
`fail-fast: false`. All channels must pass before packaging and publication.

The workflow uploads these Actions artifacts:

| Artifact | Contents | Retention |
| --- | --- | --- |
| `upstream-arm64-<channel>` | Resolved source commit | 2 days |
| `raw-arm64-<channel>` | Raw core and source metadata | 7 days |
| `verified-arm64-<channel>` | Verified core and metadata | 7 days |
| `release-assets-arm64` | Compressed release files and manifest | 14 days |

## Release

Every successful run updates the fixed `kernel` prerelease named `Build Kernel`.

```text
kernel-alpha.so.xz
kernel-meta.so.xz
kernel-smart.so.xz
kernel-checksums.txt
kernel-index.json
```

Clients must validate `kernel-index.json`, verify SHA-256, decompress the selected asset, and
confirm an Android ARM64 ELF exporting `MihomoMain` before replacing an installed kernel.

## Local Checks

```text
scripts/validate-config.sh .env kernel-builder.json
scripts/verify-core.sh <libmihomocore.so> arm64-v8a
scripts/package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>
scripts/verify-release.sh <release-dir>
```
