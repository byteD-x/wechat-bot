# 系统链路说明

本文档用于集中说明当前系统中的主要链路、每条链路的节点职责，以及这些节点在代码中是如何实现的。

适用范围：

- Electron 桌面端
- Quart Web API
- WeChatBot 主运行时
- WCFerry 传输层
- LangChain / LangGraph 运行时
- 记忆、RAG、观测与配置热更新

## 1. 分层总览

系统可以分成 6 层：

1. 界面层
   - Electron 主进程
   - Electron 渲染层
   - Web API 客户端服务
2. 接口层
   - Quart API
   - SSE 状态/事件流
3. 生命周期层
   - `BotManager`
   - `WeChatBot`
4. 传输层
   - `BaseTransport`
   - `WcferryTransport`
5. AI 运行时层
   - `AIClient`
   - `AgentRuntime`
6. 数据与能力层
   - SQLite 记忆
   - 向量记忆
   - 导出语料 RAG
   - 情绪分析
   - 配置快照与审计

## 2. 桌面启动链路

链路目标：启动 Electron，加载 preload，渲染控制台页面，并接入本地 API。

### 节点

1. `dev.bat` / `npm run dev`
   - 功能：启动 Electron 开发模式。
   - 实现：调用 `electron . --dev`，由主进程负责决定是否启动后端。

2. `src/main/index.js`
   - 功能：创建主窗口、启动 splash、注册 IPC、按需启动后端。
   - 实现：
     - 创建 BrowserWindow。
     - 注册 `dom-ready`、`did-finish-load`、`did-fail-load` 等事件。
     - 管理 splash 的显示、关闭和鼠标事件穿透。

3. `src/preload/index.js`
   - 功能：把受控的 Electron API 暴露给渲染层。
   - 实现：通过 `contextBridge` 将窗口控制、日志、配置、更新检查等接口暴露到 `window.electronAPI`。

4. `src/renderer/js/app.module.js`
   - 功能：初始化前端应用、页面控制器、轮询与事件绑定。
   - 实现：
     - 创建页面控制器。
     - 初始化服务层。
     - 绑定导航、状态更新、更新下载、SSE 等行为。

5. `src/renderer/js/services/ApiService.js`
   - 功能：统一访问本地 Quart API。
   - 实现：
     - 维护 API base URL 和 token。
     - 封装 `status/config/start/stop/send/preview_prompt/check-update`、模型中心、微信导出、成本、日志等请求。

## 3. Web API 链路

链路目标：为桌面端和调试工具提供统一接口。

### 节点

1. `backend/api.py`
   - 功能：定义全部 `/api/*` 接口。
   - 实现：
     - `before_request` 中限制仅本机访问。
     - 当 `WECHAT_BOT_API_TOKEN` 存在时，普通 API 校验 `X-Api-Token`/`Authorization`；SSE 校验 `ticket`.
     - 输出 JSON 或 SSE。
   - 部署边界：
     - `python run.py web --host 0.0.0.0` 这类非回环绑定必须显式设置 `WECHAT_BOT_API_TOKEN`，否则启动会被拒绝。
     - `Dockerfile` 默认只启动 Web API，并设置 `WECHAT_BOT_DEPLOYMENT_TARGET=web-api`；该目标只覆盖 Web API、readiness 和离线 eval，不覆盖桌面启动链、WCFerry 注入链或微信消息收发链。

2. `/api/status`
   - 功能：返回结构化运行状态。
   - 实现：委托 `BotManager.get_status()` 组装启动状态、健康检查、诊断、系统指标、`response_cache_stats`、`safety_stats`、`model_route_stats`、`model_tool_call_stats`、`governance_metrics` 和 `trace_logger`。
   - 约束：`response_cache_stats` 只暴露默认关闭的响应缓存统计；语义缓存 `semantic_enabled` 默认关闭，开启后也只在同一 provider、model、chat、system prompt、非当前用户 prompt context、RAG citation ids 与安全策略边界内相似命中，不跨会话、模型、引用策略或安全策略复用；缓存不包含原始 prompt、聊天正文、真实联系人标识或 token；`safety_stats` 只记录安全护栏 action/reason 聚合与最近一次脱敏结果，不记录原始请求或回复；`model_route_stats` 只记录当前请求的可解释模型路由决策，不自动切换用户选择的 provider、model 或认证方式；`model_tool_call_stats` 只记录模型侧工具调用开关、请求、成功、失败和阻断计数；`governance_metrics` 只记录 Prompt 回滚与 Tool Workflow 的聚合次数、成功率、失败原因短枚举和耗时；`trace_logger` 只保留进程内最近 trace 摘要，通过 hash 引用和聚合字段描述 cache、模型路由、安全护栏、模型工具调用与错误类型，不记录原始 Prompt、聊天正文、token、工具原始输出或完整本机路径。

