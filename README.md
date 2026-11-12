# Kernel-Builder

Kernel-Builder independently builds and publishes verified Android mihomo kernels for FlyCat. Each channel declares its target ABIs; `alpha`, `meta`, and `smart` build for all four Android ABIs (`armeabi-v7a`, `arm64-v8a`, `x86`, `x86_64`), while `ebpf` builds only for `arm64-v8a` and `x86_64`.

FlyCat reads per-ABI manifests from the fixed `kernel` Release at [`kernel/download/kernel-index.json`](https://github.com/LM-Firefly/Kernel-Builder/releases/download/kernel/kernel-index.json) (arm64-v8a default) and `kernel-index-{abi}.json` for other ABIs. Official Releases contain only the per-ABI `kernel-index*.json` and `kernel-*.so.xz` assets; no Release notes or temporary files are uploaded.

The workflow has a manual `workflow_dispatch` trigger with only two inputs: `release_mode` and `kernel_repository`. Official mode ignores the repository input and builds the configured `alpha`, `meta`, `smart`, and `ebpf` channels. Custom mode uses the submitted repository URL with the configured branch and patch set, builds one channel named `custom`, and derives its version and unique Release tag automatically. The custom Release publishes only `kernel-plugin.zip`; after extraction it contains the same `kernel-index.json` and verified kernel archive format as an official build.

Custom manifests include the builder repository, workflow, run id, commit, and `kernel-plugin-v1` format marker. APP integrations should accept custom packages only when these fields point to the certified workflow format and should verify archive contents, SHA-256, ABI, and source metadata before loading the core. These fields identify the workflow but are not a cryptographic signature, so a hostile-input client should additionally allowlist trusted builder repositories or verify GitHub artifact attestations.

The builder uses FlyCat's native build template for the CGO adapter and launcher. The builder workflow and release packaging are implemented in Python; it does not build the APK or duplicate those sources.

Release versions are derived from the locked upstream commit (`<channel>-<commit>`), so template branch suffixes cannot produce duplicate values such as `ebpf-ebpf-<commit>`. Upstream commits are resolved once and fetched by SHA, and packaging hashes/compresses cores as streams for faster, lower-memory releases.
