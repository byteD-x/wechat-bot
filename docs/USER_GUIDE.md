# 使用手册

本文档负责承载详细的使用、配置、运行与排障说明。README 只保留仓库首页所需的高层信息，这份文档负责逐步操作。

## 目录

- [系统链路说明](#系统链路说明)
- [1. 环境要求](#1-环境要求)
- [2. 安装依赖](#2-安装依赖)
- [3. 首次配置](#3-首次配置)
- [4. 启动前检查](#4-启动前检查)
- [5. 启动方式](#5-启动方式)
- [6. 验证是否正常工作](#6-验证是否正常工作)
- [7. LangChain / RAG 配置](#7-langchain--rag-配置)
- [8. 配置说明](#8-配置说明)
- [9. 常见问题](#9-常见问题)
- [10. 开发与测试](#10-开发与测试)

## 系统链路说明

如果需要从整体上理解“启动、配置、收消息、语音转文字、AI 运行时、回复发送、状态诊断、热更新”这些链路之间如何衔接，请直接查看 [SYSTEM_CHAINS.md](SYSTEM_CHAINS.md)。

这份手册继续侧重使用、配置和排障步骤；链路级节点职责、入口文件和实现方式集中维护在系统链路文档中。

## 1. 环境要求

运行前请确认：

- Windows 10 或 Windows 11
- 微信 PC `3.9.12.51`
- Python `3.9+`
- Node.js `16+`
- 微信客户端已登录

关于管理员权限（重要）：

- 默认传输后端 `wcferry` 需要通过 WCFerry 向微信进程注入。在 Windows 下必须以“管理员身份运行”启动本项目（桌面端或后端），否则会提示 “wcferry 注入需要管理员权限”。
- 建议先启动并登录微信，再启动本项目。

限制：

- 当前项目不支持微信 `4.x`
- 不支持 Linux / macOS 直接运行微信自动化
- 运行时需要保持微信客户端处于可访问状态

## 2. 安装依赖

### 2.1 克隆仓库

```bash
git clone https://github.com/byteD-x/wechat-bot.git
cd wechat-bot
```

### 2.2 安装 Python 依赖

```bash
pip install -r requirements.txt
```

这一阶段会安装：

- Quart / Hypercorn
- WCFerry 主链路依赖，以及旧版兼容依赖
- ChromaDB
- LangChain / LangGraph / LangSmith
- `watchdog`
- 测试依赖

可选依赖：

- 如需启用本地 `Cross-Encoder` 精排，额外安装 `sentence-transformers`

```bash
pip install sentence-transformers
```

说明：

- 该依赖不是默认必需项。
- 只有配置了本地模型目录时才会启用，不会自动联网下载模型。

### 2.3 安装桌面端依赖

```bash
npm install
```

这一阶段会安装 Electron 桌面端依赖。

## 3. 首次配置

推荐优先使用桌面界面配置。

### 3.1 打开桌面设置页

```bash
npm run dev
```

桌面端启动后会自动轻启动 Python Web 服务，便于直接查看状态、消息、成本和日志；机器人主循环与成长任务仍保持手动启动。

补充说明：
- 停止机器人或停止成长任务，只会停止对应业务，不会立即关闭 Python Web 服务。
- 当机器人和成长任务都停止后，后端会进入待机态；主窗口隐藏到托盘后才会开始 15 分钟自动休眠计时。
- 后端因空闲自动休眠后，重新打开主界面不会自动拉起；切换到消息、日志、成本等依赖页面，或执行显式操作时会按需恢复。

### 3.2 配置模型

在设置页里完成：

1. 选择一个模型预设
2. 填写 API Key
3. 选择模型名称
4. 点击测试连接
5. 保存配置

补充说明：

- 设置卡片右上角支持“保存本模块”，适合只修改单个主题后立即验证。
- “微信连接与传输”卡片保存后会自动重连传输层；其它卡片会在界面上标出是立即生效还是仅运行中即时生效。

### 3.3 配置文件优先级

运行时主要读取以下配置来源：

1. `data/app_config.json`

当前实现说明：

- Electron 主进程与 Python 运行时统一读取同一份 `app_config.json`，不再依赖 `backend/config.py`、`data/config_override.json`、`data/api_keys.py`、`prompt_overrides.py` 作为运行时配置源。
- 首次升级到当前版本时，应用会自动把旧链路迁移到 `app_config.json`，并在 `data/backups/legacy-config-*` 下保留一次性备份。
- 设置页通过 Electron IPC 直接读写 `app_config.json`，支持自动保存、真实落盘、文件外部改动回推，以及在机器人未启动时测试 AI 联通。
- `/api/config` 与 `/api/config/audit` 仍可用于兼容和诊断，但不再是前端设置页的主配置入口。

建议：

- 以 `data/app_config.json` 作为唯一真实配置文件
- 若需要回滚旧配置，请使用迁移生成的 `data/backups/legacy-config-*`

## 4. 启动前检查

运行环境自检：

```bash
python run.py check
```

建议至少确认：

- Python 依赖安装完成
- Node.js / Electron 依赖安装完成
- 微信版本为 `3.9.12.51`
- 配置文件可读

## 5. 启动方式

### 5.1 桌面模式

```bash
npm run dev
```

适合：

- 在 GUI 中配置参数
- 查看状态与日志
- 通过仪表盘观察健康监控和启动进度
- 启动时自动获得轻量后端服务能力，而不立即启动机器人主循环或成长任务
- 当机器人与成长任务都停止时，仪表盘会显示后端待机提示；隐藏到托盘后才会进入 15 分钟自动休眠倒计时

注意：

- 若使用默认后端 `wcferry`：请用“以管理员身份运行”打开终端再执行 `npm run dev`，并确保微信已启动且已登录。

### 5.2 无头机器人模式

```bash
python run.py start
```

适合：

- 已完成配置
- 只需要机器人主循环
- 不需要桌面控制台

注意：

- 若使用默认后端 `wcferry`：请用“以管理员身份运行”启动本项目，否则注入会失败。

### 5.3 Web API 模式

```bash
python run.py web
```

适合：

- 单独运行后端 API
- 调试接口
- 与 Electron 或外部控制端联动

注意：

- Web API 默认仅允许本机访问（`127.0.0.1/localhost`）。
- 若设置了环境变量 `WECHAT_BOT_API_TOKEN`（桌面端会自动设置），访问 `/api/*` 需要携带 `X-Api-Token` 请求头；SSE（`/api/events`）也支持 `?token=` 参数。
- `python run.py web` 若未显式设置 token，会自动生成并注入环境变量，但不会打印到控制台；如需手工调试，请在启动前自行设置 `WECHAT_BOT_API_TOKEN`（并妥善保管）。

## 6. 验证是否正常工作

建议按以下顺序验证：

1. 打开设置页，确认当前预设和 Key 已配置。
2. 访问仪表盘，确认启动状态、健康检查和系统指标正常。
3. 给允许回复的联系人发送一条简单文本。
4. 查看 `data/logs/bot.log`。
5. 检查 API `/api/status`、`/api/config`、`/api/config/audit` 和 `/api/metrics`（仅本机可访问；若设置了 `WECHAT_BOT_API_TOKEN`，需要携带 `X-Api-Token` 或 `?token=`）。

示例（PowerShell）：

```powershell
$env:WECHAT_BOT_API_TOKEN = "your_token"
python run.py web
Invoke-RestMethod -Headers @{ "X-Api-Token" = "your_token" } http://127.0.0.1:5000/api/status
```

如需快速观察运行状态，重点看：

- `/api/status.startup`
- `/api/status.diagnostics`
- `/api/status.health_checks`
- `/api/status.system_metrics`
- `/api/metrics`

如果没有回复，优先检查：

- 微信是否仍是 `3.9.12.51`
- 当前会话是否被白名单或过滤规则限制
- 如果使用“文件传输助手”做自测，确认“允许文件传输助手中的自发消息参与回复”已开启
- API Key 是否有效
- 激活预设是否可连通
- 传输后端是否已连接

## 7. LangChain / RAG 配置

### 7.1 LangChain Runtime

`agent` 分区用于控制当前主运行时。常用字段：

```python
"agent": {
    "enabled": True,
    "graph_mode": "state_graph",
    "retriever_top_k": 3,
    "retriever_score_threshold": 1.0,
    "retriever_rerank_mode": "lightweight",
    "retriever_cross_encoder_model": "",
    "retriever_cross_encoder_device": "",
    "embedding_cache_ttl_sec": 300.0,
    "background_fact_extraction_enabled": True,
    "emotion_fast_path_enabled": True,
    "llm_foreground_max_concurrency": 1,
    "background_ai_batch_time": "04:00",
    "background_ai_missed_window_policy": "wait_until_next_day",
    "background_ai_defer_mode": "defer_all",
    "langsmith_enabled": False,
    "langsmith_project": "wechat-chat",
}
```

新增的后台 AI 调度字段说明：

- `llm_foreground_max_concurrency`: 主回复共享的全局 LLM 并发上限，默认 `1`
- `background_ai_batch_time`: 后台 AI 任务统一批处理时间，默认每天 `04:00`
- `background_ai_missed_window_policy`: 错过当天批处理窗口后的策略，当前默认 `wait_until_next_day`
- `background_ai_defer_mode`: 白天后台 AI 的处理模式，当前默认 `defer_all`

当前默认行为：

- 主回复与 delayed reply 统一走前台通道，并发固定为 `1`
- 白天所有会触发 `chat/completions` 或 `embeddings` 的后台任务都会进入持久化 backlog
- backlog 会按 `chat_id + task_type` 聚合覆盖，只保留下一次重算所需的最新快照
- 后台 backlog 只在凌晨批处理窗口执行；如果程序错过当天 `04:00`，不会补跑，直接等待下一次窗口

建议：

- 初次使用保持默认。
- 主链路默认直接等待真实模型回复返回；只有将 `bot.reply_deadline_sec` 设为大于 `0` 的值时，才会启用这层预算化同步回复。
- 将 `bot.reply_deadline_sec` 设为 `0` 可关闭这层回复 deadline；关闭后主链路会直接等待真实模型返回，直到当前 provider 自己的 `timeout_sec` / `max_retries` 结束。
- 对 `Qwen` 这类远程推理模型，运行时会对过低的 `timeout_sec` 自动应用安全下限；当前默认最小值为 `15s`，避免“探测可用但正式对话总超时”。
- 当前默认模式为“对话快路径 + 后台成长增强”：同步对话只读取短期上下文和轻量画像摘要，RAG、情绪分析、事实提取、向量写回与导出语料同步都在回复后后台执行。
- 系统会为活跃联系人后台生成并渐进更新一份“联系人专属 Prompt”；没有导出聊天记录时也会基于近期对话成长，有导出聊天记录时则会额外吸收历史风格特征。
- 设置页可单独配置“联系人 Prompt 更新频率（每 N 条）”；它独立于“画像更新频率”，用于控制联系人专属 Prompt 的自动增量更新节奏。
- 性能调优时优先调整 `retriever_top_k`、阈值、精排模式和缓存 TTL；这些参数现在主要影响后台增强链而不是首条回复。
- 若日志中出现 `compat_fallback=openai_chat_completions`，表示底层 provider 实际返回了结果，但 LangChain 兼容层给出了异常空内容；系统已自动回退到原生 OpenAI-compatible `/chat/completions` 结果。
- 开启 LangSmith 前先确认你接受外部 tracing。

### 7.2 运行期向量记忆

相关开关位于 `bot`：

```python
"rag_enabled": True
```

作用：

- 将当前聊天沉淀为向量记忆，供后续成长能力持续积累
- 默认不再参与本轮同步回复上下文拼装

### 7.3 运行期精排与本地 Cross-Encoder

运行期 RAG 现在有两层精排能力：

- `lightweight`: 默认模式，基于向量距离和关键词重合做轻量重排
- `auto`: 如果检测到本地 `Cross-Encoder` 模型且依赖可用，则启用精排；否则自动回退轻量重排
- `cross_encoder`: 优先尝试本地 `Cross-Encoder`，若初始化失败仍回退轻量重排

推荐配置示例：

```python
"agent": {
    "retriever_rerank_mode": "auto",
    "retriever_cross_encoder_model": "models/bge-reranker-base",
    "retriever_cross_encoder_device": "cpu",
}
```

注意：

- `retriever_cross_encoder_model` 必须是本地目录
- 项目不会自动联网下载模型
- `/api/status` 中的 `retriever_stats.rerank_backend` 可用于确认当前实际启用的是 `cross_encoder` 还是 `lightweight`

### 7.4 导出语料 RAG

相关字段：

```python
"export_rag_enabled": True,
"export_rag_dir": "data/chat_exports/聊天记录",
"export_rag_top_k": 3,
"export_rag_max_chunks_per_chat": 500,
```

作用：

- 从导出的真实聊天中召回你过去的表达风格
- 更偏“风格模仿”，不是事实数据库
- 默认作为后台成长能力运行，不阻塞当前对话回复

使用方式：

1. 导出聊天记录
2. 放到 `data/chat_exports/聊天记录/...`
3. 启动机器人或等待自动增量导入

相关命令：

```bash
python -m tools.chat_exporter.cli
python -m tools.prompt_gen.generator
```

## 8. 配置说明

### 8.1 `api`

负责模型与提供方：

- `base_url`
- `api_key`
- `model`
- `embedding_model`
- `active_preset`
- `presets`
- `timeout_sec`
- `max_retries`

### 8.2 `bot`

负责机器人行为：

- 回复格式
- 轮询与并发
- 记忆与上下文
- 群聊规则
- 控制命令
- 情绪识别
- RAG 开关
- 传输后端
- 配置热重载

与本轮更新相关的字段：

- `config_reload_mode`: `auto` / `polling` / `watchdog`
- `config_reload_debounce_ms`: 文件事件防抖窗口
- `required_wechat_version`: 官方支持版本基线，当前应保持为 `3.9.12.51`
- `vector_memory_enabled`: 向量记忆 / RAG 总开关，关闭后不会写入或检索向量记忆
- `vector_memory_embedding_model`: 给向量记忆单独指定 embedding 模型，优先级高于预设和全局配置

说明：
- `wcferry` 是当前默认且唯一官方支持的传输后端。
- 当前需要将 `wcferry` 与微信 `3.9.12.51` 版本配套使用，否则传输层兼容性无法保证。

### 8.3 `agent`

负责 LangChain/LangGraph 运行时：

- 主链路开关
- Retriever 参数
- RAG 精排模式
- Embedding 缓存
- 后台事实提取
- LangSmith tracing

与精排相关的字段：

- `retriever_rerank_mode`
- `retriever_cross_encoder_model`
- `retriever_cross_encoder_device`

### 8.4 `logging`

负责日志：

- 日志级别
- 日志文件
- 轮转大小与数量
- 是否记录消息正文

### 8.5 运行状态与指标

当前可直接观察的接口：

- `/api/status`: 结构化运行状态
- `/api/metrics`: Prometheus 风格指标
- `/api/contact_profile`: 返回当前联系人的画像摘要、专属 Prompt 和成长元数据
- `/api/contact_prompt`: 保存人工编辑后的联系人专属 Prompt

`/api/status` 重点字段：

- `startup`
- `diagnostics`
- `health_checks`
- `system_metrics`
- `config_reload`
- `growth_mode`
- `growth_tasks_pending`
- `last_growth_error`
- `foreground_active`
- `foreground_waiters`
- `background_active`
- `background_backlog_count`
- `background_backlog_by_task`
- `next_background_batch_at`
- `last_background_batch`

消息页里的“消息详情”面板现在会展示当前联系人的画像摘要和专属 Prompt，并允许直接编辑；人工编辑后的版本会继续作为后台渐进式更新的基础。
设置页支持“保存本模块”；日志页默认启用自动换行，并会把成长任务、发送链和 API 请求整理成更容易扫描的摘要行；侧边栏底部新增“关于”页面入口，可直接查看作者主页、开源仓库、Issue 反馈入口与赞助说明文档。

### 8.6 运行时文件位置

为避免根目录持续堆积运行产物，当前目录约定如下：

- 应用日志：`data/logs/`
- 第三方运行时产物：`data/runtime/`
- 测试缓存：`data/runtime/test/pytest_cache/`
- 覆盖率文件：`data/runtime/test/coverage/.coverage`

## 9. 常见问题

### 9.1 `pip` 或 `python` 不存在

处理：

1. 重新安装 Python
2. 勾选 `Add Python to PATH`
3. 重开终端

### 9.2 `npm install` 失败

处理：

1. 检查 Node.js 版本
2. 清理 `node_modules`
3. 重新执行 `npm install`

### 9.3 机器人不回复

优先排查：

- 微信是否是 `3.9.12.51`
- 微信是否保持登录
- 当前会话是否被过滤
- 是否开启白名单且遗漏会话
- 模型连接是否成功
- 传输后端是否已连接
- 日志中是否有请求错误

### 9.4 模型能连通但 RAG 没效果

优先排查：

- `vector_memory_enabled` 是否被关闭
- `rag_enabled` 或 `export_rag_enabled` 是否开启
- embedding 模型是否可用
- 导出目录是否存在有效语料
- `retriever_top_k` 是否过低
- `retriever_score_threshold` 是否过严
- 当前 `retriever_stats.rerank_backend` 是否符合预期

补充说明：

- embedding 解析优先级为 `bot.vector_memory_embedding_model` > 当前预设的 `embedding_model` > `api.embedding_model`
- 使用 `Ollama` 时可以在预设或“向量记忆 embedding 模型”里填写本地 embedding 模型，例如 `nomic-embed-text`
- 首次打开向量记忆总开关时，桌面端会提示本地索引存储、CPU/内存占用以及潜在云端调用成本

### 9.5 已配置 Cross-Encoder 但没有启用

优先排查：

- 是否额外安装了 `sentence-transformers`
- `retriever_cross_encoder_model` 是否指向本地存在的目录
- `retriever_rerank_mode` 是否为 `auto` 或 `cross_encoder`
- `/api/status.retriever_stats.rerank_backend` 是否仍显示 `lightweight`
- 日志中是否有 “Cross-Encoder 精排初始化失败” 或 “本地模型路径不存在”

### 9.6 LangSmith 不生效

优先排查：

- `agent.langsmith_enabled` 是否开启
- LangSmith API Key 是否已配置
- 网络是否允许访问 LangSmith 服务

### 9.7 `/api/metrics` 无法访问

优先排查：

- 是否以 `python run.py web` 或桌面端启动了后端
- 访问的端口是否正确
- 代理或网关是否拦截了纯文本响应
- `/api/status` 是否已经可访问

### 9.8 提示 “wcferry 注入需要管理员权限”

现象：

- 启动后端时提示 `wcferry 注入需要管理员权限`，或传输后端一直无法连接。

处理：

1. 先启动并登录微信 PC（`3.9.12.51`）。
2. 用“以管理员身份运行”启动本项目（桌面端或 `python run.py start/web`）。
3. 确认 `wcferry`、管理员权限和微信版本三者同时满足，再继续排查其余环境问题。

## 10. 开发与测试

### 10.1 常用命令

```bash
# 安装依赖
pip install -r requirements.txt
npm install

# 桌面开发模式
npm run dev

# 启动机器人
python run.py start

# 启动 Web API
python run.py web

# 环境检查
python run.py check
```

### 10.2 测试

```bash
# 前端 / Electron 侧测试
npm test
npm run test:renderer

# Python 回归
python -m pytest tests\test_runtime_observability.py -q
python -m pytest tests\test_smoke.py tests\test_api.py tests\test_runtime_observability.py -q

# 语法检查
python -m py_compile backend\core\agent_runtime.py backend\bot.py backend\bot_manager.py backend\api.py
```

说明：

- `npm test` 会顺序执行 `update-manager`、`backend-idle-controller` 和 renderer helper 测试。
- `npm run test:renderer` 适合只验证 `src/renderer/js/pages/settings/` 与 `src/renderer/js/pages/dashboard/` 拆分后的辅助模块。

### 10.3 Windows 发布说明

当前 Windows 发布策略已经调整为：

- 日常发布默认只生成 `setup.exe` 和 `portable.exe`
- `MSI` 仅保留为按需构建产物，可通过 `npm run build:msi` 单独生成
- `setup.exe` 安装版支持应用内自动更新：应用启动后会自动检查 GitHub 最新 Release
- 检查到新版本时会弹窗显示最新版本号、发布日期和更新说明，并提供“跳过此版本”和“下载更新”两个操作
- 选择“跳过此版本”后，该版本只会在当前机器上被忽略；当后续发布更高版本时会重新提示
- 下载完成后可直接执行“立即安装并重启”，应用会退出并启动最新 `setup.exe` 完成覆盖升级
- `portable.exe` 仍为手动更新模式，桌面端会保留打开 GitHub Releases 的入口
- 正式 Release 通过 GitHub Actions 构建并上传，不再依赖本地手工上传大文件

Release Notes 规则：

- 每次正式发版都会自动对比“上一个正式 tag 到当前 tag”的提交范围
- 发布说明会自动包含 compare 区间、Compare 链接、按 Conventional Commits 分组的摘要，以及原始提交列表
- 如果当前是首个正式版本，则会回退为“从仓库起点到当前 tag”的首版说明

## 11. 成本管理

桌面端新增了“成本管理”页面，用于查看 AI 回复的 token 与金额消耗。

页面能力：

- 顶部总览卡展示总金额、总 Token、已定价回复数、未定价回复数、最高消耗模型
- 支持按 `today / 7d / 30d / all` 切换时间范围
- 支持按 `Provider`、`模型`、`仅看已定价`、`包含估算数据` 筛选
- 会话列表按 `chat_id` 分组，展开后可查看每条 AI 回复的模型、输入 Token、输出 Token、总 Token、金额、时间和回复摘要

定价与估算规则：

- 优先读取 assistant 消息 `metadata` 中已经落库的 `pricing` 与 `cost`
- 若旧消息缺少 token，会按文本长度估算 token
- 若能估 token 但无法可靠解析 provider 或价格，则只展示 token，不显示金额，并标记为“待定价”
- 金额按官方“每 1M tokens 单价”换算，不做汇率折算；多币种会拆分展示
- `Ollama` 本地模型默认按 `0` 成本处理

### 11.1 成本相关 API

新增接口：

- `GET /api/pricing`
- `POST /api/pricing/refresh`
- `GET /api/costs/summary`
- `GET /api/costs/sessions`
- `GET /api/costs/session_details`

说明：

- `/api/pricing` 返回当前价格目录、来源链接、最近校验时间和是否支持刷新
- `/api/pricing/refresh` 用于手动刷新可自动抓取的价格来源
- `/api/costs/summary` 返回总览和模型聚合
- `/api/costs/sessions` 返回会话级摘要
- `/api/costs/session_details` 返回单个会话的 AI 回复成本明细，需要传 `chat_id`

当前测试覆盖重点包括：

- API 路由
- Bot 生命周期
- Export RAG
- Agent Runtime
- 运行状态、健康检查与指标导出

### 10.3 敏感数据注意事项

不要提交以下内容：

- 真实 API Key
- `data/chat_exports/`
- `data/`
- `data/logs/`
- 解密后的微信数据库
## 附录：成长任务管理与发布权限

- 仪表盘中的“成长任务”面板现在支持按任务类型查看排队数量，并可执行“立即执行 / 暂停或恢复 / 清空队列”。
- 仪表盘会额外显示后端待机/休眠状态：窗口可见时只提示待机，隐藏到托盘后才开始倒计时；已休眠时可在页面中按需唤醒。
- 任务级 API：
  - `GET /api/growth/tasks`
  - `POST /api/growth/tasks/<task_type>/run`
  - `POST /api/growth/tasks/<task_type>/pause`
  - `POST /api/growth/tasks/<task_type>/resume`
  - `POST /api/growth/tasks/<task_type>/clear`
- Windows Release 产物现在默认嵌入管理员权限清单，启动 `setup.exe` 或 `portable.exe` 时会请求 UAC 提权。