3. `/api/config`
   - 功能：读取/保存有效配置。
   - 实现：
     - `GET` 读取配置快照并脱敏输出。
     - `POST` 更新 override，返回 `changed_paths` 和 `reload_plan`，必要时触发运行时热应用。

4. `/api/events`
   - 功能：提供 SSE 事件流。
   - 实现：委托 `BotManager.event_generator()` 输出状态变化和消息事件。

5. `/api/start` `/api/stop` `/api/pause` `/api/resume` `/api/restart`
   - 功能：控制机器人生命周期。
   - 实现：委托 `BotManager` 对 `WeChatBot` 进行启动、停止、暂停和恢复。

6. `/api/messages` `/api/send`
   - 功能：读取历史消息和主动发送消息。
   - 实现：
     - 历史消息走共享 `MemoryManager`。
     - 主动发送走 `BotManager.send_message()`，最终调用 `WeChatBot.send_text_message()`。

7. `/api/contact_profile` `/api/contact_prompt`
   - 功能：读取联系人画像与专属 Prompt，并支持人工保存修订版本。
   - 实现：
     - 画像读取走 `MemoryManager.get_contact_profile()`。
     - 手工编辑走 `MemoryManager.save_contact_prompt()`，保存后继续作为后台成长链的增量基础。

8. `/api/preview_prompt`
   - 功能：预览系统提示词。
   - 实现：构造一个示例事件对象，调用 `resolve_system_prompt()` 生成预览。

9. Prompt governance routes
   - 功能：查看系统 Prompt revision 元数据、预览 active 到目标 revision 的差异，并把系统 Prompt 回滚到指定历史 revision。
   - 实现：
     - `backend/api.py::list_prompt_revisions` 调用 `PromptGovernanceService.list_revisions()`，返回 revision/status/source/created_at/rollback_from/reason 等元数据，不返回完整 `prompt` 或 `editable_prompt`。
     - `backend/api.py::diff_prompt_revision` 调用 `PromptGovernanceService.diff_revision()`，返回 active revision 到目标 revision 的 unified diff，供回滚确认前预览。
     - `backend/api.py::rollback_prompt_revision` 调用 `PromptGovernanceService.rollback()`。
     - 回滚会复制目标 Prompt 并追加新的 active revision，默认写入 `data/prompt_revisions.json` 审计账本。
     - 设置页系统提示区的“Prompt 版本治理”折叠面板通过 `SettingsPage`、`prompt-governance.js` 和 `ApiService` 调用这些接口；回滚按钮必须在当前 revision 生成 fresh diff 后才会启用，成功后刷新设置快照和版本历史。
     - Electron 主进程只允许转发固定列表路径 `/api/v1/admin/prompts/revisions`，以及匹配 `^/api/v1/admin/prompts/\d+/(diff|rollback)$` 的数字 revision 路径，避免任意管理路径穿透。

