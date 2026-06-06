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
    }
  ]
}
```

字段说明：

- `steps`: 必填，非空数组，最多 8 步。
- `dry_run`: 可选，`true` 时只返回跳过 trace，不执行工具。
- `step.tool`: 必填，只能是白名单工具。
- `step.payload`: 可选对象，单步 payload 字符串化后最多 12000 字符。
- `step.continue_on_error`: 可选，`true` 时单步失败后继续执行下一步。

执行边界：

- 每个工具必须先注册到 `ToolRegistry`，并声明 `payload_schema`、`permission`、`timeout_sec`、`retry_count` 和 handler。
- `payload_schema` 使用项目内最小 JSON Schema 子集校验 `type`、`object/properties`、`required`、`additionalProperties`。
- 当前允许权限集合为 `admin_read`；注册工具权限不匹配时会拒绝执行。
- 每个工具按注册的 `timeout_sec` 独立限时，超时会返回失败 trace；只有显式声明 `retry_count` 的注册工具会对 handler 超时或临时异常做有限重试。
- 未知工具、payload schema 不通过、权限不匹配等请求侧错误不会重试。

当前白名单工具：

- `config_audit`: 返回配置审计结果。
- `readiness_check`: 返回启动前就绪检查报告。
- `prompt_preview`: 基于示例消息生成 Prompt 预览和长度摘要。

成功响应：

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

错误响应：

- `400 bad_workflow`: steps 缺失、超长、tool 缺失、payload 过大或工作流执行失败。
- `400` 且 `success=false`: 工作流执行中某一步失败，响应仍包含已执行 trace；失败原因可能是未知工具、payload schema 不通过、权限不匹配、工具超时、handler 异常或 handler 返回非 JSON 对象。
- `500 tool_workflow_failed`: 未预期的服务端错误。

产品约束：

- 不支持任意 shell、文件写入、网络请求或动态插件执行。
- 所有步骤都返回 `index/tool/status/duration_ms/attempts/retry_count`，注册工具还会返回 `permission/schema_valid/timeout_ms`；失败步骤会返回 `error_type`，例如 `unsupported_tool`、`schema_validation`、`permission_denied`、`timeout`、`invalid_tool_result` 或 `tool_error`，方便桌面端展示进度、失败位置、输入校验结果和恢复建议。
- 后续新增工具必须先进入白名单，并补充 API 测试与文档。

## 成熟产品化参考

- Windows 桌面端体验应继续对齐 Microsoft Fluent / Windows 控件模式：清晰的顶层导航、稳定的标题栏与命令区、明确的焦点态和错误恢复路径。
- Agent 工具执行应继续对齐成熟 Agent 产品的 guardrails 和 tracing 思路：工具白名单、输入限制、逐步 trace、失败可解释、必要时人工确认。

参考资料：

- [Windows Controls and patterns](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/)
- [NavigationView - Windows apps](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)
- [OpenAI Agents SDK Guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK Tracing](https://openai.github.io/openai-agents-python/tracing/)
