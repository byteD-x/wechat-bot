# Windows 发布与更新说明

## 当前发布方式

项目通过 GitHub Releases 分发 Windows 桌面端，仓库信息如下：
- `owner`: `byteD-x`
- `repo`: `wechat-bot`

Electron 打包配置位于 `electron-builder.yml`，自动更新使用 `electron-updater`，读取构建产物中的 `app-update.yml` 与 `latest.yml`。

## 构建产物

执行 `npm run build:release` 或 `.\build.bat` 后，会在 `release/` 目录生成以下产物：
- `wechat-ai-assistant-portable-<version>-x64.exe`
- `wechat-ai-assistant-setup-<version>.exe`
- `wechat-ai-assistant-installer-<version>-x64.msi`
- `latest.yml`
- `*.blockmap`

说明：
- `portable` 适合免安装分发。
- `setup` 是 NSIS 安装包，也是应用内自动更新的主要目标。
- `msi` 适合企业或手动分发场景。
- `latest.yml` 与 `blockmap` 由 `electron-builder` 自动生成，自动更新依赖它们。

## 应用内更新行为

桌面端支持以下更新流程：
- 启动后自动检查更新。
- 运行期间按策略轮询更新。
- 发现新版本时展示系统通知。
- 在“设置 -> 应用更新”中支持手动检查和跳转下载。

注意：
- `NSIS` 是 Windows 自动更新的主路径。
- `MSI` 安装用户也会收到新版本提醒，但当前动作是打开 GitHub Releases 页面，不做应用内静默升级。

## 本地构建

仅构建，不发布：

```powershell
npm run build:release
```

或：

```powershell
.\build.bat
```

## 发布到 GitHub Releases

先准备 `GH_TOKEN`：

```powershell
$env:GH_TOKEN="你的 GitHub Token"
```

再执行：

```powershell
npm run publish:github
```

## 构建与发布验证

1. 执行 `npm run build:release`，确认 `release/` 下已生成 `setup`、`msi`、`latest.yml`。
2. 执行 `npm run publish:github`，确认对应 Release 附件上传完成。
3. 安装应用后进入“设置 -> 应用更新”，点击“检查更新”。
4. 发布更高版本后再次启动应用，确认能收到新版本提示。

## 2026-03-15 优化计划落地

### 第一批

本批完成了桌面端可见性和故障恢复能力的补强：
- 消息中心新增“消息详情”面板，可查看模型预设、Token 估算、执行耗时、情感识别和上下文召回摘要。
- 仪表盘新增启动进度、运行诊断和“一键恢复”入口。
- Splash 页面改为带进度条的阶段提示。
- 后端新增 `/api/recover`，并在 `/api/status` 中返回 `startup` 与 `diagnostics`。

### 第二批

本批完成了运行可观测性与配置预览能力：
- 仪表盘新增“健康监控”卡片，展示 CPU、内存、队列积压、AI 延迟和依赖健康检查。
- 合并回复流程会回传当前状态，前端可直接显示是否仍在等待合并窗口结束。
- 设置页新增提示词预览，可在不保存配置的前提下查看最终系统提示词。
- 后端新增 `/api/preview_prompt`。

### 第三批

本批完成了低侵入的性能和交互优化：
- `AIClient` 支持 `tiktoken` 精确 Token 估算，并在缺少依赖时回退原有估算。
- 关键词情感识别加入缓存，减少重复计算。
- 桌面端补充快捷键：`Ctrl+1/2/3/4`、`Ctrl+R`、`Ctrl+Q`、`F5`。
- Splash 阶段预加载主界面入口模块，降低主窗口首屏等待。

### 第四批

本批完成了底层稳定性、RAG 精排和运行监控补齐：
- `AIClient` 改为带引用计数的共享 `httpx.AsyncClient` 连接池。
- `MemoryManager` 新增 `get_recent_context_batch()` 批量上下文读取接口。
- 传输层补齐 `BaseTransport` 抽象，`WcferryWeChatClient` 已接入。
- 配置热重载优先使用 `watchdog` 事件监听，缺失依赖时自动回退轮询，并带防抖。
- 新增 `/api/metrics` Prometheus 风格指标导出接口。
- 运行期 RAG 先做轻量重排，并支持可选本地 `Cross-Encoder` 精排；缺失依赖或本地模型目录时自动回退。
- 统一项目的微信版本基线为 `3.9.12.51`，并将 `compat_ui` 明确为遗留兼容链路。

### 第五批（安全与稳定性补丁）

本批完成了本机默认安全基线、配置生效一致性和前端注入面收口：

- Web API 默认仅允许本机访问（`127.0.0.1/localhost`），并支持 `WECHAT_BOT_API_TOKEN` 轻量鉴权；Electron 会自动携带 Token，手工调试可在 `python run.py web` 输出中获取。
- 修复 `prompt_overrides.py` 未生效：启动时会将其合并进 `bot.system_prompt_overrides`（保持“现有配置优先”）。
- 修复提示词注入在运行期与预览不一致：`user_profile` 支持 Pydantic 对象，同时 `profile_inject_in_prompt` / `emotion_inject_in_prompt` 作为开关统一生效。
- 让记忆保留策略配置真正生效：初始化与热重载时把 `memory_ttl_sec` / `memory_cleanup_interval_sec` 传入并更新。
- 修复语音转写依赖不一致：`audio_transcription` 统一使用 `httpx`，避免缺少 `requests` 导致运行时报错。
- 清理后端不可达死代码与指标格式：健康检查构建逻辑去重，Prometheus `wechat_bot_health_check` 的 `HELP/TYPE` 不再重复输出。
- 脚本与主配置路径对齐：`setup_wizard` 改写 `data/config_override.json`，`check.py` 读取 `backend/config.py` 并尝试应用 override。
- 前端彻底移除动态 `innerHTML/insertAdjacentHTML` 渲染：Settings/Dashboard/Logs/Messages 全部改为 DOM 构建或 `textContent`，降低 XSS 风险。
- Electron 安全基线增强：启用 `sandbox`，阻止非 `file:` 导航与重定向，`window.open` 统一 deny 并仅允许外部打开 `http(s)/mailto`。
- 运行时产物目录收口：忽略 `data/runtime/`，避免测试缓存误入版本控制。

### 本轮验证

- `python -m py_compile backend\core\agent_runtime.py backend\config_schemas.py backend\config.py tests\test_agent_runtime.py`
  - 结果：通过
- `python -m pytest tests\test_agent_runtime.py tests\test_optimization_tasks.py tests\test_runtime_observability.py -q`
  - 结果：`4 passed, 2 skipped`
  - 说明：跳过由当前环境缺少 `aiosqlite` 触发，不是代码报错

补充：本机 `.venv` 环境验证（含 Quart）

- `.venv\Scripts\python.exe -m pytest tests\test_api.py -q`
  - 结果：`16 passed`