10. `/api/v1/agents/tool-workflow`
    - 功能：按顺序执行受控本机工具，并返回每一步 trace。
    - 实现：
      - `backend/api.py::run_agent_tool_workflow` 调用 `ControlledToolWorkflowService`。
      - 当前最多 `8` 步，单步 payload 字符串化后最多 `12000` 字符。
      - 当前注册工具只包含 `config_audit`、`readiness_check`、`prompt_preview`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run`、`data_controls_dry_run`。
      - 每个注册工具声明 payload schema、permission 和 timeout，执行前完成输入校验与权限检查。
      - 请求体 `workflow_mode` 默认 `direct`；可选 `plan_reflect_repair` 会返回 `planning / reflection / repair` 摘要，`max_repair_attempts=1`，`repair_policy=schema_safe_defaults_only`。
      - 未知工具、schema 不通过、权限不匹配或超时都会返回 `bad_workflow` 和失败 trace；即使启用 `plan_reflect_repair`，未知工具、权限失败、危险 payload、非白名单路径也只会 blocked，不会被 repair 成可执行动作。
      - 工具流不会执行任意 shell、任意文件写入、任意网络请求或动态插件，也不进入微信消息快回复主链路。
      - 仪表盘“风险与恢复 / 受控工具流”通过 `src/renderer/js/pages/dashboard/tool-workflow.js` 构造白名单步骤、dry-run 和 `continue_on_error`，再由 `ApiService.runToolWorkflow()` 调用该接口。
      - 前端 trace 只展示工具名、状态、耗时、失败原因和结果摘要；`prompt_preview` 不在界面 trace 中展示完整 Prompt，`eval_latest` 不展示完整 `cases`，`cost_summary` 不展示完整 `review_queue`，维护 dry-run 工具不展示备份候选列表、清理 targets 或完整本机路径。

11. `/api/v1/mcp`
    - 功能：提供本机只读 MCP JSON-RPC adapter，让外部 MCP host 只能发现和调用安全摘要工具。
    - 实现：
      - `backend/api.py::run_readonly_mcp_adapter` 创建 `ReadOnlyMCPAdapter`，复用 `ControlledToolWorkflowService` 的工具注册、schema、permission、timeout 和 trace。
      - 当前只支持 `initialize`、`tools/list`、`tools/call`，不实现 resources、prompts、shell、文件写入、任意 HTTP 或动态插件。
      - `tools/list` 只返回模型侧安全工具 `readiness_check`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run`、`data_controls_dry_run`；`prompt_preview` 和 `config_audit` 不会出现在 MCP 工具列表中。
      - `tools/call` 每次只调用一个安全工具，响应包含 MCP `content` 与 `structuredContent`，其中 output 继续沿用既有脱敏摘要，不返回完整 Prompt、评测用例、review_queue、targets 或完整本机路径。
      - MCP adapter 是治理入口，不进入微信消息快回复主链路。

12. `/api/knowledge_base/*`
    - 功能：提供本机知识库治理闭环，支持查看状态、单文档/多文档预览分块、单文档/多文档写入、单文档/多文档重建和按 `doc_id` 删除。
    - 实现：
      - `backend/api.py::preview_knowledge_base_document` 和 `KnowledgeBaseService.build_chunks()` 复用同一套分块逻辑；`dry-run` 只返回 chunk id、字符数和脱敏来源摘要，不返回正文、chunk text 或 embedding。
      - `backend/api.py::preview_knowledge_base_documents` 复用单文档 payload 解析和 dry-run 构造，`batch-dry-run` 只聚合请求体中的多份文档预览结果，不写入向量库、不触发 embedding、不读取本机路径。
      - `backend/api.py::ingest_knowledge_base_document`、`ingest_knowledge_base_documents`、`rebuild_knowledge_base_document` 与 `rebuild_knowledge_base_documents` 复用运行中 bot 的 `vector_memory` 和 `ai_client.get_embedding`；`batch-ingest` 只顺序写入请求体文档，不读取本机路径、不删除旧 chunk；`batch-rebuild` 只顺序重建请求体文档，重复 `doc_id` 会在删除前被拒绝，单文档 embedding 准备失败时保留该文档旧 chunk。
      - 设置页“数据与恢复 / 知识库治理”通过 `SettingsPage`、`backup-panel.js`、`page-shell.js` 和 `ApiService` 只调用固定的 `status / dry-run / ingest / rebuild` 端点；写入或重建都必须先对当前粘贴内容完成 dry-run，内容或元数据变化后会清空签名。
      - 当前设置页不开放 `batch-dry-run`、`batch-ingest`、`batch-rebuild`、`delete`、文件上传、目录扫描或任意本机路径读取；Web API 也只接收请求体中的纯文本或 Markdown。

### 当前接口分组

`backend/api.py` 当前按职责提供这些主要接口：

