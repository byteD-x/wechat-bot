# API Route Index

本文件由 `scripts/generate_api_route_index.py` 从 `backend/api.py` 的 `@app.route` 装饰器静态生成。
它只记录路由、方法、处理函数和源码行号，用于发现接口清单漂移；详细请求、响应和安全边界仍以 `docs/api.md` 为准。

生成命令：

```powershell
.\.venv\Scripts\python.exe scripts\generate_api_route_index.py
```

- Source: `backend/api.py`
- Route count: `84`

| Methods | Path | Handler | Source |
| --- | --- | --- | --- |
| `GET` | `/api/auth/providers` | `get_auth_providers_api` | `backend/api.py:2714` |
| `POST` | `/api/auth/providers/<provider_key>/cancel` | `cancel_auth_provider_flow` | `backend/api.py:2738` |
| `POST` | `/api/auth/providers/<provider_key>/logout_source` | `logout_auth_provider_source` | `backend/api.py:2769` |
| `POST` | `/api/auth/providers/<provider_key>/start` | `start_auth_provider_flow` | `backend/api.py:2723` |
| `POST` | `/api/auth/providers/<provider_key>/submit_callback` | `submit_auth_provider_callback` | `backend/api.py:2753` |
| `GET` | `/api/backups` | `list_backups` | `backend/api.py:1775` |
| `POST` | `/api/backups` | `create_backup` | `backend/api.py:1787` |
| `POST` | `/api/backups/cleanup` | `cleanup_backups` | `backend/api.py:1832` |
| `POST` | `/api/backups/restore` | `restore_backup` | `backend/api.py:1865` |
| `GET` | `/api/config` | `get_config` | `backend/api.py:2810` |
| `POST` | `/api/config` | `save_config` | `backend/api.py:2851` |
| `GET` | `/api/config/audit` | `get_config_audit` | `backend/api.py:2822` |
| `GET` | `/api/contact_profile` | `get_contact_profile` | `backend/api.py:1504` |
| `POST` | `/api/contact_prompt` | `save_contact_prompt` | `backend/api.py:1526` |
| `GET` | `/api/costs/review_queue_export` | `export_cost_review_queue` | `backend/api.py:2661` |
| `GET` | `/api/costs/session_details` | `get_cost_session_details` | `backend/api.py:2641` |
| `GET` | `/api/costs/sessions` | `get_cost_sessions` | `backend/api.py:2625` |
| `GET` | `/api/costs/summary` | `get_costs_summary` | `backend/api.py:2609` |
| `GET` | `/api/data_controls` | `get_data_controls` | `backend/api.py:2059` |
| `POST` | `/api/data_controls/clear` | `clear_data_controls` | `backend/api.py:2077` |
| `GET` | `/api/evals/latest` | `get_latest_eval_report` | `backend/api.py:2540` |
| `GET` | `/api/events` | `sse_events` | `backend/api.py:1248` |
| `GET` | `/api/events_ticket` | `get_events_ticket` | `backend/api.py:1263` |
| `POST` | `/api/growth/start` | `start_growth` | `backend/api.py:1285` |
| `POST` | `/api/growth/stop` | `stop_growth` | `backend/api.py:1292` |
| `GET` | `/api/growth/tasks` | `list_growth_tasks` | `backend/api.py:1299` |
| `POST` | `/api/growth/tasks/<task_type>/clear` | `clear_growth_task` | `backend/api.py:1306` |
| `POST` | `/api/growth/tasks/<task_type>/pause` | `pause_growth_task` | `backend/api.py:1320` |
| `POST` | `/api/growth/tasks/<task_type>/resume` | `resume_growth_task` | `backend/api.py:1327` |
| `POST` | `/api/growth/tasks/<task_type>/run` | `run_growth_task` | `backend/api.py:1313` |
| `POST` | `/api/knowledge_base/auto-index/jobs` | `create_knowledge_base_auto_index_job` | `backend/api.py:2229` |
| `GET` | `/api/knowledge_base/auto-index/preview` | `preview_knowledge_base_auto_index` | `backend/api.py:2215` |
| `POST` | `/api/knowledge_base/batch-dry-run` | `preview_knowledge_base_documents` | `backend/api.py:2295` |
| `POST` | `/api/knowledge_base/batch-ingest` | `ingest_knowledge_base_documents` | `backend/api.py:2366` |
| `POST` | `/api/knowledge_base/batch-rebuild` | `rebuild_knowledge_base_documents` | `backend/api.py:2401` |
| `POST` | `/api/knowledge_base/delete` | `delete_knowledge_base_document` | `backend/api.py:2499` |
| `POST` | `/api/knowledge_base/dry-run` | `preview_knowledge_base_document` | `backend/api.py:2280` |
| `GET` | `/api/knowledge_base/index` | `get_knowledge_base_index` | `backend/api.py:2172` |
| `POST` | `/api/knowledge_base/ingest` | `ingest_knowledge_base_document` | `backend/api.py:2443` |
| `POST` | `/api/knowledge_base/jobs` | `create_knowledge_base_job` | `backend/api.py:2310` |
| `GET` | `/api/knowledge_base/jobs/<job_id>` | `get_knowledge_base_job` | `backend/api.py:2351` |
| `POST` | `/api/knowledge_base/rebuild` | `rebuild_knowledge_base_document` | `backend/api.py:2449` |
| `GET` | `/api/knowledge_base/status` | `get_knowledge_base_status` | `backend/api.py:2145` |
| `GET` | `/api/logs` | `get_logs` | `backend/api.py:3265` |
| `POST` | `/api/logs/clear` | `clear_logs` | `backend/api.py:3309` |
| `POST` | `/api/message_feedback` | `save_message_feedback` | `backend/api.py:1558` |
| `GET` | `/api/messages` | `get_messages` | `backend/api.py:1469` |
| `GET` | `/api/metrics` | `get_metrics` | `backend/api.py:1234` |
| `POST` | `/api/model_auth/action` | `post_model_auth_action` | `backend/api.py:2699` |
| `GET` | `/api/model_auth/overview` | `get_model_auth_overview` | `backend/api.py:2690` |
| `GET` | `/api/model_catalog` | `get_model_catalog_api` | `backend/api.py:2680` |
| `GET` | `/api/ollama/models` | `get_ollama_models` | `backend/api.py:2784` |
| `POST` | `/api/pause` | `pause_bot` | `backend/api.py:1439` |
| `GET` | `/api/pending_replies` | `list_pending_replies` | `backend/api.py:1694` |
| `POST` | `/api/pending_replies/<int:pending_id>/approve` | `approve_pending_reply` | `backend/api.py:1724` |
| `POST` | `/api/pending_replies/<int:pending_id>/reject` | `reject_pending_reply` | `backend/api.py:1745` |
| `GET` | `/api/ping` | `ping` | `backend/api.py:1212` |
| `POST` | `/api/preview_prompt` | `preview_prompt` | `backend/api.py:3184` |
| `GET` | `/api/pricing` | `get_pricing` | `backend/api.py:2583` |
| `POST` | `/api/pricing/refresh` | `refresh_pricing` | `backend/api.py:2594` |
| `GET` | `/api/readiness` | `get_readiness` | `backend/api.py:1218` |
| `POST` | `/api/recover` | `recover_bot` | `backend/api.py:1462` |
| `GET` | `/api/reply_policies` | `get_reply_policies` | `backend/api.py:1622` |
| `POST` | `/api/reply_policies` | `save_reply_policies` | `backend/api.py:1643` |
| `POST` | `/api/restart` | `restart_bot` | `backend/api.py:1455` |
| `POST` | `/api/resume` | `resume_bot` | `backend/api.py:1448` |
| `POST` | `/api/send` | `send_message` | `backend/api.py:1601` |
| `POST` | `/api/start` | `start_bot` | `backend/api.py:1271` |
| `GET` | `/api/status` | `get_status` | `backend/api.py:1206` |
| `POST` | `/api/stop` | `stop_bot` | `backend/api.py:1278` |
| `POST` | `/api/test_connection` | `test_connection` | `backend/api.py:3158` |
| `GET` | `/api/usage` | `get_usage` | `backend/api.py:2572` |
| `GET` | `/api/v1/admin/prompts/<int:revision>/diff` | `diff_prompt_revision` | `backend/api.py:2944` |
| `POST` | `/api/v1/admin/prompts/<int:revision>/rollback` | `rollback_prompt_revision` | `backend/api.py:2959` |
| `GET` | `/api/v1/admin/prompts/revisions` | `list_prompt_revisions` | `backend/api.py:2933` |
| `POST` | `/api/v1/agents/tool-workflow` | `run_agent_tool_workflow` | `backend/api.py:3090` |
| `POST` | `/api/v1/mcp` | `run_readonly_mcp_adapter` | `backend/api.py:3144` |
| `POST` | `/api/wechat_export/apply` | `wechat_export_apply` | `backend/api.py:1421` |
| `POST` | `/api/wechat_export/apply/preview` | `wechat_export_preview_apply` | `backend/api.py:1404` |
| `POST` | `/api/wechat_export/contacts` | `wechat_export_contacts` | `backend/api.py:1372` |
| `GET` | `/api/wechat_export/decrypt/jobs/<job_id>` | `wechat_export_decrypt_job` | `backend/api.py:1359` |
| `POST` | `/api/wechat_export/decrypt/start` | `wechat_export_start_decrypt` | `backend/api.py:1345` |
| `POST` | `/api/wechat_export/export` | `wechat_export_run_export` | `backend/api.py:1388` |
| `POST` | `/api/wechat_export/probe` | `wechat_export_probe` | `backend/api.py:1334` |
