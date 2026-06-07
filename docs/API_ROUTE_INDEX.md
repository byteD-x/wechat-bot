# API Route Index

本文件由 `scripts/generate_api_route_index.py` 从 `backend/api.py` 的 `@app.route` 装饰器静态生成。
它只记录路由、方法、处理函数和源码行号，用于发现接口清单漂移；详细请求、响应和安全边界仍以 `docs/api.md` 为准。

生成命令：

```powershell
.\.venv\Scripts\python.exe scripts\generate_api_route_index.py
```

- Source: `backend/api.py`
- Route count: `76`

| Methods | Path | Handler | Source |
| --- | --- | --- | --- |
| `GET` | `/api/auth/providers` | `get_auth_providers_api` | `backend/api.py:2418` |
| `POST` | `/api/auth/providers/<provider_key>/cancel` | `cancel_auth_provider_flow` | `backend/api.py:2442` |
| `POST` | `/api/auth/providers/<provider_key>/logout_source` | `logout_auth_provider_source` | `backend/api.py:2473` |
| `POST` | `/api/auth/providers/<provider_key>/start` | `start_auth_provider_flow` | `backend/api.py:2427` |
| `POST` | `/api/auth/providers/<provider_key>/submit_callback` | `submit_auth_provider_callback` | `backend/api.py:2457` |
| `GET` | `/api/backups` | `list_backups` | `backend/api.py:1754` |
| `POST` | `/api/backups` | `create_backup` | `backend/api.py:1766` |
| `POST` | `/api/backups/cleanup` | `cleanup_backups` | `backend/api.py:1811` |
| `POST` | `/api/backups/restore` | `restore_backup` | `backend/api.py:1844` |
| `GET` | `/api/config` | `get_config` | `backend/api.py:2514` |
| `POST` | `/api/config` | `save_config` | `backend/api.py:2555` |
| `GET` | `/api/config/audit` | `get_config_audit` | `backend/api.py:2526` |
| `GET` | `/api/contact_profile` | `get_contact_profile` | `backend/api.py:1483` |
| `POST` | `/api/contact_prompt` | `save_contact_prompt` | `backend/api.py:1505` |
| `GET` | `/api/costs/review_queue_export` | `export_cost_review_queue` | `backend/api.py:2365` |
| `GET` | `/api/costs/session_details` | `get_cost_session_details` | `backend/api.py:2345` |
| `GET` | `/api/costs/sessions` | `get_cost_sessions` | `backend/api.py:2329` |
| `GET` | `/api/costs/summary` | `get_costs_summary` | `backend/api.py:2313` |
| `GET` | `/api/data_controls` | `get_data_controls` | `backend/api.py:2038` |
| `POST` | `/api/data_controls/clear` | `clear_data_controls` | `backend/api.py:2056` |
| `GET` | `/api/evals/latest` | `get_latest_eval_report` | `backend/api.py:2244` |
| `GET` | `/api/events` | `sse_events` | `backend/api.py:1227` |
| `GET` | `/api/events_ticket` | `get_events_ticket` | `backend/api.py:1242` |
| `POST` | `/api/growth/start` | `start_growth` | `backend/api.py:1264` |
| `POST` | `/api/growth/stop` | `stop_growth` | `backend/api.py:1271` |
| `GET` | `/api/growth/tasks` | `list_growth_tasks` | `backend/api.py:1278` |
| `POST` | `/api/growth/tasks/<task_type>/clear` | `clear_growth_task` | `backend/api.py:1285` |
| `POST` | `/api/growth/tasks/<task_type>/pause` | `pause_growth_task` | `backend/api.py:1299` |
| `POST` | `/api/growth/tasks/<task_type>/resume` | `resume_growth_task` | `backend/api.py:1306` |
| `POST` | `/api/growth/tasks/<task_type>/run` | `run_growth_task` | `backend/api.py:1292` |
| `POST` | `/api/knowledge_base/delete` | `delete_knowledge_base_document` | `backend/api.py:2203` |
| `POST` | `/api/knowledge_base/dry-run` | `preview_knowledge_base_document` | `backend/api.py:2149` |
| `POST` | `/api/knowledge_base/ingest` | `ingest_knowledge_base_document` | `backend/api.py:2164` |
| `POST` | `/api/knowledge_base/rebuild` | `rebuild_knowledge_base_document` | `backend/api.py:2170` |
| `GET` | `/api/knowledge_base/status` | `get_knowledge_base_status` | `backend/api.py:2124` |
| `GET` | `/api/logs` | `get_logs` | `backend/api.py:2969` |
| `POST` | `/api/logs/clear` | `clear_logs` | `backend/api.py:3013` |
| `POST` | `/api/message_feedback` | `save_message_feedback` | `backend/api.py:1537` |
| `GET` | `/api/messages` | `get_messages` | `backend/api.py:1448` |
| `GET` | `/api/metrics` | `get_metrics` | `backend/api.py:1213` |
| `POST` | `/api/model_auth/action` | `post_model_auth_action` | `backend/api.py:2403` |
| `GET` | `/api/model_auth/overview` | `get_model_auth_overview` | `backend/api.py:2394` |
| `GET` | `/api/model_catalog` | `get_model_catalog_api` | `backend/api.py:2384` |
| `GET` | `/api/ollama/models` | `get_ollama_models` | `backend/api.py:2488` |
| `POST` | `/api/pause` | `pause_bot` | `backend/api.py:1418` |
| `GET` | `/api/pending_replies` | `list_pending_replies` | `backend/api.py:1673` |
| `POST` | `/api/pending_replies/<int:pending_id>/approve` | `approve_pending_reply` | `backend/api.py:1703` |
| `POST` | `/api/pending_replies/<int:pending_id>/reject` | `reject_pending_reply` | `backend/api.py:1724` |
| `GET` | `/api/ping` | `ping` | `backend/api.py:1191` |
| `POST` | `/api/preview_prompt` | `preview_prompt` | `backend/api.py:2888` |
| `GET` | `/api/pricing` | `get_pricing` | `backend/api.py:2287` |
| `POST` | `/api/pricing/refresh` | `refresh_pricing` | `backend/api.py:2298` |
| `GET` | `/api/readiness` | `get_readiness` | `backend/api.py:1197` |
| `POST` | `/api/recover` | `recover_bot` | `backend/api.py:1441` |
| `GET` | `/api/reply_policies` | `get_reply_policies` | `backend/api.py:1601` |
| `POST` | `/api/reply_policies` | `save_reply_policies` | `backend/api.py:1622` |
| `POST` | `/api/restart` | `restart_bot` | `backend/api.py:1434` |
| `POST` | `/api/resume` | `resume_bot` | `backend/api.py:1427` |
| `POST` | `/api/send` | `send_message` | `backend/api.py:1580` |
| `POST` | `/api/start` | `start_bot` | `backend/api.py:1250` |
| `GET` | `/api/status` | `get_status` | `backend/api.py:1185` |
| `POST` | `/api/stop` | `stop_bot` | `backend/api.py:1257` |
| `POST` | `/api/test_connection` | `test_connection` | `backend/api.py:2862` |
| `GET` | `/api/usage` | `get_usage` | `backend/api.py:2276` |
| `GET` | `/api/v1/admin/prompts/<int:revision>/diff` | `diff_prompt_revision` | `backend/api.py:2648` |
| `POST` | `/api/v1/admin/prompts/<int:revision>/rollback` | `rollback_prompt_revision` | `backend/api.py:2663` |
| `GET` | `/api/v1/admin/prompts/revisions` | `list_prompt_revisions` | `backend/api.py:2637` |
| `POST` | `/api/v1/agents/tool-workflow` | `run_agent_tool_workflow` | `backend/api.py:2794` |
| `POST` | `/api/v1/mcp` | `run_readonly_mcp_adapter` | `backend/api.py:2848` |
| `POST` | `/api/wechat_export/apply` | `wechat_export_apply` | `backend/api.py:1400` |
| `POST` | `/api/wechat_export/apply/preview` | `wechat_export_preview_apply` | `backend/api.py:1383` |
| `POST` | `/api/wechat_export/contacts` | `wechat_export_contacts` | `backend/api.py:1351` |
| `GET` | `/api/wechat_export/decrypt/jobs/<job_id>` | `wechat_export_decrypt_job` | `backend/api.py:1338` |
| `POST` | `/api/wechat_export/decrypt/start` | `wechat_export_start_decrypt` | `backend/api.py:1324` |
| `POST` | `/api/wechat_export/export` | `wechat_export_run_export` | `backend/api.py:1367` |
| `POST` | `/api/wechat_export/probe` | `wechat_export_probe` | `backend/api.py:1313` |