- 基础状态与事件：`/api/status`、`/api/ping`、`/api/readiness`、`/api/metrics`、`/api/events`、`/api/events_ticket`
- 生命周期：`/api/start`、`/api/stop`、`/api/pause`、`/api/resume`、`/api/restart`、`/api/recover`
- 成长任务：`/api/growth/start`、`/api/growth/stop`、`/api/growth/tasks`、`/api/growth/tasks/<task_type>/clear|run|pause|resume`
- 微信导出：`/api/wechat_export/probe`、`/api/wechat_export/decrypt/start`、`/api/wechat_export/decrypt/jobs/<job_id>`、`/api/wechat_export/contacts`、`/api/wechat_export/export`、`/api/wechat_export/apply/preview`、`/api/wechat_export/apply`
- 消息与画像：`/api/messages`、`/api/send`、`/api/contact_profile`、`/api/contact_prompt`、`/api/message_feedback`
- 回复策略与审批：`/api/reply_policies`、`/api/pending_replies`、`/api/pending_replies/<id>/approve|reject`
- 备份与数据治理：`/api/backups`、`/api/backups/cleanup`、`/api/backups/restore`、`/api/data_controls`、`/api/data_controls/clear`、`/api/evals/latest`
- 成本：`/api/usage`、`/api/pricing`、`/api/pricing/refresh`、`/api/costs/summary`、`/api/costs/sessions`、`/api/costs/session_details`、`/api/costs/review_queue_export`
- 模型与认证：`/api/model_catalog`、`/api/model_auth/overview`、`/api/model_auth/action`、兼容壳层 `/api/auth/providers*`、本地模型探测 `/api/ollama/models`
- 配置与诊断：`/api/config`、`/api/config/audit`、`/api/test_connection`、`/api/preview_prompt`、`/api/logs`、`/api/logs/clear`
- 知识库治理：`/api/knowledge_base/status`、`/api/knowledge_base/dry-run`、`/api/knowledge_base/batch-dry-run`、`/api/knowledge_base/ingest`、`/api/knowledge_base/batch-ingest`、`/api/knowledge_base/rebuild`、`/api/knowledge_base/batch-rebuild`、`/api/knowledge_base/delete`
- Prompt 与工具治理：`/api/v1/admin/prompts/revisions`、`/api/v1/admin/prompts/<revision>/diff`、`/api/v1/admin/prompts/<revision>/rollback`、`/api/v1/agents/tool-workflow`

## 4. 启动与生命周期链路

链路目标：从“用户点击启动”到“机器人进入收发循环”。

### 节点

1. `backend/bot_manager.py::start`
   - 功能：启动生命周期入口。
   - 实现：
     - 创建 `WeChatBot`。
     - 注入共享 `MemoryManager`。
     - 创建异步任务执行 `_run_bot()`。
     - 更新 startup 状态并广播。

2. `backend/bot.py::initialize`
   - 功能：完成运行前准备。
   - 实现：
     - 加载有效配置快照。
     - 初始化记忆与向量记忆。
     - 选择并探测 AI 客户端。
     - 连接微信传输层。
     - 写入 startup 状态：`loading_config -> init_memory -> init_ai -> connect_wechat -> ready`。

3. `backend/core/factory.py::select_ai_client`
   - 功能：选择可用 AI 预设。
   - 实现：
     - 枚举候选预设。
     - 构造 `AIClient` 或 `AgentRuntime`。
     - 逐个 `probe()`，选中首个可用预设。

4. `backend/core/factory.py::reconnect_wechat`
   - 功能：连接或重连微信传输层。
   - 实现：
     - 仅支持 `wcferry`。
     - 按重试策略构造 `WcferryTransport`。
     - 记录最近一次传输层错误，供状态接口和诊断面板使用。

5. `backend/bot_manager.py::_run_bot`
   - 功能：托管主循环任务。
   - 实现：
     - 调用 `bot.run()`。
     - 捕获运行时异常并写入结构化 issue。
     - 在退出时清理状态并广播。

## 5. 传输层链路

链路目标：把微信收发能力适配成机器人可消费的统一接口。

### 节点

1. `backend/transports/base.py::BaseTransport`
   - 功能：定义统一传输接口。
   - 实现：约束 `close/get_transport_status/poll_new_messages/send_text/send_files`。

