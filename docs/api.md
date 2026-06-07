# API 契约与治理接口

本文记录当前已经落地、可通过本地 Quart API 调用的治理接口。它们面向桌面端、调试脚本和受信任的本机自动化，不是公网开放接口。

## 通用安全边界

- 默认只允许本机访问；绑定非回环地址运行 `python run.py web` 时必须显式设置 `WECHAT_BOT_API_TOKEN`。
- 设置 `WECHAT_BOT_API_TOKEN` 后，`/api/*` 请求需要携带 `X-Api-Token` 或 `Authorization: Bearer <token>`。
- Electron 主进程只允许转发白名单路径；Prompt 治理与 Agent Tool Workflow 已加入 `src/main/ipc.js` 的 allowlist。
- 不要把 API token、模型密钥、OAuth/session、聊天原文或诊断支持包中的敏感内容写入日志、截图或文档。

## GET `/api/v1/admin/prompts/revisions`

用途：只读列出系统 Prompt 审计账本中的 revision 元数据，用于桌面端展示版本历史，不直接返回完整 Prompt 正文。

实现入口：

- `backend/api.py::list_prompt_revisions`
- `backend/core/prompt_governance.py::PromptGovernanceService.list_revisions`

成功响应包含：

- `success`: 固定为 `true`。
- `schema_version`: Prompt 审计账本 schema 版本。
- `active_revision`: 当前 active revision；账本为空时为 `0`。
- `revision_count`: 当前可读取 revision 数量。
- `revisions`: revision 元数据列表，只包含 `revision`、`status`、`source`、`created_at`、`rollback_from`、`reason`、`operator`、`active`、`prompt_length`、`editable_prompt_length`。
- `issues`: 账本诊断问题，例如 `ledger_missing`、`ledger_parse_failed`、`revisions_not_array`、`invalid_active_revision_count`、`active_revision_not_found`。
- `ledger_path`: 本地审计账本路径，默认 `data/prompt_revisions.json`。

错误响应：

- `500 prompt_revision_list_failed`: 未预期的服务端错误。

产品约束：

- 该接口不会 seed、写入或修复账本，只暴露可诊断的只读视图。
- `revisions` 不包含 `prompt` 或 `editable_prompt` 字段，避免桌面端列表、日志或调试输出意外泄露完整 Prompt。

## GET `/api/v1/admin/prompts/{revision}/diff`

用途：预览当前 active Prompt 与目标历史 revision 的统一 diff，供回滚确认前展示“将要回滚哪些内容”。

实现入口：

- `backend/api.py::diff_prompt_revision`
- `backend/core/prompt_governance.py::PromptGovernanceService.diff_revision`

字段说明：

- `revision`: 路径参数，正整数，表示要对比的历史版本。

成功响应包含：

- `success`: 固定为 `true`。
- `active_revision`: 当前 active revision。
- `target_revision`: 目标历史 revision。
- `from_revision`: active revision 的元数据摘要，不含完整 Prompt 字段。
- `to_revision`: 目标 revision 的元数据摘要，不含完整 Prompt 字段。
- `diff`: 从 active 到 target 的 unified diff 行数组，`fromfile` 为 `active:<revision>`，`tofile` 为 `target:<revision>`。
- `summary`: 包含 `changed`、`line_count`、`active_prompt_length`、`target_prompt_length`。
- `issues`: 账本诊断问题。
- `ledger_path`: 本地审计账本路径。

错误响应：

- `400 bad_request`: revision 非正整数。
- `404 prompt_revision_not_found`: 指定 revision 不存在，或账本没有可对比的 active revision。
- `500 prompt_revision_diff_failed`: 未预期的服务端错误。

产品约束：

- diff 是受信任本机治理预览能力，可能包含 Prompt 片段；不要把 diff 内容写入日志、诊断支持包或公开文档。
- 该接口不修改账本，也不会触发回滚。

