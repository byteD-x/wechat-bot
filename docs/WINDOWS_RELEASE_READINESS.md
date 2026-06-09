# Windows Release Readiness 门禁

本门禁用于发布前检查本地 Windows 产物是否具备进入人工安装升级演练和 GitHub Release 发布的最低条件。它不负责构建、签名、安装、上传或发布产物。

## 本地检查命令

```powershell
python scripts/check_windows_release_readiness.py --release-dir release --version 1.6.3
python scripts/check_windows_release_readiness.py --release-dir release --version 1.6.3 --json
python scripts/check_windows_release_readiness.py --release-dir release --version 1.6.3 --allow-unsigned-community
```

正式 GitHub Actions 发布必须先配置 Windows 代码签名 Secrets：

```powershell
$pfxPassphrase = Read-Host "PFX password" -AsSecureString
.\scripts\setup_windows_signing_secrets.ps1 -CertificatePath C:\path\to\codesign.pfx -Repository byteD-x/wechat-bot -Password $pfxPassphrase
```

脚本会上传：

- `WINDOWS_SIGNING_CERTIFICATE_BASE64`
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`

该 `.pfx` 必须来自受信任代码签名证书，并包含 Code Signing EKU `1.3.6.1.5.5.7.3.3`。自签证书或普通 TLS 证书不能作为正式发版凭据。

默认 official signed release 仍要求 Authenticode 签名通过；个人开发者若选择 unsigned community release，必须显式传入 `--allow-unsigned-community`。该模式只放宽签名门槛，仍要求 `SHA256SUMS.txt`、`latest.yml`、setup `.blockmap` 和 GitHub Release 资产标识完整，并且安装时会触发 Windows SmartScreen 或未签名发布者提示。

建议在本地发布前传入 `--version`。带版本号时，脚本只检查目标版本的安装版和便携版产物，并允许 `release/` 中保留命名合法的历史版本 `.exe`；但不符合发布命名规则的 `.exe` 仍会阻塞，避免把临时备份、MSI 或错名产物误发布。

脚本退出码含义：

- `0`: 所有自动检查通过。
- `1`: 存在阻塞项，不能发布。

## 自动阻塞项

脚本至少检查以下内容：

- `release/` 中必须各有一个目标版本的安装版和便携版产物：
  - `wechat-ai-assistant-setup-<version>.exe`
  - `wechat-ai-assistant-portable-<version>-x64.exe`
- 不传 `--version` 时，`release/` 下只能存在一组安装版和便携版产物；传入 `--version` 时，命名合法的其他历史版本会被忽略。
- 不能混入不符合命名约束的 `.exe`，避免把 MSI、临时备份或错名产物误发布。
- `SHA256SUMS.txt` 必须存在，并覆盖当前检查范围内的 `.exe`；不传 `--version` 时覆盖 `release/` 下所有 `.exe`，传入 `--version` 时覆盖目标版本产物。
- `SHA256SUMS.txt` 中记录的 SHA256 必须与本地文件实际 hash 一致。
- `latest.yml` 必须存在，并作为 electron-updater 正式发布元数据接受门禁校验；传入 `--version` 时，`version` 必须与目标版本一致。
- `latest.yml` 的 `path` 必须指向 `wechat-ai-assistant-setup-<version>.exe`，`files` 必须至少包含该 setup 产物且带有 `sha512`。
- `wechat-ai-assistant-setup-<version>.exe.blockmap` 必须存在，确保安装版自动更新 metadata 不会指向缺失的差分元数据。
- 默认模式下，Authenticode 签名只能在 Windows 上通过 `Get-AuthenticodeSignature` 验证；只有 `Status=Valid` 才算通过。非 Windows、无法检查、未签名或签名状态异常都视为阻塞。
- 仅当显式传入 `--allow-unsigned-community` 时，未签名产物可作为 unsigned community release 继续通过门禁；该例外不适用于 official signed release。
- Electron 安全与 IPC 基线必须保留，包括 BrowserWindow 加固、preload 受控 API、可信 renderer sender 校验、后端请求 allowlist、知识库文件选择限制和诊断支持包脱敏标记。

## Windows 安全与 IPC 审查

高权限 Windows 微信接入场景的威胁模型、失败模式和 IPC 回归检查表记录在 [`docs/WINDOWS_SECURITY_MODEL.md`](WINDOWS_SECURITY_MODEL.md)。

`electron_security_baseline` 只做静态标记检查，用于阻止明显回归；它不能替代人工代码审查、真实 Windows 安装升级演练、生产代码签名证书审计或微信消息收发验证。

## 安装升级演练清单

脚本输出会包含 `installation_upgrade_drill`，该清单需要在真实 Windows 10/11 环境中人工执行并留存证据：

1. 准备旧版 `wechat-ai-assistant-setup-<old-version>.exe`。
2. 准备新版 `wechat-ai-assistant-setup-<new-version>.exe`，确认它已被 `SHA256SUMS.txt` 覆盖。
3. 在干净 Windows 10/11 虚拟机安装旧版，并确认旧版可启动。
4. 升级前记录 `userData/data/app_config.json` 的路径、时间戳和一个无敏感信息的标记值。
5. 运行新版 setup 覆盖升级旧版安装目录。
6. 升级后确认 `userData/data/app_config.json` 仍存在，且标记值未丢失。
7. 启动升级后的应用，验证 `GET /api/ping` 或 `GET /api/readiness` 返回符合目标环境的健康结果。
8. 若失败，记录回滚方式、快照恢复证据和诊断日志摘要。

## 残余风险

- 真实代码签名证书、时间戳服务和证书链信任不能在本地脚本中伪造；脚本只接受 Windows Authenticode 的真实 `Valid` 结果。
- unsigned community release 不具备 Authenticode 身份背书，用户安装或运行时应预期看到 Windows SmartScreen 或未签名发布者提示。
- 真实安装升级演练依赖 Windows 桌面、UAC、安装目录、`userData` 位置和微信环境，不能由纯文件扫描替代。
- `electron_security_baseline` 只能确认关键安全/IPC 标记仍存在，不能证明所有参数校验、业务授权或诊断脱敏路径都完整。
- 该门禁不会上传 GitHub Release，也不会修改 draft release；发布资产同步仍使用既有发布流程。