2. `backend/transports/wcferry_adapter.py::WcferryTransport.__init__`
   - 功能：初始化 WCFerry 传输层。
   - 实现：
     - 检测管理员权限、微信路径和版本。
     - 加载 `wcferry.Wcf`。
     - 等待登录。
     - 读取联系人。
     - 启用消息接收通道。

3. `_enable_receiving_msg_robust`
   - 功能：可靠建立消息通道。
   - 实现：
     - 显式调用 `FUNC_ENABLE_RECV_TXT`。
     - 自己维护消息 socket 连接与重连。
     - 等待消息通道 ready，再宣布 transport connected。

4. `poll_new_messages`
   - 功能：拉取消息并适配为兼容结构。
   - 实现：
     - 从 WCFerry 消息队列取消息。
     - 按会话分组。
     - 包装成 `{"chat_name","chat_type","msg":[...]}`。

5. `send_text`
   - 功能：发送文本消息。
   - 实现：
     - 解析目标联系人或群聊。
     - 调用 `send_text`。
     - 返回统一结果字典：`success/code/message/receiver`。

6. `close`
   - 功能：关闭传输层。
   - 实现：
     - 先关闭接收标志。
     - 对 `disable_recv_msg` 和 `cleanup` 采用限时 best-effort 清理。
     - 回收运行时产物。

## 6. 消息接收主链

链路目标：从微信新消息到标准化事件。

### 节点

1. `WeChatBot.run`
   - 功能：主轮询循环。
   - 实现：
     - 按轮询间隔拉取微信新消息。
     - 调用 `normalize_new_messages()` 标准化。
     - 为每条消息创建处理任务，受并发信号量控制。

2. `backend/handlers/converters.py::normalize_new_messages`
   - 功能：标准化多种消息结构。
   - 实现：
     - 兼容 dict、list、bundle 三种输入形式。
     - 调用 `normalize_message_item()` 统一输出 `MessageEvent`。

3. `normalize_message_item`
   - 功能：解析单条消息。
   - 实现：
     - 识别文本、图片、语音。
     - 解析群聊发送者。
     - 识别 `@`。
     - 记录 `chat_name/sender/content/msg_type/is_group/is_self/raw_item`。

## 7. 文本消息处理链

链路目标：收到文本后完成过滤、AI 调用与回复发送。

### 节点

1. `backend/bot.py::handle_event`
   - 功能：单条消息处理入口。
   - 实现：
     - 广播 incoming 事件。
     - 检查控制命令。
     - 检查静默/暂停。
     - 调用 `should_reply()` 判断是否应答。

2. `backend/handlers/filter.py::should_reply`
   - 功能：决定是否回复。
   - 实现：
     - 结合白名单、忽略名单、群聊是否必须 `@`、静默规则等配置进行判断。

3. `backend/bot.py::_process_and_reply`
   - 功能：进入 AI 主处理流。
   - 实现：
     - 生成 `chat_id`。
     - 调用 AI 运行时准备上下文。
     - 根据 `reply_deadline_sec` 和 provider 超时预算组织同步真实回复。
     - 在发送成功后写入日志、广播 outgoing、记录 token 统计。

## 8. 语音消息处理链

链路目标：收到语音后下载音频、转写成文本，再进入正常回复链。

### 节点

1. `backend/utils/tools.py::transcribe_voice_message`
   - 功能：抽象语音转文字入口。
   - 实现：
     - 只对 voice/audio 类型生效。
     - 校验 `voice_to_text` 开关。
     - 调用 `raw_item.to_text()`，再统一解析结果。

2. `backend/transports/wcferry_adapter.py::transcribe_voice`
   - 功能：WCFerry 侧的语音转写实现。
   - 实现：
     - 调用 `get_audio_msg` 下载音频。
     - 读取当前激活 AI 预设的 `base_url/api_key`。
     - 调用 `transcribe_audio_file()` 请求 `/audio/transcriptions`。

3. `backend/transports/audio_transcription.py::transcribe_audio_file`
   - 功能：调用 OpenAI-compatible 转写接口。
   - 实现：
     - 构造 multipart/form-data 请求。
     - 兼容 `text` 成功返回。
     - 兼容 HTTP 错误和嵌套错误体。

