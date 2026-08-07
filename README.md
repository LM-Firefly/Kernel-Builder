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
5. `publish-release` 只在全部渠道成功后更新固定的 GitHub prerelease。

## Release 资产

## 固定 Release 合约

工作流不会为每次运行创建新的 Release。它始终更新以下固定 Release：

| 字段 | 值 |
| --- | --- |
| Tag | `yumebox-kernels-arm64` |
| Name | `YumeBox Kernels (arm64-v8a)` |
| 类型 | prerelease，且不标记为 latest |
| JSON 稳定地址 | `https://github.com/<owner>/<repo>/releases/download/yumebox-kernels-arm64/kernels.json` |
| 支持 ABI | `arm64-v8a` |

固定资产名会被覆盖，不会在同一 Release 中残留旧 commit 文件；实际源版本始终记录在
`kernels.json`。如果需要历史版本，应在 APP 侧保存 manifest，或复制 Release 后再归档。

## 最终 Release 资产

最终 Release 只上传这些文件（内部 Actions Artifact 不会出现在 Release 页面）：

```text
libmihomocore-stable-arm64-v8a.so.xz
libmihomocore-stable-arm64-v8a.so.xz.sha256
libmihomocore-alpha-arm64-v8a.so.xz
libmihomocore-alpha-arm64-v8a.so.xz.sha256
libmihomocore-meta-arm64-v8a.so.xz
libmihomocore-meta-arm64-v8a.so.xz.sha256
libmihomocore-smart-arm64-v8a.so.xz
libmihomocore-smart-arm64-v8a.so.xz.sha256
checksums.txt
kernels.json
kernels.json.sha256
```

压缩使用 `xz -9e`，即 LZMA2 极限压缩；Release 页面提供 `checksums.txt`，每个压缩库和
`kernels.json` 还有独立的 SHA-256 文件。`kernels.json` 使用 schema version 2，包含 shell ABI、
源仓库/ref/commit、模板 commit、压缩格式、工具链、下载 URL 和 SHA-256。APP 必须先校验
manifest，再校验目标 `.so.xz`，解压后验证 ARM64 ELF 和 `MihomoMain`，最后写入临时文件并
原子替换；失败时保留当前内核或回退到内置内核。

## Actions Artifact 与 Release 的区别

| 阶段 | Artifact 名称 | 内容 | 保留时间 | 是否对用户发布 |
| --- | --- | --- | --- | --- |
| 构建后 | `raw-arm64-<channel>` | 未压缩 `.so`、版本 properties、源 commit JSON | 7 天 | 否 |
| 验证后 | `verified-arm64-<channel>` | 通过 ELF/入口点验证的同一组文件 | 7 天 | 否 |
| 打包后 | `release-assets-arm64` | 最终压缩包、校验文件、JSON、Release notes | 14 天 | 否 |
| 发布后 | 固定 Release `yumebox-kernels-arm64` | 上表“最终 Release 资产” | 由 GitHub 保留 | 是 |

## 本地检查

```text
scripts/validate-config.sh .env kernel-builder.json
scripts/verify-core.sh <libmihomocore.so> arm64-v8a
scripts/package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>
scripts/verify-release.sh <release-dir>
```

SHA-256 只能检测传输损坏，不能单独证明发布者身份。生产环境还应在 APP 侧增加签名或
可信 release 仓库约束。
