# 桌面端自动升级与发布策略调研

本文记录 2026-06-09 对桌面端自动升级和发布流程的调研结论。目标是让 Windows 安装版升级更优雅、更快速、更稳定，同时保留当前已经建立的发布安全门禁。

## 当前项目状态

当前项目使用 `electron-builder` 构建 Windows `NSIS setup` 和 `portable` 两类产物：

- `electron-builder.yml` 中 `win.target` 包含 `portable` 和 `nsis`。
- `nsis.artifactName` 为 `wechat-ai-assistant-setup-${version}.exe`。
- `portable.artifactName` 为 `wechat-ai-assistant-portable-${version}-${arch}.exe`。
- `nsis.differentialPackage` 当前为 `true`，NSIS setup 会生成可供后续差分更新使用的 `.blockmap`。
- `electron-builder.yml` 已配置 GitHub provider：`byteD-x/wechat-bot`、`latest` channel、`publishAutoUpdate: true`。
- 应用内更新由 `src/main/update-manager.js` 自研实现：读取 GitHub Releases API，下载完整 `setup.exe`，校验 `SHA256SUMS.txt`，再启动安装器。
- GitHub Release 发布由 `.github/workflows/release.yml` 构建并调用 `scripts/sync_github_release_assets.py` 同步资产。
- 发布前已有 `scripts/check_windows_release_readiness.py` 门禁，覆盖命名、checksum、Authenticode 和 Electron 安全基线；默认 official signed release 仍要求 Authenticode 通过。

这套方案的优点是可控、易审计、与现有 UI 状态机贴合。本批改动只先建立 `electron-updater` 所需的发布元数据通道：构建产物可以保留 `latest.yml` 与 setup `.blockmap`，但运行时仍由现有 `UpdateManager` 兜底，继续走 GitHub Releases API、完整 `setup.exe` 下载和 checksum 校验。

## 外部成熟方案

### 1. electron-updater + electron-builder publish

官方文档把 `electron-updater` 定位为 electron-builder 的自动更新方案。它的流程是：构建发布元数据 `latest.yml`，上传产物和元数据，应用端查询发布服务器并执行更新。Windows 的自动更新目标是 NSIS。官方还明确它相比 Electron 内置 `autoUpdater` 支持 Windows 签名校验、下载进度、staged rollout、多 provider 和自动生成/发布元数据。

参考资料：

