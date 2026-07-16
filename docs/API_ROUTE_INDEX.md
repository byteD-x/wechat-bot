# API Route Index

本文件由 `scripts/generate_api_route_index.py` 从 `backend/api.py` 的 `@app.route` 装饰器静态生成。
它只记录路由、方法、处理函数和源码行号，用于发现接口清单漂移；详细请求、响应和安全边界仍以 `docs/api.md` 为准。

生成命令：

```powershell
.\.venv\Scripts\python.exe scripts\generate_api_route_index.py
```

- Source: `backend/api.py`
- Route count: `65`

| Methods | Path | Handler | Source |
| --- | --- | --- | --- |
| `GET` | `/api/auth/providers` | `get_auth_providers_api` | `backend/api.py:2238` |
| `POST` | `/api/auth/providers/<provider_key>/cancel` | `cancel_auth_provider_flow` | `backend/api.py:2262` |
| `POST` | `/api/auth/providers/<provider_key>/logout_source` | `logout_auth_provider_source` | `backend/api.py:2293` |
| `POST` | `/api/auth/providers/<provider_key>/start` | `start_auth_provider_flow` | `backend/api.py:2247` |
| `POST` | `/api/auth/providers/<provider_key>/submit_callback` | `submit_auth_provider_callback` | `backend/api.py:2277` |
| `GET` | `/api/backups` | `list_backups` | `backend/api.py:1725` |
| `POST` | `/api/backups` | `create_backup` | `backend/api.py:1737` |
| `POST` | `/api/backups/cleanup` | `cleanup_backups` | `backend/api.py:1782` |
| `POST` | `/api/backups/restore` | `restore_backup` | `backend/api.py:1815` |
| `GET` | `/api/config` | `get_config` | `backend/api.py:2334` |
| `POST` | `/api/config` | `save_config` | `backend/api.py:2375` |
| `GET` | `/api/config/audit` | `get_config_audit` | `backend/api.py:2346` |
| `GET` | `/api/contact_profile` | `get_contact_profile` | `backend/api.py:1454` |
| `POST` | `/api/contact_prompt` | `save_contact_prompt` | `backend/api.py:1476` |
| `GET` | `/api/costs/review_queue_export` | `export_cost_review_queue` | `backend/api.py:2185` |
| `GET` | `/api/costs/session_details` | `get_cost_session_details` | `backend/api.py:2165` |
| `GET` | `/api/costs/sessions` | `get_cost_sessions` | `backend/api.py:2149` |
| `GET` | `/api/costs/summary` | `get_costs_summary` | `backend/api.py:2133` |
| `GET` | `/api/data_controls` | `get_data_controls` | `backend/api.py:2009` |
| `POST` | `/api/data_controls/clear` | `clear_data_controls` | `backend/api.py:2027` |
| `GET` | `/api/events` | `sse_events` | `backend/api.py:1198` |
| `GET` | `/api/events_ticket` | `get_events_ticket` | `backend/api.py:1213` |
| `POST` | `/api/growth/start` | `start_growth` | `backend/api.py:1235` |
| `POST` | `/api/growth/stop` | `stop_growth` | `backend/api.py:1242` |
| `GET` | `/api/growth/tasks` | `list_growth_tasks` | `backend/api.py:1249` |
| `POST` | `/api/growth/tasks/<task_type>/clear` | `clear_growth_task` | `backend/api.py:1256` |
| `POST` | `/api/growth/tasks/<task_type>/pause` | `pause_growth_task` | `backend/api.py:1270` |
| `POST` | `/api/growth/tasks/<task_type>/resume` | `resume_growth_task` | `backend/api.py:1277` |
| `POST` | `/api/growth/tasks/<task_type>/run` | `run_growth_task` | `backend/api.py:1263` |
| `GET` | `/api/logs` | `get_logs` | `backend/api.py:2564` |
| `POST` | `/api/logs/clear` | `clear_logs` | `backend/api.py:2608` |
| `POST` | `/api/message_feedback` | `save_message_feedback` | `backend/api.py:1508` |
| `GET` | `/api/messages` | `get_messages` | `backend/api.py:1419` |
| `GET` | `/api/metrics` | `get_metrics` | `backend/api.py:1184` |
| `POST` | `/api/model_auth/action` | `post_model_auth_action` | `backend/api.py:2223` |
| `GET` | `/api/model_auth/overview` | `get_model_auth_overview` | `backend/api.py:2214` |
| `GET` | `/api/model_catalog` | `get_model_catalog_api` | `backend/api.py:2204` |
| `GET` | `/api/ollama/models` | `get_ollama_models` | `backend/api.py:2308` |
| `POST` | `/api/pause` | `pause_bot` | `backend/api.py:1389` |
| `GET` | `/api/pending_replies` | `list_pending_replies` | `backend/api.py:1644` |
| `POST` | `/api/pending_replies/<int:pending_id>/approve` | `approve_pending_reply` | `backend/api.py:1674` |
| `POST` | `/api/pending_replies/<int:pending_id>/reject` | `reject_pending_reply` | `backend/api.py:1695` |
| `GET` | `/api/ping` | `ping` | `backend/api.py:1162` |
| `POST` | `/api/preview_prompt` | `preview_prompt` | `backend/api.py:2483` |
| `GET` | `/api/pricing` | `get_pricing` | `backend/api.py:2107` |
| `POST` | `/api/pricing/refresh` | `refresh_pricing` | `backend/api.py:2118` |
| `GET` | `/api/readiness` | `get_readiness` | `backend/api.py:1168` |
| `POST` | `/api/recover` | `recover_bot` | `backend/api.py:1412` |
| `GET` | `/api/reply_policies` | `get_reply_policies` | `backend/api.py:1572` |
| `POST` | `/api/reply_policies` | `save_reply_policies` | `backend/api.py:1593` |
| `POST` | `/api/restart` | `restart_bot` | `backend/api.py:1405` |
| `POST` | `/api/resume` | `resume_bot` | `backend/api.py:1398` |
| `POST` | `/api/send` | `send_message` | `backend/api.py:1551` |
| `POST` | `/api/start` | `start_bot` | `backend/api.py:1221` |
| `GET` | `/api/status` | `get_status` | `backend/api.py:1156` |
| `POST` | `/api/stop` | `stop_bot` | `backend/api.py:1228` |
| `POST` | `/api/test_connection` | `test_connection` | `backend/api.py:2457` |
| `GET` | `/api/usage` | `get_usage` | `backend/api.py:2096` |
| `POST` | `/api/wechat_export/apply` | `wechat_export_apply` | `backend/api.py:1371` |
| `POST` | `/api/wechat_export/apply/preview` | `wechat_export_preview_apply` | `backend/api.py:1354` |
| `POST` | `/api/wechat_export/contacts` | `wechat_export_contacts` | `backend/api.py:1322` |
| `GET` | `/api/wechat_export/decrypt/jobs/<job_id>` | `wechat_export_decrypt_job` | `backend/api.py:1309` |
| `POST` | `/api/wechat_export/decrypt/start` | `wechat_export_start_decrypt` | `backend/api.py:1295` |
| `POST` | `/api/wechat_export/export` | `wechat_export_run_export` | `backend/api.py:1338` |
| `POST` | `/api/wechat_export/probe` | `wechat_export_probe` | `backend/api.py:1284` |