4. `backend/utils/message.py::parse_voice_to_text_result`
   - 功能：统一解析转写结果。
   - 实现：
     - 支持字符串成功返回。
     - 支持 `{"text": ...}` 和 `{"data":{"text": ...}}` 成功结构。
     - 支持 `error/message` 错误结构。

5. `backend/bot.py::handle_event`
   - 功能：把转写文本灌回主链。
   - 实现：
     - 成功时把 `event.content` 替换为转写结果。
     - 失败时按 `voice_to_text_fail_reply` 可选回复失败提示。

## 9. 图片消息链

链路目标：把图片消息包装为可被 AI 模型识别的多模态输入。

### 节点

1. `backend/transports/wcferry_adapter.py::save_media`
   - 功能：下载图片到目标路径。
   - 实现：调用 `download_image` 并移动到目标文件。

2. `backend/utils/image_processing.py::process_image_for_api`
   - 功能：把图片转为 base64 数据 URL 所需内容。
   - 实现：读取图片并生成适合模型接口的编码。

3. `backend/core/agent_runtime.py::_build_prompt_messages`
   - 功能：构造多模态 message。
   - 实现：
     - 文本部分放在 `type=text`。
     - 图片部分放在 `type=image_url`。

## 10. AI 运行时链

链路目标：统一完成上下文准备、RAG、情绪分析、提示词构建和回复生成。

### 节点

1. `backend/core/agent_runtime.py::prepare_request`
   - 功能：准备本轮请求。
   - 实现：
     - 运行 `load_context -> build_prompt` 图。
     - 返回 `AgentPreparedRequest`。

2. `_load_context_node`
   - 功能：并发加载上下文依赖。
   - 实现：
     - 读取最近对话。
     - 读取用户画像。
     - 读取导出语料 RAG。
     - 读取运行期向量记忆。
     - 执行情绪分析。

3. `_build_prompt_node`
   - 功能：构建 prompt messages。
   - 实现：
     - 调用 `resolve_system_prompt()`。
     - 按消息角色构建 `SystemMessage/HumanMessage/AIMessage`。
     - 群聊可按 `group_include_sender` 注入 `[sender]` 前缀。

