# Windows 发布与更新说明

## 当前发布方式

项目通过 GitHub Releases 分发 Windows 桌面端，仓库信息如下：
- `owner`: `byteD-x`
- `repo`: `wechat-bot`

当前发布策略：
- 正式发布走 GitHub Actions，不再在本地直接上传 Release 附件
- 默认只构建 `portable + NSIS setup`
- `MSI` 仅保留为按需手工构建产物
- 应用内自动更新已停用，桌面端只保留“打开 GitHub Releases 页面”的入口

## 默认构建产物

执行 `npm run build:release` 或 `.\build.bat` 后，默认会在 `release/` 目录生成：
- `wechat-ai-assistant-portable-<version>-x64.exe`
- `wechat-ai-assistant-setup-<version>.exe`

按需构建：
- `npm run build:msi`

说明：
- `portable` 适合免安装分发
- `setup` 是默认安装包
- `MSI` 适合企业或特殊分发场景，但不进入日常发版链路

## 发布说明生成规则

每次正式 Release 都必须自动生成“与上一个正式版本相比”的更新说明：
- 当前版本：本次发布 tag，例如 `v1.2.0`
- 上一个版本：按 `git tag --sort=-creatordate` 解析，排除当前 tag 后取最近一个正式 tag
- 说明区间：`previous_tag..current_tag`
- 说明结构固定包含：
  - 标题
  - compare 区间
  - GitHub compare 链接
  - 按 Conventional Commits 分组的变更摘要
  - 原始提交列表

若没有上一个正式 tag，则回退为“从仓库起点到当前 tag”的首版发布说明。

## 本地构建

仅构建产物，不负责正式发布：

```powershell
npm run build:release
```

或：

```powershell
.\build.bat
```

本地构建主要用于调试和兜底。正式 Release 以 GitHub Actions 产物为准。

## GitHub Actions 发版

正式发布入口：
- 推送 `v*` tag
- 或在 Actions 中手动触发 `release` workflow，并指定已有 tag

工作流固定步骤：
1. 解析当前 tag
2. 定位上一个正式 tag
3. 构建 Python 后端
4. 构建 Electron 默认安装产物
5. 生成 Release Notes
6. 上传附件到 GitHub Release

默认上传附件：
- `setup.exe`
- `portable.exe`
- `SHA256SUMS.txt`

## 构建与发布验证

1. 执行 `npm run build:release`，确认 `release/` 下仅生成 `setup` 和 `portable`。
2. 执行 `npm run build:msi`，确认仍可单独生成 `msi`。
3. 确认产物中不包含 `data/chat_exports`、日志、数据库、`api_keys.py`、`config_override.json` 等运行数据。
4. 推送新 tag 后，确认 GitHub Actions 成功创建或更新 Release。
5. 确认 Release 正文包含 `previous_tag...current_tag` 对比说明与 commit 分组摘要。

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

## 2026-03-17 桌面端主链路与运行时配置体系修复

本节可直接作为本轮发布说明或 PR 摘要使用，重点覆盖“用户可见变化 / 架构变化 / 验证方式”。

### 用户可见变化

- 桌面端恢复可点击状态，导航、窗口按钮和仪表盘主操作不再因前端初始化异常整体失效。
- 仪表盘、消息中心、系统日志、配置中心完成清理与重接线，页面文本乱码已移除，主流程交互恢复。
- 设置页支持真实配置加载、保存反馈、提示词预览、更新检查、预设编辑、预设连接测试和 Ollama 模型列表刷新。
- 启动机器人后的状态反馈更完整，前端可显示运行时预设、配置变更数量、运行时热应用反馈和更新下载状态。
- 语音消息转文字链路补齐失败兜底，转写失败时不会静默吞掉，界面和日志能反映真实结果。
- 回复发送链路修复“前端显示成功但微信未实际发出”的假阳性问题，发送失败会暴露真实错误而不是误记成功。
- 项目文档新增系统级链路说明，可直接查看启动、消息处理、语音转文字、RAG、配置热更新和状态诊断的实现路径。

