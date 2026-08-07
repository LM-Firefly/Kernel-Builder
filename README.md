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

`kernel-builder.json` 固定包含三个渠道：`alpha`、`meta`、`smart`。可以修改它们的仓库地址、
ref、后缀和 patch 目录，但不要改变 `id`，这样 APP 的列表解析和回退逻辑保持稳定。
工作流按 UTC 每 4 小时检查一次上游（`0 */4 * * *`），也支持手动构建和上游通过
`repository_dispatch` 发送 `kernel-update`。每次成功运行都会刷新固定 Release 的资产和
Release Notes 时间，即使版本未变化也会留下本次检查时间。

## 工作流阶段

1. `validate-config` 解析 `.env`，校验 JSON、三个渠道、patch 目录、工具链，并生成矩阵。
2. `build-core` 为每个渠道独立 checkout 壳与内核，应用 patch，只构建 ARM64。
3. `verify-core` 用 `file`/`readelf` 校验 ELF、架构和 `MihomoMain` 导出，并锁定源 commit。
4. `package-release` 压缩 `.so`，生成 sidecar SHA-256、`kernel-checksums.txt`、`kernel-index.json` 和校验报告。
5. `publish-release` 只在全部渠道成功后更新固定的 GitHub prerelease。

## 固定 Release 合约

工作流不会为每次运行创建新的 Release。它始终更新以下固定 Release：

| 字段 | 值 |
| --- | --- |
| Tag | `kernel` |
| Name | `Build Kernel` |
| 类型 | prerelease，且不标记为 latest |
| JSON 稳定地址 | `https://github.com/<owner>/<repo>/releases/download/kernel/kernel-index.json` |
| 支持 ABI | `arm64-v8a`（只写入 JSON，不写入资产文件名） |

固定资产名会被覆盖，不会在同一 Release 中残留旧 commit 文件；实际源版本始终记录在
`kernel-index.json`。APP 不需要从资产文件名反向解析渠道，直接读取 `kernels[]` 的 `id` 和 `name`。

## 最终 Release 资产

最终 Release 只上传这些文件（内部 Actions Artifact 不会出现在 Release 页面）：

```text
kernel-alpha.so.xz
kernel-alpha.so.xz.sha256
kernel-meta.so.xz
kernel-meta.so.xz.sha256
kernel-smart.so.xz
kernel-smart.so.xz.sha256
kernel-checksums.txt
kernel-index.json
kernel-index.json.sha256
```

压缩使用 `xz -9e`，即 LZMA2 极限压缩；Release 页面提供 `kernel-checksums.txt`，每个压缩库和
`kernel-index.json` 还有独立的 SHA-256 文件。`kernel-index.json` 使用 schema version 3，`kernels[]` 是
固定的 `alpha`、`meta`、`smart` 列表，每项直接提供 `id`、`name`、`version`、`asset`、
`downloadUrl`、`checksumUrl`、`sha256`、ABI 和源 commit。APP 必须先校验
manifest，再校验目标 `.so.xz`，解压后验证 ARM64 ELF 和 `MihomoMain`，最后写入临时文件并
原子替换；失败时保留当前内核或回退到内置内核。

APP 只需读取 `kernels` 数组，不需要解析资产文件名：

```json
{
  "id": "alpha",
  "name": "Mihomo Alpha",
  "version": "v1.19.29",
  "asset": "kernel-alpha.so.xz",
  "downloadUrl": "https://github.com/owner/repo/releases/download/kernel/kernel-alpha.so.xz",
  "checksumUrl": "https://github.com/owner/repo/releases/download/kernel/kernel-alpha.so.xz.sha256",
  "sha256": "..."
}
```

### JSON 解析规范

1. 先校验 `schemaVersion == 3`、`abi == "arm64-v8a"`、`shellAbi` 和 `release.manifestUrl`。
2. 将 `kernels` 当作固定列表，必须恰好包含 `alpha`、`meta`、`smart` 三项；用 `id` 作为唯一键，
   用 `name` 作为显示文本，推荐显示顺序为 Alpha、Meta、Smart。
3. 下载时只使用该项的 `downloadUrl` 和 `checksumUrl`，不要拼接或解析 `asset` 文件名。
4. 先校验 SHA-256，再解压 XZ；解压结果必须是 `arm64-v8a` ELF，并导出 `MihomoMain`。
5. 缺字段、未知 `schemaVersion`、重复/缺失 id、哈希失败或 ABI 不匹配时，保留当前内核；`defaultKernel`
   只在 Alpha 可用时生效。

## Actions Artifact 与 Release 的区别

| 阶段 | Artifact 名称 | 内容 | 保留时间 | 是否对用户发布 |
| --- | --- | --- | --- | --- |
| 构建后 | `raw-arm64-<channel>` | 未压缩 `.so`、版本 properties、源 commit JSON | 7 天 | 否 |
| 验证后 | `verified-arm64-<channel>` | 通过 ELF/入口点验证的同一组文件 | 7 天 | 否 |
| 打包后 | `release-assets-arm64` | 最终压缩包、校验文件、JSON、Release notes | 14 天 | 否 |
| 发布后 | 固定 Release `kernel` / `Build Kernel` | 上表“最终 Release 资产” | 由 GitHub 保留 | 是 |

## 本地检查

```text
scripts/validate-config.sh .env kernel-builder.json
scripts/verify-core.sh <libmihomocore.so> arm64-v8a
scripts/package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at> <release-repository> <template-repository> <template-ref> <go-version> <ndk-version>
scripts/verify-release.sh <release-dir>
```

SHA-256 只能检测传输损坏，不能单独证明发布者身份。生产环境还应在 APP 侧增加签名或
可信 release 仓库约束。
