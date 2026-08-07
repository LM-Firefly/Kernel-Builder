## Kernel-Builder

Kernel-Builder independently builds and publishes verified Android `arm64-v8a` mihomo kernels for YumeBox.

YumeBox keeps the built-in Alpha kernel for offline use. When another kernel is selected, YumeBox reads the available Alpha, Meta, and Smart releases from [`kernel-index.json`](https://github.com/YumeYucca/Kernel-Builder/releases/download/kernel/kernel-index.json), downloads the selected archive, verifies its size and SHA-256, and loads it on the next service start.

The builder uses YumeBox's native build template for the CGO adapter and launcher. It does not build the APK or duplicate those sources.