## POST `/api/v1/admin/prompts/{revision}/rollback`

用途：把系统 Prompt 回滚到指定历史版本，同时追加一条新的 active revision，保留旧版本和回滚审计信息。

实现入口：

- `backend/api.py::rollback_prompt_revision`
- `backend/core/prompt_governance.py::PromptGovernanceService`

请求体：

```json
{
  "reason": "上一版更稳定",
  "operator": "desktop"
}
```

字段说明：

- `revision`: 路径参数，正整数，表示要回滚到的历史版本。
- `reason`: 可选，回滚原因，最多保留 500 个字符。
- `operator`: 可选，操作者标识，最多保留 80 个字符，默认 `api`。

成功响应包含：

- `success`: 固定为 `true`。
- `active_revision`: 回滚后新生成的 active revision。
- `rolled_back_from`: 目标历史 revision。
- `revision`: 新 revision 的审计记录，包含 `source=rollback`、`rollback_from`、`reason`、`operator`、`created_at`。
- `ledger_path`: 本地审计账本路径，默认 `data/prompt_revisions.json`。
- `config`: 保存后的脱敏配置快照。
- `changed_paths`: 配置变化路径。
- `reload_plan`: 热重载计划。
- `runtime_apply`: 如果 bot 正在运行，返回运行时热应用结果；未运行时为 `null`。

错误响应：

- `400 bad_request`: revision 非正整数或 Prompt 超过长度限制。
- `404 prompt_revision_not_found`: 指定 revision 不存在。
- `500 prompt_rollback_failed`: 未预期的服务端错误。

产品约束：

- 回滚不会覆盖历史记录，而是复制目标 Prompt 生成一个新的 active revision。
- 首次回滚前如果账本不存在，会从当前配置 seed 出 revision `1`。
- 当前已提供只读版本列表、差异预览和回滚写入能力；完整的版本创建与 UI 审批仍在后续 TODO 中。

## POST `/api/v1/agents/tool-workflow`

用途：按顺序执行一组受控的内部工具，返回每一步 trace。该接口用于把 Agent 能力产品化为可审计、可失败降级的本机工作流。

实现入口：

- `backend/api.py::run_agent_tool_workflow`
- `backend/core/tool_workflow.py::ControlledToolWorkflowService`
- `backend/core/tool_workflow.py::ToolRegistry`

请求体：

```json
{
  "dry_run": false,
  "workflow_mode": "direct",
  "steps": [
    { "tool": "config_audit", "payload": {} },
    { "tool": "readiness_check", "payload": {} },
    {
      "tool": "prompt_preview",
      "payload": {
        "sample": {
          "chat_name": "preview_contact",
          "sender": "preview_user",
          "message": "你好"
        }
      }
    },
    { "tool": "eval_latest", "payload": {} },
    { "tool": "cost_summary", "payload": { "period": "30d", "include_estimated": true } },
    { "tool": "backup_cleanup_dry_run", "payload": { "keep_quick": 5, "keep_full": 3, "protect_restore_anchor": true } },
    { "tool": "data_controls_dry_run", "payload": { "scopes": ["memory", "usage", "export_rag"] } }
  ]
}
```

字段说明：

- `steps`: 必填，非空数组，最多 8 步。
- `dry_run`: 可选，`true` 时只返回跳过 trace，不执行工具。
- `workflow_mode`: 可选，默认 `direct`；传入 `plan_reflect_repair` 时返回 `planning / reflection / repair` 摘要，并启用一次受控 repair。
- `step.tool`: 必填，只能是白名单工具。
- `step.payload`: 可选对象，单步 payload 字符串化后最多 12000 字符。
- `step.continue_on_error`: 可选，`true` 时单步失败后继续执行下一步。

执行边界：