### 架构变化

- 新增中心化配置快照服务 `backend/core/config_service.py`，运行时统一从快照读取配置，减少多来源配置分散读取。
- 新增配置审计模块 `backend/core/config_audit.py`，为 `/api/config/audit`、设置页变更提示和运行时生效说明提供统一数据来源。
- `backend/api.py`、`backend/bot_manager.py` 与 `backend/bot.py` 之间补齐配置保存、热应用、状态广播和运行时反馈闭环。
- `AgentRuntime` 补强 `reasoning_content` 回退、情绪分析降级、群聊发送者注入和画像刷新频率控制，减少 OpenAI-compatible 差异导致的空回复或脏状态。
- `sender.py`、`bot.py` 与音频转写模块统一了发送成功判定、错误上抛和转写结果解析，避免底层异常被误吞。
- `WcferryWeChatClient` 补充限时 best-effort 清理与版本校验相关修复，减少 stop/reconnect 时的拖尾超时和运行时产物污染。
- Electron 主进程、preload 和 renderer 重新梳理初始化链路，增加渲染日志回传、启动页收口和页面容错，避免单页脚本异常拖死整窗口。
- 运行产物统一收口到 `data/runtime/`，并通过 `.gitignore` 忽略 `data/runtime/` 与 `*.log.*`，降低测试缓存和日志误入仓库的概率。

### 验证方式

本轮验证以项目 `.venv` 为准，已实际执行：

- `E:\Project\wechat-chat\.venv\Scripts\python.exe -m pytest -q`
  - 结果：`99 passed, 3 warnings`
- `E:\Project\wechat-chat\.venv\Scripts\python.exe -m pytest tests\test_api.py -q`
  - 结果：通过，覆盖 API 状态、配置保存、提示词预览与运行时反馈链路
- `E:\Project\wechat-chat\.venv\Scripts\python.exe -m pytest tests\test_bot.py tests\test_handlers.py tests\test_agent_runtime.py tests\test_optimization_tasks.py -q`
  - 结果：通过，覆盖 Bot 主链、发送判定、语音链路、运行时降级与 WCFerry 清理逻辑
- `git show -s --format=%h%n%s%n%b HEAD`
  - 结果：当前提交说明已按模块列出主要改动

建议发布前再做一次人工验收：

1. 以管理员身份启动 `.\dev.bat`。
2. 在桌面端验证导航切换、设置保存、提示词预览、更新检查。
3. 点击“启动机器人”，确认状态变更和日志输出正常。
4. 用真实微信发送文本、语音、带 emoji 的消息各一条，确认机器人真实回复到微信客户端。

## 2026-03-17 成本定价默认快照补齐

本批补齐了成本页默认价格目录中已能从官方公开页面直接核实的模型价格，优先覆盖当前实际可配置且已经接入成本统计的主流供应商。

- 补入 Qwen 的 `qwen-flash-latest`、`qwen3.5-flash`，并按最新官方计费页更新 `qwen-max-latest` 与 `qwen3-coder-plus`
- 补入 Perplexity 的 `sonar`、`sonar-pro`、`sonar-reasoning-pro`
- 补入 Together 的 `deepseek-ai/DeepSeek-V3.1` 与 `meta-llama/Llama-3.3-70B-Instruct-Turbo`
- 补入 Fireworks 的 `accounts/fireworks/models/deepseek-v3p1`
- 补入 Groq 的 `meta-llama/llama-4-scout-17b-16e-instruct`

说明：

- 本轮仅填入能从官方公开页直接确认数值的模型；Doubao、Zhipu、Moonshot、SiliconFlow 等仍保留为空或部分为空，避免误填导致成本核算失真
- Ollama 继续按本地模型 `0` 成本口径处理