- [electron-builder Auto Update](https://www.electron.build/docs/features/auto-update)
- [electron-builder publish](https://www.electron.build/docs/publish/)
- [NsisUpdater API](https://www.electron.build/docs/api/electron-updater.class.nsisupdater/)

适配本项目的结论：

- 这是最适合当前架构的主路线，因为项目已经使用 `electron-builder + NSIS + GitHub Releases`。
- 可以保留现有 `portable` 手动更新策略，仅把安装版从自研下载器逐步切到 `electron-updater`。
- 需要让 release 资产包含 `latest.yml`、安装包 `.blockmap`，并评估是否开启 `nsis.differentialPackage`。
- 需要把当前 `UpdateManager` 的 UI 状态字段映射到 `electron-updater` 事件：`checking-for-update`、`update-available`、`download-progress`、`update-downloaded`、`error`。
- 需要继续保留发布门禁，默认避免 `latest.yml` 指向未签名、错名或半成品资产；unsigned community release 只能通过显式 `--allow-unsigned-community` 例外放宽签名门槛。

### 2. Electron 内置 autoUpdater

Electron 官方内置 `autoUpdater` 支持 macOS 和 Windows。Windows 下会根据打包形态选择 MSIX 或 Squirrel.Windows；Squirrel.Windows 需要处理安装事件和首启文件锁，MSIX 可使用直接 MSIX 链接或 JSON feed。

参考资料：

- [Electron autoUpdater](https://www.electronjs.org/docs/latest/api/auto-updater)

适配本项目的结论：

- 不建议作为当前主路线。项目已经是 electron-builder NSIS，而 Electron 内置 `autoUpdater` 的 Windows 传统安装路径偏 Squirrel.Windows。
- 若为了使用内置 `autoUpdater` 改成 Squirrel.Windows，会引入安装事件、快捷方式 AppUserModelId、首启锁等迁移成本。
- 对当前 Windows 管理员权限、后端资源包、便携版共存的应用形态来说，切 Squirrel 的收益不如 `electron-updater + NSIS`。

### 3. MSIX App Installer / Windows 原生更新

Microsoft 的 MSIX App Installer 支持 Windows 10 2004 及以后版本和 Windows 11，允许通过 `.appinstaller` 配置启动时检查、检查间隔、是否展示提示、是否阻止旧版本启动，以及 fallback `UpdateURI`。它更接近 Windows 原生分发和企业设备管理。

参考资料：

- [MSIX Auto-update and repair apps](https://learn.microsoft.com/en-us/windows/msix/app-installer/auto-update-and-repair--overview)

适配本项目的结论：

- 适合企业分发、内网部署、MDM/Intune 管理和强制更新场景。
- 不适合作为马上替换 NSIS 的最小方案，因为它会改变安装包形态、签名要求、更新配置和用户安装入口。
- 可作为第二阶段并行分发通道：保留 NSIS 面向普通用户，新增 MSIX/AppInstaller 面向企业或受控环境。

### 4. 成熟开源项目参考：Joplin

Joplin 桌面端是长期维护的 Electron 应用。它封装 `AutoUpdaterService`，使用 `electron-updater` 处理下载和安装事件，同时保留自己的版本选择、预发布过滤、平台/架构资产选择和 UI 通知逻辑。

参考资料：

- [Joplin AutoUpdaterService.ts](https://github.com/laurent22/joplin/blob/dev/packages/app-desktop/services/autoUpdater/AutoUpdaterService.ts)

适配本项目的结论：

- 这种“业务状态机自管，底层更新引擎交给 electron-updater”的模式最值得借鉴。
- 本项目可以继续保留当前前端 `updater.*` 状态、跳过版本、手动检查、便携版手动更新入口，把下载与安装执行层替换为 `electron-updater`。

## 推荐路线

### P1：建立 electron-updater 元数据通道

目标：不替换现有更新器，先让 `electron-updater` 所需的 GitHub provider 元数据随本项目 NSIS 安装版产物生成并进入发布资产治理。

本批已落地的最小改动：

- 添加 `electron-updater` 依赖。
- 在 `electron-builder.yml` 增加明确 `publish` 配置：
  - provider: `github`
  - owner: `byteD-x`
  - repo: `wechat-bot`
  - channel: `latest`
  - publishAutoUpdate: `true`
- 将 `nsis.differentialPackage` 设为 `true`，让 setup `.blockmap` 成为可发布资产。
- `build.bat` 保留 `release/latest.yml` 与 setup `.blockmap`，只继续清理 `win-unpacked`、`builder-debug.yml`、`app-update.yml`、`*.msi` 等非默认发布内容。
- release workflow 与运行时更新器暂时仍保留现有链路；本批不切换 `src/main/update-manager.js` 的执行后端。

验证方式：

- `npm run build:installer` 后确认 `release/` 产生 `latest.yml` 和 `.blockmap`。
- 在本地测试 release feed 或 GitHub draft 中验证 `autoUpdater.checkForUpdates()` 能读取 metadata。
- 保持 `node --test tests\update-manager.test.cjs tests\main-ipc-security.test.cjs tests\main-backend-manager.test.cjs` 通过，确认现有运行时兜底不受影响。

### P1：扩展发布资产同步与 readiness gate

目标：让自动更新元数据进入发布治理，避免客户端读到半成品 metadata。

最小改动：

- `scripts/check_windows_release_readiness.py` 增加 `latest.yml` 校验：
  - version 与 tag 版本一致。
  - path 指向目标版本 setup。
  - files 中 sha512 存在。
  - setup `.blockmap` 存在时与 setup 文件同版本。
- `scripts/check_windows_release_readiness.py` 保持 official signed release 默认 Authenticode 门槛，并提供 `--allow-unsigned-community` 给个人开发者未签名社区版使用。
- `scripts/sync_github_release_assets.py` 支持同步 `latest.yml` 和 `.blockmap`，并把它们纳入 unexpected assets 规则。
- `docs/MANUAL_RELEASE_FALLBACK.md` 补充 metadata 资产检查。

验证方式：

- `pytest tests\test_windows_release_readiness.py tests\test_github_release_assets.py -q`
- 对一个临时 release 目录构造缺失 `latest.yml`、错版本 `latest.yml`、缺 `.blockmap` 的失败用例。

### P2：把现有 UpdateManager 改成双后端适配器

目标：保留当前 UI/IPC 契约，降低一次性替换风险。

最小改动：

- 抽象更新后端接口：
  - `checkForUpdates(options)`
  - `downloadUpdate()`
  - `prepareInstall()`
  - `installPreparedUpdateAndQuit()`
  - `openDownloadPage()`
  - `getState()`
- 现有 GitHub 全量下载器作为 `GitHubInstallerUpdaterBackend`。
- 新增 `ElectronUpdaterBackend`，把 `electron-updater` 事件转成现有 `updater.*` 状态字段。
- portable 环境继续走手动更新，不启用自动安装。

验证方式：

- 现有 `tests/update-manager.test.cjs` 全部保留。
- 新增 electron-updater mock 测试，覆盖事件流到状态字段映射。
- `node --test tests\update-manager.test.cjs tests\main-ipc-security.test.cjs`

### P2：启用差分下载与 staged rollout

目标：在安装版上提升更新速度，并降低新版本一次性全量推送风险。

最小改动：

- 基于已生成的 setup `.blockmap`，在运行时后端切换后确认 updater 实际尝试差分下载。
- 在 `latest.yml` 中预留 staged rollout 机制，先人工设置 `stagingPercentage` 做灰度。
- 保持本项目跳过版本功能；对 staged rollout 不命中的用户，UI 应显示“当前无可用更新”。

验证方式：

- 使用两个相邻版本构建产物，确认 updater 尝试差分下载。
- 人工 Windows VM 安装旧版后升级到新版，记录下载体积、耗时和日志。

### P3：新增 MSIX/AppInstaller 企业分发通道

目标：面向企业用户或受控环境提供 Windows 原生更新能力。

最小改动：

- 保留 NSIS 主通道。
- 单独建立 `build:msix` 或 `build:appinstaller` 试验脚本。
- 生成 `.appinstaller`，配置 `HoursBetweenUpdateChecks`、`ShowPrompt`、`UpdateBlocksActivation`。
- 明确证书、签名、托管 URL 和企业部署说明。

验证方式：

- Windows 11 VM 安装 MSIX。
- 修改 `.appinstaller` 指向更高版本，验证启动时更新行为。
- 验证管理员权限和后端资源访问是否仍满足当前项目约束。

## 不建议的路线

- 不建议继续扩大自研下载器功能来复刻 `electron-updater`。这样会持续承担 metadata、差分、签名校验、灰度、失败恢复和安装事件细节。
- 不建议当前阶段切到 Squirrel.Windows。它和项目现有 NSIS 资产、管理员权限、便携版策略不一致，迁移收益不足。
- 不建议把 portable 做成自动覆盖更新。便携版运行文件自替换风险高，继续保留“检查新版本 + 打开发布页”更稳。

## 建议最终形态

- 安装版：`electron-updater + NSIS + GitHub provider`，支持进度、签名校验、差分更新、staged rollout。
- 便携版：继续手动更新，只提示新版本并打开 GitHub Releases。
- 发布：GitHub Actions 构建，默认签名并生成 `latest.yml` / `.blockmap` / `SHA256SUMS.txt`；unsigned community release 可显式放弃签名门槛，但仍由 readiness gate 校验全部资产并由 `sync_github_release_assets.py` 统一发布。未签名社区版会触发 Windows SmartScreen 或未签名发布者提示。
- 企业分发：后续新增 MSIX/AppInstaller 通道，不影响普通用户 NSIS 主通道。