- 每个工具必须先注册到 `ToolRegistry`，并声明 `payload_schema`、`permission`、`timeout_sec`、`retry_count` 和 handler。
- `payload_schema` 使用项目内最小 JSON Schema 子集校验 `type`、`object/properties`、`required`、`additionalProperties`。
- 当前允许权限集合为 `admin_read`；注册工具权限不匹配时会拒绝执行。
- 每个工具按注册的 `timeout_sec` 独立限时，超时会返回失败 trace；只有显式声明 `retry_count` 的注册工具会对 handler 超时或临时异常做有限重试。
- 未知工具、payload schema 不通过、权限不匹配等请求侧错误不会重试。
- `plan_reflect_repair` 最多自动 repair 一次，当前仅允许 `data_controls_dry_run` 的空 `scopes` 回落到默认治理范围；未知工具、权限失败、危险 payload、超时或非白名单路径只会返回 blocked reflection。

当前白名单工具：

- `config_audit`: 返回配置审计结果。
- `readiness_check`: 返回启动前就绪检查报告。
- `prompt_preview`: 基于示例消息生成 Prompt 预览和长度摘要。
- `eval_latest`: 返回最新本地评测报告的名称、版本、摘要和回归数量，不返回完整 `cases`。
- `cost_summary`: 返回成本概览、筛选条件、模型数量和待复核数量，不返回完整 `review_queue`。
- `backup_cleanup_dry_run`: 预览备份清理策略与可回收空间，只返回候选数量、保留数量、保护数量和备份总量，不返回备份路径、候选列表或删除目标。
- `data_controls_dry_run`: 预览数据治理清理范围，只返回 scope、目标数量、现存目标数量、不支持目标数量和可回收空间，不返回本机路径、targets 或 deleted_targets。

默认成功响应：

```json
{
  "success": true,
  "trace": [
    {
      "index": 1,
      "tool": "config_audit",
      "status": "ok",
      "duration_ms": 1.2,
      "permission": "admin_read",
      "schema_valid": true,
      "timeout_ms": 5000.0,
      "retry_count": 0,
      "attempts": 1,
      "output": {}
    }
  ]
}
```

`plan_reflect_repair` 成功修复时会额外返回：

```json
{
  "planning": {
    "workflow_mode": "plan_reflect_repair",
    "step_count": 1,
    "tools": ["data_controls_dry_run"],
    "max_repair_attempts": 1,
    "repair_policy": "schema_safe_defaults_only"
  },
  "repair": {
    "attempted": true,
    "count": 1,
    "max_attempts": 1,
    "items": [
      {
        "step_index": 1,
        "tool": "data_controls_dry_run",
        "action": "use_default_scopes",
        "reason": "empty scopes fallback to default data control scopes",
        "attempt": 1
      }
    ]
  },
  "reflection": {
    "status": "resolved",
    "items": [
      {
        "step_index": 1,
        "tool": "data_controls_dry_run",
        "status": "resolved",
        "error_type": "schema_validation",
        "message": "payload.scopes must contain at least 1 item(s)",
        "repairable": true,
        "repair_action": "use_default_scopes"
      }
    ]
  }
}
```

错误响应：

- `400 bad_workflow`: steps 缺失、超长、tool 缺失、payload 过大或工作流执行失败。
- `400` 且 `success=false`: 工作流执行中某一步失败，响应仍包含已执行 trace；失败原因可能是未知工具、payload schema 不通过、权限不匹配、工具超时、handler 异常或 handler 返回非 JSON 对象。
- `500 tool_workflow_failed`: 未预期的服务端错误。

产品约束：