4. `invoke`
    - 功能：非流式模型调用。
    - 实现：
      - 调用 `ChatOpenAI.ainvoke()`。
      - 响应统一经过兼容层标准化，收敛正文、推理、工具调用与 finish reason。
      - `response_cache` 先查精确 key；若 `semantic_enabled=true` 且精确未命中，才对当前用户文本生成 embedding，并在同上下文边界内计算语义相似命中；命中后仍重新执行安全护栏。
      - `agent.model_tool_calls_enabled` 默认关闭；开启后仅在 OpenAI-compatible 对话接口中向模型暴露 `readiness_check`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run`、`data_controls_dry_run` 五个安全工具。
      - 模型侧工具调用复用 `ControlledToolWorkflowService` 的注册工具、payload schema、permission、timeout 和 trace，不新增执行器，也不向模型暴露 `prompt_preview` 或 `config_audit`。
      - 运行时最多执行一轮模型工具调用，再请求一轮 final 回复；如果 final 继续返回 `tool_calls`，只记录 `model_tool_call_loop_blocked`，不会进入循环。
      - 调用完成后写入 `TraceLoggerLite` 的内存级脱敏摘要，覆盖 cache hit、成功、fallback 空响应和异常路径；摘要只进入 `/api/status.trace_logger`，不持久化。
      - 当正文为空时，仅内部任务可回退到推理文本；普通聊天不再发送兜底文案。

5. `finalize_request`
   - 功能：请求收尾。
   - 实现：
      - 写回 SQLite 记忆。
      - 更新情绪。
      - 异步写入向量记忆。
     - 异步做事实提取和画像演化。

## 11. 记忆与 RAG 链

链路目标：让回复具备短期上下文、运行期语义记忆和历史风格召回。

### 节点

1. `backend/core/memory.py::MemoryManager`
   - 功能：SQLite 持久化记忆。
   - 实现：
     - 维护消息历史。
     - 维护画像、事实、情绪。
     - 提供最近上下文和消息检索。

2. `backend/core/vector_memory.py`
   - 功能：运行期向量记忆。
   - 实现：
     - 为聊天内容写入 embedding。
     - 检索当前会话相关语义片段。

3. `backend/core/export_rag.py`
   - 功能：导出聊天记录风格召回。
   - 实现：
     - 从导出语料构建片段。
     - 为 prompt 提供真实风格参考。

4. `AgentRuntime._search_runtime_memory`
   - 功能：运行期 RAG 检索。
   - 实现：
     - 生成 embedding。
     - 查询向量库。
     - 走轻量重排或可选 Cross-Encoder 重排。

## 12. 回复格式链

链路目标：把 AI 输出转换为适合微信发送的文本。

### 节点

1. `backend/utils/message.py::refine_reply_text`
   - 功能：去掉明显的 AI 腔和冗余套话。
   - 实现：通过若干正则裁掉“作为 AI”之类前缀。

2. `sanitize_reply_text`
   - 功能：按策略处理 emoji。
   - 实现：
     - `keep`：保留原始 emoji
     - `strip`：移除 emoji
     - `mixed`：可映射的转微信文案，其余保留
     - `wechat`：尽量转微信文案，无法映射时替换为 `[表情]`

3. `split_reply_chunks`
   - 功能：按长度和标点切普通分段。
   - 实现：优先在句号、问号、换行等标点边界切分。

4. `split_reply_naturally`
   - 功能：做更像真人发消息的自然分段。
   - 实现：在最小/最大长度区间内按分隔符优先级切段。

5. `backend/bot.py::_send_smart_reply`
   - 功能：统一处理非流式回复发送。
   - 实现：
     - 自然分段：按配置拆段
     - 每段调用 `send_reply_chunks()`
     - 任一发送失败立即抛错，不再误记成功

6. `backend/bot.py::_process_and_reply`
   - 功能：统一处理同步调用、deadline 控制与预算内真实回复。
   - 实现：
     - 根据 `reply_deadline_sec` 计算剩余预算
     - 超出预算时转入延后发送真实回复，不再生成兜底文本
     - 统一走 `_send_smart_reply()` 和 `finalize_request()`
     - 保证“接收消息 → 发送消息 → 完成落盘”闭环不断裂

7. `backend/handlers/sender.py::send_reply_chunks`
   - 功能：底层分块发送器。
   - 实现：
     - 控制 chunk 间延迟
     - 控制最小回复间隔

## 13. 配置保存与热更新链

链路目标：设置页保存后，配置能即时体现在运行中的机器人上。

### 节点

1. `backend/core/config_service.py`
   - 功能：维护中心化配置快照。
   - 实现：
     - 合并默认配置、override 和其他来源。
     - 提供 `get_snapshot/reload/publish/update_override`。

2. `backend/shared_config.py`
   - 功能：维护共享配置文件路径、旧配置迁移和前后端共同字段。
   - 实现：
     - 以 `data/app_config.json` 作为运行时唯一真实配置源。
     - 兼容迁移 `backend/config.py`、`data/config_override.json`、`data/api_keys.py`、`prompt_overrides.py`。
     - 暴露 `get_app_config_path()` 与 `migrate_legacy_config()` 供 Electron、CLI 和后端复用。

3. `src/main/shared-config.js`
   - 功能：Electron 主进程侧共享配置入口。
   - 实现：
     - 解析安装包或开发环境中的可写 `data` 目录。
     - 通过 IPC 让设置页直接读写 `app_config.json`。

4. `backend/api.py::save_config`
   - 功能：兼容 Web API 保存配置入口。
   - 实现：
     - 更新 override 文件。
     - 计算 `changed_paths`。
     - 生成 `reload_plan`。
     - 当机器人正在运行时触发 `reload_runtime_config()`。

5. `backend/core/config_cli.py`
   - 功能：命令行配置辅助入口。
   - 实现：
     - `python run.py config migrate` 迁移旧配置到 `app_config.json`。
     - `python run.py config validate` 校验并规范化配置。
     - `python run.py config probe` 使用当前配置或 stdin patch 测试 AI 联通。

6. `backend/bot.py::reload_runtime_config`
   - 功能：运行时热应用配置。
   - 实现：
     - 更新当前 bot/config/agent 配置。
     - 必要时重载 AI 客户端。
     - 必要时重连微信传输层。
     - 广播状态变化。

7. `backend/core/config_audit.py`
   - 功能：配置审计。
   - 实现：
     - 标出配置项属于 live/restart/transport 级别。
     - 输出未知 override 路径与影响摘要。

## 14. 状态、诊断与观测链

链路目标：让前端和运维能够知道系统当前是否可用、卡在哪一层、为什么失败。

### 节点

1. `BotManager.get_status`
   - 功能：统一组装状态快照。
   - 实现：
     - 汇总运行状态、startup、transport、AI、统计、观测字段。
     - 透出 `AgentRuntime.get_status()` 中的 `trace_logger`，用于查看最近模型调用的脱敏摘要。

2. `_build_health_checks`
   - 功能：构建 `ai/wechat/database` 三类健康检查。
   - 实现：根据运行状态、连接状态、启动阶段和数据库连接情况输出结构化 health。

3. `_build_diagnostics`
   - 功能：构建结构化诊断信息。
   - 实现：
     - 启动中不误报失败。
     - 运行中断链时输出 `wechat_disconnected`、`transport_warning` 等诊断。

4. `export_metrics`
   - 功能：导出 Prometheus 风格指标。
   - 实现：输出运行、回复量、CPU、内存、队列、health check 等指标。

5. `/api/readiness`
   - 功能：输出启动前准备度和阻塞项。
   - 实现：
     - 默认 `deployment_target=desktop`，检查 Python、依赖、管理员权限、微信进程、微信安装、WCFerry 兼容性、传输配置和 API 配置。
     - 当环境变量 `WECHAT_BOT_DEPLOYMENT_TARGET=web-api` 时，依赖检查不要求 `wcferry`，并把管理员权限、微信进程、微信安装和 WCFerry 兼容性标为 `skipped`。
     - `web-api` 目标只表示 Web API/readiness/eval 部署边界，不表示微信传输层可用。

6. `event_generator` / `broadcast_event`
   - 功能：把状态和消息广播到前端。
   - 实现：SSE 推送 `status_change`、`message` 等事件。

7. `src/main/diagnostics-snapshot.js`
   - 功能：导出本机诊断支持包。
   - 实现：
     - 由 Electron 主进程聚合 `/api/status`、`/api/readiness`、`/api/config/audit`、更新器状态和最近日志摘要。
     - 生成本地 JSON 文件，不自动上传。
     - 导出前会脱敏 API Key、token、authorization、OAuth/session、聊天正文、联系人真实标识和完整本机路径。

8. `src/main/ipc.js`
   - 功能：收口桌面端可调用的后端请求和诊断导出入口。
   - 实现：
     - 只允许主渲染入口页调用受控 IPC。
     - 后端请求通过 allowlist 转发，Prompt 回滚和 Tool Workflow 只开放明确路径。
     - 诊断导出仍由主进程完成本地文件保存和敏感字段脱敏。

## 15. 更新链

链路目标：桌面端检查新版本、下载并提示安装。

### 节点

1. `src/main/update-manager.js`
   - 功能：桌面端更新管理。
   - 实现：调用 GitHub Releases API 获取最新版本、Release 正文和 `setup.exe` 下载地址；维护跳过版本、下载进度、已下载待安装状态，并在退出前延迟启动安装包。

2. `src/renderer/js/app.module.js`
   - 功能：前端更新状态展示。
   - 实现：订阅更新状态，更新侧边栏提示与全局更新弹窗；弹窗支持跳过版本、开始下载和安装重启。

3. `src/renderer/js/pages/AboutPage.js`
   - 功能：关于页更新入口。
   - 实现：在关于页 Hero 展示当前版本、最新版本、检查时间、下载进度与安装入口；在安装版环境中触发真实下载，在便携版环境中回退到 GitHub Releases 页面。

## 16. 当前文档边界

本文档覆盖的是“系统如何工作”。

不覆盖的内容：

- 每个配置项的字段级说明
- 用户安装操作步骤
- 发布流程

这些内容分别见：

- `README.md`
- `docs/USER_GUIDE.md`
- `docs/HIGHLIGHTS.md`
