# 手工发版兜底流程

正式发版优先使用 GitHub Actions 的 `release` workflow。只有在 Actions 因账号、runner 或平台状态无法启动时，才使用本流程处理已经本地构建好的 Windows 产物。

GitHub Release 正式受管资产包括：

- `wechat-ai-assistant-portable-<version>-x64.exe`：供用户手动下载，应用内更新不使用该资产。
- `wechat-ai-assistant-setup-<version>.exe`
- `SHA256SUMS.txt`
- `latest.yml`：electron-updater 更新元数据。
- `wechat-ai-assistant-setup-<version>.exe.blockmap`：setup 差分更新元数据。

`SHA256SUMS.txt` 只要求覆盖 portable/setup 两个 exe；`latest.yml` 和 `.blockmap` 不需要写入 `SHA256SUMS.txt`，同步脚本仍会计算它们的 SHA256 并与 GitHub Release 远端 digest/size 对比。

默认 official signed release 仍要求 Authenticode 签名通过。个人开发者可选择 unsigned community release，但必须保留上述受管资产、SHA256 校验、`latest.yml` / `.blockmap` 和 GitHub Release 资产标识，并预期用户安装时看到 Windows SmartScreen 或未签名发布者提示。

## 适用场景

- `v*` tag 已推送，版本号、Release Notes 和本地产物已经验证通过。
- GitHub Actions 没有进入构建步骤，或因为平台侧问题无法创建完整 Release。
- 需要修复 draft release 中的半成品资产，例如 `state=starter`、`digest=null`，或大小不匹配的 exe / electron-updater 元数据。

## 本地前置检查

手工 official signed release 也不能跳过 Windows 签名门禁。`check_windows_release_readiness.py` 必须返回 `passed` 后，才允许执行 `--apply --publish`。

```powershell
.\.venv\Scripts\python.exe scripts\validate_release_metadata.py --tag v1.6.3
.\.venv\Scripts\python.exe scripts\generate_release_notes.py --current-tag v1.6.3 --output .git\release-notes-v1.6.3.tmp
$managedAssets = @(
  "release\wechat-ai-assistant-portable-1.6.3-x64.exe"
  "release\wechat-ai-assistant-setup-1.6.3.exe"
  "release\SHA256SUMS.txt"
  "release\latest.yml"
  "release\wechat-ai-assistant-setup-1.6.3.exe.blockmap"
)
Get-Item $managedAssets
Get-FileHash -Algorithm SHA256 $managedAssets
.\.venv\Scripts\python.exe scripts\check_windows_release_readiness.py --release-dir release --version 1.6.3
```

unsigned community release 使用同一门禁，并显式追加签名例外：

```powershell
.\.venv\Scripts\python.exe scripts\check_windows_release_readiness.py --release-dir release --version 1.6.3 --allow-unsigned-community
```

## Dry-run

默认只生成计划，不删除、不上传、不发布。

```powershell
npm run release:manual -- --tag v1.6.3 --repo byteD-x/wechat-bot --release-dir release --notes-file .git\release-notes-v1.6.3.tmp --json
```

检查输出中的字段：

- `delete`：只应包含同名的半成品或不匹配资产。
- `upload`：应只包含缺失或需要重传的 `portable.exe`、`setup.exe`、`SHA256SUMS.txt`、`latest.yml` 或 setup `.blockmap`。
- `complete`：为 `true` 时说明远端资产已经完整。
- `unexpected`：脚本不会自动删除，必须人工处理；存在 unexpected 资产时，`--apply` 或 `--publish` 会拒绝继续。

## 应用并发布

只有 Windows release readiness gate 通过，且 dry-run 结果符合预期、没有 unexpected 资产后，才执行。unsigned community release 必须先通过带 `--allow-unsigned-community` 的门禁：

```powershell
npm run release:manual -- --tag v1.6.3 --repo byteD-x/wechat-bot --release-dir release --notes-file .git\release-notes-v1.6.3.tmp --apply --publish --json
```

脚本会按以下顺序执行：

1. 确认本地 `portable.exe`、`setup.exe`、`SHA256SUMS.txt`、`latest.yml` 和 setup `.blockmap` 存在。
2. 校验 `SHA256SUMS.txt` 覆盖两个 exe，且 hash 与本地文件一致；`latest.yml` 和 `.blockmap` 不要求进入 `SHA256SUMS.txt`。
3. 创建或更新 draft release。
4. 删除同名但不健康的远端资产。
5. 逐个上传缺失资产。
6. 每次上传后重新读取 GitHub Release assets，并校验 `state=uploaded`、大小和 `sha256` digest。
7. 只有全部资产完整后，才把 draft 发布为正式 Release。

如果任一步失败，脚本会停止并保持 Release 为 draft。再次执行前，应先 dry-run 检查是否留下新的半成品资产。

## 正式发布后复核

```powershell
gh release view v1.6.3 --repo byteD-x/wechat-bot --json tagName,isDraft,publishedAt,assets
```

正式 Release 必须同时满足：

- `isDraft=false`
- 包含 `wechat-ai-assistant-portable-<version>-x64.exe`
- 包含 `wechat-ai-assistant-setup-<version>.exe`
- 包含 `SHA256SUMS.txt`
- 包含 `latest.yml`
- 包含 `wechat-ai-assistant-setup-<version>.exe.blockmap`
- 五个资产均为 `state=uploaded`，大小和 digest 与本地记录一致
- unsigned community release 需在 Release 标识或说明中明确未签名社区版属性，不能标记为 official signed release