- 不支持任意 shell、文件写入、网络请求或动态插件执行。
- 所有步骤都返回 `index/tool/status/duration_ms/attempts/retry_count`，注册工具还会返回 `permission/schema_valid/timeout_ms`；失败步骤会返回 `error_type`，例如 `unsupported_tool`、`schema_validation`、`permission_denied`、`timeout`、`invalid_tool_result` 或 `tool_error`，方便桌面端展示进度、失败位置、输入校验结果和恢复建议。
- `prompt_preview`、`eval_latest`、`cost_summary`、`backup_cleanup_dry_run` 和 `data_controls_dry_run` 的 trace 输出只用于本机诊断摘要，不在响应中展开完整 Prompt、评测用例、聊天正文、成本复核队列、备份候选列表、清理 targets 或完整本机路径。
- `plan_reflect_repair` 只属于本机治理 API，不接入微信消息快回复主链路。
- 后续新增工具必须先进入白名单，并补充 API 测试与文档。

## POST `/api/v1/mcp`

用途：提供一个本机只读 MCP JSON-RPC adapter，用于让外部 MCP host 发现并调用安全摘要工具。它复用 `ControlledToolWorkflowService`，不是动态插件市场，也不会启动独立 MCP 进程。

实现入口：

- `backend/api.py::run_readonly_mcp_adapter`
- `backend/core/mcp_adapter.py::ReadOnlyMCPAdapter`
- `backend/core/tool_workflow.py::ControlledToolWorkflowService`

支持方法：

- `initialize`: 返回协议版本、工具能力和本机 serverInfo。
- `tools/list`: 返回 MCP tool 列表。
- `tools/call`: 调用单个安全工具，返回 `content` 与 `structuredContent`。

请求体示例：

```json
{
  "jsonrpc": "2.0",
  "id": "call-1",
  "method": "tools/call",
  "params": {
    "name": "data_controls_dry_run",
    "arguments": {
      "scopes": ["memory"]
    }
  }
}
```

可见工具：

- `readiness_check`
- `eval_latest`
- `cost_summary`
- `backup_cleanup_dry_run`
- `data_controls_dry_run`

响应示例：

```json
{
  "jsonrpc": "2.0",
  "id": "call-1",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "data_controls_dry_run completed: {...}"
      }
    ],
    "structuredContent": {
      "success": true,
      "tool": "data_controls_dry_run",
      "trace": [],
      "output": {
        "success": true,
        "dry_run": true,
        "scopes": ["memory"],
        "target_count": 3,
        "existing_target_count": 2,
        "unsupported_target_count": 1,
        "reclaimable_bytes": 4096,
        "deleted_count": 0
      }
    }
  }
}
```

错误边界：

- 非 JSON object、缺少 `jsonrpc: "2.0"` 或未知 method 会返回 JSON-RPC `error`。
- `tools/call` 的 `params.name` 必填，`params.arguments` 必须是 JSON object。
- `prompt_preview`、`config_audit`、未知工具和非安全工具会返回 `isError: true` 的工具结果，不会进入执行路径。

产品约束：

- 该 adapter 不实现 resources、prompts、shell、文件写入、任意 HTTP 或动态插件。
- `tools/list` 和 `tools/call` 只复用模型侧安全白名单，不暴露 `prompt_preview` 或 `config_audit`。
- 工具调用结果沿用既有脱敏摘要，不返回完整 Prompt、评测用例、聊天正文、成本复核队列、备份候选列表、清理 targets 或完整本机路径。
- 该 adapter 只属于本机治理 API，不接入微信消息快回复主链路。

## 知识库治理 API

用途：把现有 `KnowledgeBaseService` 暴露成受控的本机治理接口，用于预览、写入、重建、删除和查看知识库向量 chunk 状态。

实现入口：

- `backend/api.py::get_knowledge_base_status`
- `backend/api.py::preview_knowledge_base_document`
- `backend/api.py::ingest_knowledge_base_document`
- `backend/api.py::rebuild_knowledge_base_document`
- `backend/api.py::delete_knowledge_base_document`
- `backend/core/knowledge_base.py::KnowledgeBaseService`
- `backend/core/knowledge_base_cli.py::build_knowledge_base_parser`

当前端点：

- `GET /api/knowledge_base/status`
- `POST /api/knowledge_base/dry-run`
- `POST /api/knowledge_base/ingest`
- `POST /api/knowledge_base/rebuild`
- `POST /api/knowledge_base/delete`

