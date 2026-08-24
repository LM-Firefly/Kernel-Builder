# Kernel-Builder

Kernel-Builder independently builds and publishes verified Android `arm64-v8a` mihomo kernels for YumeBox.

YumeBox reads the official index from [`latest/download/kernel-index.json`](https://github.com/YumeYucca/Kernel-Builder/releases/latest/download/kernel-index.json), so each official build can use a new immutable Release tag without breaking the APP URL. Official Releases contain only `kernel-index.json` and the three `kernel-*.so.xz` assets; no Release notes or temporary files are uploaded.

The workflow has a manual `workflow_dispatch` trigger with only two inputs: `release_mode` and `kernel_repository`. Official mode ignores the repository input and builds the configured `alpha`, `meta`, `smart`, and `ebpf` channels. Custom mode uses the submitted repository URL with the configured branch and patch set, builds one channel named `custom`, and derives its version and unique Release tag automatically. The custom Release publishes only `kernel-plugin.zip`; after extraction it contains the same `kernel-index.json` and verified kernel archive format as an official build.

Custom manifests include the builder repository, workflow, run id, commit, and `kernel-plugin-v1` format marker. APP integrations should accept custom packages only when these fields point to the certified workflow format and should verify archive contents, SHA-256, ABI, and source metadata before loading the core. These fields identify the workflow but are not a cryptographic signature, so a hostile-input client should additionally allowlist trusted builder repositories or verify GitHub artifact attestations.

The builder uses YumeBox's native build template for the CGO adapter and launcher. The builder workflow and release packaging are implemented in Python; it does not build the APK or duplicate those sources.
