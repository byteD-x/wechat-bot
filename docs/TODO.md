# TODO 与成熟化路线

本文只记录当前仓库事实基础上的后续任务，避免把已完成、未完成和愿景混在一起。

## 已完成

- Windows 成熟化第一轮：桌面端壳、消息中心、设置中心、模型中心、诊断支持包和相关 Node 测试已有改动。
- Prompt 回滚 API：`POST /api/v1/admin/prompts/{revision}/rollback` 已落地，回滚追加新 active revision，并写入 `data/prompt_revisions.json` 审计账本。
- Prompt 版本列表与差异 API：`GET /api/v1/admin/prompts/revisions` 与 `GET /api/v1/admin/prompts/{revision}/diff` 已落地；列表只返回 revision 元数据，不泄露完整 Prompt，diff 供回滚确认前预览。
- Prompt 回滚 UI：设置页系统提示区已提供“Prompt 版本治理”折叠面板，可查看版本历史、先预览 diff、再确认回滚，并在成功后刷新只读注入块与运行时状态。
- 受控 Agent Tool Workflow API：`POST /api/v1/agents/tool-workflow` 已落地，当前白名单包含 `config_audit`、`readiness_check`、`prompt_preview`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run`、`data_controls_dry_run`；后端已支持 `workflow_mode="plan_reflect_repair"`，默认 direct 旧行为不变，启用后最多自动 repair 一次且仅限 schema-safe 默认值修复。
- 只读 MCP adapter：`POST /api/v1/mcp` 已落地，支持 `initialize`、`tools/list`、`tools/call`，只复用模型侧安全白名单工具，不暴露 `prompt_preview`、`config_audit`、shell、文件写入、任意 HTTP 或动态插件。
- 模型 Tool Calling 接入 ToolRegistry：`agent.model_tool_calls_enabled` 已作为默认关闭开关落地；开启后模型侧只暴露 `readiness_check`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run`、`data_controls_dry_run` 五个安全工具，不暴露 `prompt_preview` 或 `config_audit`，并通过 `/api/status.model_tool_call_stats` 返回聚合计数。
- TraceLogger-lite：`/api/status.trace_logger` 已提供内存级最近模型调用摘要，使用 hash 引用和聚合字段记录 cache、模型路由、安全护栏、模型工具调用与错误类型，不保存聊天正文、Prompt、token、工具输出或完整本机路径。
- Tool Workflow UI：仪表盘“风险与恢复 / 受控工具流”已接入白名单工具选择、dry-run、逐步 trace、失败步骤突出和恢复建议；Renderer 测试覆盖 dry-run、单步失败 trace、`continue_on_error`、最新评测、成本摘要、备份清理预览和数据治理预览的只读摘要展示。
- API 测试：已覆盖 Prompt 版本列表、diff 预览、空/损坏账本诊断、active revision 唯一性、Prompt 回滚成功、revision 不存在、白名单工具执行、只读评测/成本/维护 dry-run 工具、`plan_reflect_repair` 安全修复、MCP adapter 白名单与调用、未知工具拒绝和危险 payload 拒绝。
- Renderer 测试：已覆盖 Prompt 版本治理入口、ApiService 幂等回滚策略、必须先预览差异再执行回滚，以及成功回滚后的设置刷新与反馈。
- RAG/eval smoke 扩样：`tests/fixtures/evals/smoke_cases.json` 已从 20 条扩到 27 条，新增 Prompt 回滚、工具审计、Windows 首次运行、导出语料 RAG 风格召回、无命中回退和误命中防护场景。
- RAG/eval 数据集治理：当前 smoke fixture 已确认 UTF-8 可读，并补充导出语料 RAG 的风格召回、无命中回退和误命中防护样例。
- RAG/eval 专项门禁：`tests/fixtures/evals/rag_cases.json` 已接入 CI 离线评测门禁，`run.py eval` 摘要会展示 citation accuracy、context recall、faithfulness、answer-citation binding 和 refusal accuracy。
- RAG Hybrid Search + Query Rewrite：`agent.retriever_hybrid_enabled` 已支持显式开启规则化 query rewrite、本地关键词召回、向量/关键词候选融合与 `/api/status.retriever_stats` 计数；默认关闭以保持旧行为。
- Semantic Cache：`agent.response_cache.semantic_enabled` 已作为默认关闭的响应缓存扩展落地；开启后仅在同一 provider、model、chat、system prompt、非当前用户 prompt context、RAG citation ids 与安全策略边界内相似命中，命中后仍重新执行安全护栏。
- 知识库治理 API：`GET /api/knowledge_base/status` 与 `POST /api/knowledge_base/dry-run|ingest|rebuild|delete` 已落地，首版只支持请求体 text/Markdown，不读取任意本机文件，预览不返回正文或完整本机路径。
- 知识库治理 UI 最小入口：设置页“数据与恢复 / 知识库治理”已支持粘贴纯文本或 Markdown、刷新状态、预览分块，并要求同一份内容 dry-run 后才允许写入；暂不开放文件上传、目录扫描、rebuild 或 delete。
- 知识库治理 CLI 显式文件入口：`python run.py knowledge-base import-files` 已支持 `.txt/.md` 显式文件列表，默认只 dry-run，拒绝目录和 glob，`--apply` 才调用 loopback 本机 API 写入。
- 文档入口：`README.md`、`docs/USER_GUIDE.md`、`docs/SYSTEM_CHAINS.md`、`docs/HIGHLIGHTS.md`、`docs/api.md` 和 `docs/interview-playbook.md` 已补充。

## 下一阶段 P1

- RAG 知识库治理增强
  - 在当前粘贴式 UI 和显式文件 CLI 之上，继续评估后台队列、文件选择器和批量重建；继续保持不开放任意路径扫描。

- Windows 真实环境手测
  - 在 Windows 10/11、管理员权限、微信 PC `3.9.12.51` 下跑一次完整首启、连接、发消息、诊断导出和停止流程。
  - 记录：环境、命令、截图或日志位置、失败项、是否需要用户操作。

## 下一阶段 P2

- 统一 API 文档生成
  - 当前 `docs/api.md` 是人工维护；后续可从路由和测试生成接口清单，减少文档漂移。

- 运行时治理指标
  - 继续为 Prompt 回滚次数、API Tool Workflow 成功率、失败原因和耗时增加可观测指标。
  - 注意不要记录完整 Prompt、聊天正文或 token。

- 安装包级体验打磨
  - 检查首次运行引导、权限提示、更新失败恢复和后台服务异常退出提示是否符合成熟 Windows 产品预期。

## 保留限制

- 当前不承诺微信 `4.x` 支持。
- 当前不承诺 Linux/macOS 微信自动化。
- 当前不开放任意 Agent 工具执行。
- 当前不把 Web API 设计为公网多租户服务。
