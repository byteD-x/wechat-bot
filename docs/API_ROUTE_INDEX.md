# API Route Index

本文件由 `scripts/generate_api_route_index.py` 从 `backend/api.py` 的 `@app.route` 装饰器静态生成。
它只记录路由、方法、处理函数和源码行号，用于发现接口清单漂移；详细请求、响应和安全边界仍以 `docs/api.md` 为准。

生成命令：

```powershell
.\.venv\Scripts\python.exe scripts\generate_api_route_index.py
```

- Source: `backend/api.py`
- Route count: `82`

| Methods | Path | Handler | Source |
| --- | --- | --- | --- |
| `GET` | `/api/auth/providers` | `get_auth_providers_api` | `backend/api.py:2639` |
| `POST` | `/api/auth/providers/<provider_key>/cancel` | `cancel_auth_provider_flow` | `backend/api.py:2663` |
| `POST` | `/api/auth/providers/<provider_key>/logout_source` | `logout_auth_provider_source` | `backend/api.py:2694` |
| `POST` | `/api/auth/providers/<provider_key>/start` | `start_auth_provider_flow` | `backend/api.py:2648` |
| `POST` | `/api/auth/providers/<provider_key>/submit_callback` | `submit_auth_provider_callback` | `backend/api.py:2678` |
| `GET` | `/api/backups` | `list_backups` | `backend/api.py:1765` |
| `POST` | `/api/backups` | `create_backup` | `backend/api.py:1777` |
| `POST` | `/api/backups/cleanup` | `cleanup_backups` | `backend/api.py:1822` |
| `POST` | `/api/backups/restore` | `restore_backup` | `backend/api.py:1855` |
| `GET` | `/api/config` | `get_config` | `backend/api.py:2735` |
| `POST` | `/api/config` | `save_config` | `backend/api.py:2776` |
| `GET` | `/api/config/audit` | `get_config_audit` | `backend/api.py:2747` |
| `GET` | `/api/contact_profile` | `get_contact_profile` | `backend/api.py:1494` |
| `POST` | `/api/contact_prompt` | `save_contact_prompt` | `backend/api.py:1516` |
| `GET` | `/api/costs/review_queue_export` | `export_cost_review_queue` | `backend/api.py:2586` |
| `GET` | `/api/costs/session_details` | `get_cost_session_details` | `backend/api.py:2566` |
| `GET` | `/api/costs/sessions` | `get_cost_sessions` | `backend/api.py:2550` |
| `GET` | `/api/costs/summary` | `get_costs_summary` | `backend/api.py:2534` |
| `GET` | `/api/data_controls` | `get_data_controls` | `backend/api.py:2049` |
| `POST` | `/api/data_controls/clear` | `clear_data_controls` | `backend/api.py:2067` |
| `GET` | `/api/evals/latest` | `get_latest_eval_report` | `backend/api.py:2465` |
| `GET` | `/api/events` | `sse_events` | `backend/api.py:1238` |
| `GET` | `/api/events_ticket` | `get_events_ticket` | `backend/api.py:1253` |
| `POST` | `/api/growth/start` | `start_growth` | `backend/api.py:1275` |
| `POST` | `/api/growth/stop` | `stop_growth` | `backend/api.py:1282` |
| `GET` | `/api/growth/tasks` | `list_growth_tasks` | `backend/api.py:1289` |
| `POST` | `/api/growth/tasks/<task_type>/clear` | `clear_growth_task` | `backend/api.py:1296` |
| `POST` | `/api/growth/tasks/<task_type>/pause` | `pause_growth_task` | `backend/api.py:1310` |
| `POST` | `/api/growth/tasks/<task_type>/resume` | `resume_growth_task` | `backend/api.py:1317` |
| `POST` | `/api/growth/tasks/<task_type>/run` | `run_growth_task` | `backend/api.py:1303` |
| `POST` | `/api/knowledge_base/batch-dry-run` | `preview_knowledge_base_documents` | `backend/api.py:2220` |
| `POST` | `/api/knowledge_base/batch-ingest` | `ingest_knowledge_base_documents` | `backend/api.py:2291` |
| `POST` | `/api/knowledge_base/batch-rebuild` | `rebuild_knowledge_base_documents` | `backend/api.py:2326` |
| `POST` | `/api/knowledge_base/delete` | `delete_knowledge_base_document` | `backend/api.py:2424` |
| `POST` | `/api/knowledge_base/dry-run` | `preview_knowledge_base_document` | `backend/api.py:2205` |
| `GET` | `/api/knowledge_base/index` | `get_knowledge_base_index` | `backend/api.py:2162` |
| `POST` | `/api/knowledge_base/ingest` | `ingest_knowledge_base_document` | `backend/api.py:2368` |
| `POST` | `/api/knowledge_base/jobs` | `create_knowledge_base_job` | `backend/api.py:2235` |
| `GET` | `/api/knowledge_base/jobs/<job_id>` | `get_knowledge_base_job` | `backend/api.py:2276` |
| `POST` | `/api/knowledge_base/rebuild` | `rebuild_knowledge_base_document` | `backend/api.py:2374` |
| `GET` | `/api/knowledge_base/status` | `get_knowledge_base_status` | `backend/api.py:2135` |
| `GET` | `/api/logs` | `get_logs` | `backend/api.py:3190` |
| `POST` | `/api/logs/clear` | `clear_logs` | `backend/api.py:3234` |
| `POST` | `/api/message_feedback` | `save_message_feedback` | `backend/api.py:1548` |
| `GET` | `/api/messages` | `get_messages` | `backend/api.py:1459` |
| `GET` | `/api/metrics` | `get_metrics` | `backend/api.py:1224` |
| `POST` | `/api/model_auth/action` | `post_model_auth_action` | `backend/api.py:2624` |
| `GET` | `/api/model_auth/overview` | `get_model_auth_overview` | `backend/api.py:2615` |
| `GET` | `/api/model_catalog` | `get_model_catalog_api` | `backend/api.py:2605` |
| `GET` | `/api/ollama/models` | `get_ollama_models` | `backend/api.py:2709` |
| `POST` | `/api/pause` | `pause_bot` | `backend/api.py:1429` |
| `GET` | `/api/pending_replies` | `list_pending_replies` | `backend/api.py:1684` |
| `POST` | `/api/pending_replies/<int:pending_id>/approve` | `approve_pending_reply` | `backend/api.py:1714` |
| `POST` | `/api/pending_replies/<int:pending_id>/reject` | `reject_pending_reply` | `backend/api.py:1735` |
| `GET` | `/api/ping` | `ping` | `backend/api.py:1202` |
| `POST` | `/api/preview_prompt` | `preview_prompt` | `backend/api.py:3109` |
| `GET` | `/api/pricing` | `get_pricing` | `backend/api.py:2508` |
| `POST` | `/api/pricing/refresh` | `refresh_pricing` | `backend/api.py:2519` |
| `GET` | `/api/readiness` | `get_readiness` | `backend/api.py:1208` |
| `POST` | `/api/recover` | `recover_bot` | `backend/api.py:1452` |
| `GET` | `/api/reply_policies` | `get_reply_policies` | `backend/api.py:1612` |
| `POST` | `/api/reply_policies` | `save_reply_policies` | `backend/api.py:1633` |
| `POST` | `/api/restart` | `restart_bot` | `backend/api.py:1445` |
| `POST` | `/api/resume` | `resume_bot` | `backend/api.py:1438` |
| `POST` | `/api/send` | `send_message` | `backend/api.py:1591` |
| `POST` | `/api/start` | `start_bot` | `backend/api.py:1261` |
| `GET` | `/api/status` | `get_status` | `backend/api.py:1196` |
| `POST` | `/api/stop` | `stop_bot` | `backend/api.py:1268` |
| `POST` | `/api/test_connection` | `test_connection` | `backend/api.py:3083` |
| `GET` | `/api/usage` | `get_usage` | `backend/api.py:2497` |
| `GET` | `/api/v1/admin/prompts/<int:revision>/diff` | `diff_prompt_revision` | `backend/api.py:2869` |
| `POST` | `/api/v1/admin/prompts/<int:revision>/rollback` | `rollback_prompt_revision` | `backend/api.py:2884` |
| `GET` | `/api/v1/admin/prompts/revisions` | `list_prompt_revisions` | `backend/api.py:2858` |
| `POST` | `/api/v1/agents/tool-workflow` | `run_agent_tool_workflow` | `backend/api.py:3015` |
| `POST` | `/api/v1/mcp` | `run_readonly_mcp_adapter` | `backend/api.py:3069` |
| `POST` | `/api/wechat_export/apply` | `wechat_export_apply` | `backend/api.py:1411` |
| `POST` | `/api/wechat_export/apply/preview` | `wechat_export_preview_apply` | `backend/api.py:1394` |
| `POST` | `/api/wechat_export/contacts` | `wechat_export_contacts` | `backend/api.py:1362` |
| `GET` | `/api/wechat_export/decrypt/jobs/<job_id>` | `wechat_export_decrypt_job` | `backend/api.py:1349` |
| `POST` | `/api/wechat_export/decrypt/start` | `wechat_export_start_decrypt` | `backend/api.py:1335` |
| `POST` | `/api/wechat_export/export` | `wechat_export_run_export` | `backend/api.py:1378` |
| `POST` | `/api/wechat_export/probe` | `wechat_export_probe` | `backend/api.py:1324` |
