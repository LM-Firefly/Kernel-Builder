# YumeBox Kernel Builder

独立的 mihomo 内核构建仓库。它只发布 `libmihomocore.so`，不发布 APP，也不修改 YumeBox
主仓库的 release。壳和 Go adapter 来自配置的模板仓库，构建后的内核通过 GitHub Release
供 APP 下载。

## 自定义内核

编辑 `kernel-builder.json`：

- `template.repository/ref`：提供固定壳、Go adapter 和 `scripts/native-build.main.kts` 的模板仓库。
- `channels[]`：每个渠道可以使用不同的内核仓库、分支或 tag。
- `channels[].patches`：该渠道额外 patch 目录；patch 会叠加到模板仓库已有的 mihomo patch。

用户可以直接 fork 本仓库，修改这些字段后启用自己的 Action。内核源代码不需要复制到
builder 仓库，Action 在 runner 中临时 clone，构建完成后只上传二进制和版本元数据。

## 默认渠道

`stable` 是当前官方 Alpha 内核的 Stable 标签，保证默认配置可用。确认上游稳定 tag 后，
把它的 `ref` 改为具体 tag；`alpha`、`meta`、`smart` 分别对应官方 Alpha、Meta 和 Smart
源。这里的映射只是模板，使用者可以完全替换 repository/ref。

## Release 格式

每次运行产生不可变的 prerelease：

```text
kernel-<channel>-<abi>.so.xz
kernels.json
```

`kernels.json` 包含 ABI、shell ABI、源 commit、显示版本和 SHA-256。APP 下载后必须先校验
SHA-256，再写入临时文件并原子替换；失败时继续使用当前内核或恢复内置内核。

当前 workflow 支持每日构建、手动构建和 `repository_dispatch` 的 `kernel-update` 事件。上游
镜像可以在推送后调用该事件；没有 webhook 时由每日任务兜底。

## 本地检查

```text
scripts/verify-core.sh <libmihomocore.so> <abi>
scripts/package-release.sh <artifact-root> <output-dir> <release-tag> <generated-at>
```

APP 集成时应固定 shell ABI 和 `MihomoMain` 协议；替换内核不会替换壳。
