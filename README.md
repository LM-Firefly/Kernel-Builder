# YumeBox Kernel Builder

这是一个独立的内核构建仓库。它只发布 `libmihomocore.so`，不构建 APP，也不修改
YumeBox 主仓库的 release。固定壳和 Go adapter 来自 `.env` 指定的模板仓库；每个渠道的
内核仓库、分支/tag 和 patch 在 `kernel-builder.json` 中定义。当前只构建 Android
`arm64-v8a`。

## 配置

`.env` 是非敏感的工具链和发布配置，已经提供默认模板；`.env.example` 用于重新创建配置。
不要把 token 写入 `.env`，私有模板或内核使用 Actions Secrets：

- `TEMPLATE_REPOSITORY_TOKEN`：读取私有壳/adapter 模板。
- `KERNEL_REPOSITORY_TOKEN`：读取私有内核源仓库。

`kernel-builder.json` 的 `channels[]` 可完全替换为自己的内核地址、ref、后缀和 patch 目录。
工作流支持定时构建、手动构建，以及上游通过 `repository_dispatch` 发送 `kernel-update`。

## 工作流阶段

1. `validate-config` 解析 `.env`，校验 JSON、patch 目录、工具链和唯一渠道，并生成矩阵。
2. `build-core` 为每个渠道独立 checkout 壳与内核，应用 patch，只构建 ARM64。
3. `verify-core` 用 `file`/`readelf` 校验 ELF、架构和 `MihomoMain` 导出，并锁定源 commit。
4. `package-release` 压缩 `.so`，生成 sidecar SHA-256、`checksums.txt`、`kernels.json` 和校验报告。
5. `publish-release` 只在全部渠道成功后创建 GitHub prerelease。

## Release 资产

每次运行创建不可变的 `yumebox-kernel-<run-id>-<attempt>` release，资产类似：

```text
libmihomocore-alpha-arm64-v8a-1af24e9.so.xz
libmihomocore-alpha-arm64-v8a-1af24e9.so.xz.sha256
kernels.json
kernels.json.sha256
checksums.txt
RELEASE_NOTES.md
```

这与 mihomo Alpha 的 `checksums.txt` 和带短 commit 的资产命名保持同一思路。`kernels.json`
使用 schema version 2，包含 shell ABI、源仓库/ref/commit、模板 commit、压缩格式、工具链、
下载 URL 和 SHA-256。APP 必须先通过 manifest 和 SHA-256 校验，再将解压后的 ARM64 ELF
写入临时文件并原子替换；失败时保留当前内核或回退到内置内核。

## 本地检查

```text
scripts/validate-config.sh .env kernel-builder.json
scripts/verify-core.sh <libmihomocore.so> arm64-v8a
scripts/package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>
scripts/verify-release.sh <release-dir>
```

SHA-256 只能检测传输损坏，不能单独证明发布者身份。生产环境还应在 APP 侧增加签名或
可信 release 仓库约束。