请求体示例：

```json
{
  "content": "# Release playbook\n\nQA signs off after smoke tests.",
  "content_type": "markdown",
  "doc_id": "release-playbook",
  "version": "2026-06",
  "source_file": "docs/release-playbook.md",
  "url": "https://example.test/release-playbook",
  "page": 3,
  "metadata": {
    "owner": "platform"
  }
}
```

字段说明：

- `content`: `dry-run`、`ingest`、`rebuild` 必填，最多 120000 字符。
- `content_type`: 可选，支持 `text`、`plain`、`markdown`、`text/plain`、`text/markdown`。
- `doc_id`: 可选；未提供时会从 `source_file`、`url` 或正文 hash 派生。
- `version` / `doc_version`: 可选，默认 `v1`。
- `source_file`、`url`、`page`、`metadata`: 可选，写入 chunk metadata，供 RAG citation 绑定。

响应摘要：

- `dry-run` 只返回 `doc_id`、`version`、`chunk_count`、`chunk_ids`、`char_count` 和每个 chunk 的 `chunk_id/chunk_index/char_count/source_file/url/page` 摘要，不返回 chunk 正文。
- `status` 返回 `vector_memory_available`、`source=knowledge_base` 和当前知识库 chunk 数。
- `ingest` 写入新 chunk；`rebuild` 会先完整准备新版本 chunk embedding，再删除同一 `doc_id` 的旧 chunk 并写入新 chunk。
- `delete` 只按精确 `{"source": "knowledge_base", "doc_id": "<doc_id>"}` 删除，不影响聊天记忆或其他来源。

错误响应：

- `400`: 请求体不是 JSON object，`dry-run / ingest / rebuild` 缺少 `content`，`delete` 缺少 `doc_id`，或字段类型/长度不符合要求。
- `409 vector_memory_unavailable`: 运行中的 bot 没有可用 `vector_memory`。
- `409 embedding_unavailable`: `ingest` 或 `rebuild` 时运行中的 bot 没有可用 `ai_client.get_embedding`。
- `500 knowledge_base_*_failed`: 未预期的服务端错误。

产品约束：

- 首版只接收请求体中的纯文本或 Markdown；不会读取任意本机文件路径、不会扫描目录，也不提供文件上传。
- 本机 CLI `python run.py knowledge-base import-files` 是独立的显式文件列表入口：只读取用户逐个传入的 `.txt/.md` 文件，拒绝目录和 glob，默认 dry-run；`--apply` 才调用 loopback 本机 API 写入，不改变 Web API “不读取文件路径”的约束。
- `doc_id / source_file / url / source_url` 只用于引用元数据；如果看起来像完整本机路径或 `file://` 本机 URI，响应和删除匹配会收敛为 `.../<filename>`。
- 预览和治理响应不返回完整正文、chunk text、embedding 或完整本机路径。
- `ingest`、`rebuild` 依赖运行中的向量库和 embedding 客户端；`rebuild` 会先完整准备新版本 chunk embedding，准备失败时返回 `no_chunks_indexed` 或 `incomplete_embeddings`，并保留旧 chunk。
- 离线批量导入、后台队列和文件索引属于后续任务。

## 成熟产品化参考

- Windows 桌面端体验应继续对齐 Microsoft Fluent / Windows 控件模式：清晰的顶层导航、稳定的标题栏与命令区、明确的焦点态和错误恢复路径。
- Agent 工具执行应继续对齐成熟 Agent 产品的 guardrails 和 tracing 思路：工具白名单、输入限制、逐步 trace、失败可解释、必要时人工确认。

参考资料：

- [Windows Controls and patterns](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/)
- [NavigationView - Windows apps](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)
- [OpenAI Agents SDK Guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK Tracing](https://openai.github.io/openai-agents-python/tracing/)
