import pytest
import os
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

pytest.importorskip("quart")

# Import app
from backend.api import app
import backend.api as api_module
from backend.utils.config import compose_system_prompt_template


def _build_snapshot(config):
    snapshot = MagicMock()
    snapshot.config = config
    snapshot.api = config.get("api", {})
    snapshot.bot = config.get("bot", {})
    snapshot.logging = config.get("logging", {})
    snapshot.agent = config.get("agent", {})
    snapshot.services = config.get("services", {})
    snapshot.version = 1
    snapshot.loaded_at = datetime(2026, 3, 16, 17, 0, 0)
    snapshot.to_dict.return_value = config
    return snapshot

@pytest.fixture
def client():
    app.config['TESTING'] = True
    return app.test_client()

@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.get_status.return_value = {"running": True}
    manager.start = AsyncMock(return_value={"status": "started"})
    manager.stop = AsyncMock(return_value={"status": "stopped"})
    manager.pause = AsyncMock(return_value={"status": "paused"})
    manager.resume = AsyncMock(return_value={"status": "resumed"})
    manager.restart = AsyncMock(return_value={"status": "restarted"})
    manager.start_growth = AsyncMock(return_value={"success": True, "message": "成长任务已启动"})
    manager.stop_growth = AsyncMock(return_value={"success": True, "message": "成长任务已停止"})
    manager.reload_runtime_config = AsyncMock(return_value={"success": True, "message": "运行中的 AI 已立即切换到 DeepSeek", "runtime_preset": "DeepSeek"})
    manager.list_growth_tasks = AsyncMock(return_value={"success": True, "tasks": [{"task_type": "emotion", "queued": 2, "paused": False}]})
    manager.clear_growth_task = AsyncMock(return_value={"success": True, "task_type": "emotion", "cleared": 2})
    manager.run_growth_task_now = AsyncMock(return_value={"success": True, "task_type": "emotion", "result": {"completed": 2}})
    manager.pause_growth_task = AsyncMock(return_value={"success": True, "task_type": "emotion", "paused_growth_task_types": ["emotion"]})
    manager.resume_growth_task = AsyncMock(return_value={"success": True, "task_type": "emotion", "paused_growth_task_types": []})
    manager.is_running = True
    manager.bot = MagicMock()
    manager.memory_manager = None

    # Mock MemoryManager
    mem_mgr = MagicMock()
    async def async_get_message_page(*args, **kwargs):
        return {
            "messages": [],
            "total": 0,
            "limit": kwargs.get("limit", 50),
            "offset": kwargs.get("offset", 0),
            "has_more": False,
        }
    async def async_list_chat_summaries(*args, **kwargs):
        return []
    async def async_get_contact_profile(chat_id):
        return {
            "chat_id": chat_id,
            "profile_summary": "关系：普通朋友",
            "contact_prompt": "",
            "contact_prompt_source": "",
            "message_count": 0,
        }
    async def async_save_contact_prompt(chat_id, contact_prompt, *, source="user_edit", last_message_count=None):
        return {
            "chat_id": chat_id,
            "profile_summary": "关系：普通朋友",
            "contact_prompt": contact_prompt,
            "contact_prompt_source": source,
            "contact_prompt_last_message_count": int(last_message_count or 0),
        }
    async def async_update_message_feedback(message_id, feedback):
        return {
            "id": int(message_id),
            "role": "assistant",
            "feedback": feedback,
            "previous_feedback": "helpful",
            "metadata": {
                "reply_quality": {
                    "user_feedback": feedback,
                }
            },
        }
    async def async_get_profile_prompt_snapshot(chat_id):
        return {
            "wx_id": chat_id,
            "profile_summary": "关系：普通朋友",
            "contact_prompt": "数据库中的联系人 Prompt",
            "contact_prompt_source": "user_edit",
        }
    async def async_expire_pending_replies(*args, **kwargs):
        return 0
    async def async_get_pending_reply_stats():
        return {
            "total": 1,
            "pending": 1,
            "approved": 0,
            "rejected": 0,
            "expired": 0,
            "failed": 0,
            "latest_created_at": 1,
            "by_status": {"pending": 1},
        }
    async def async_list_pending_replies(*args, **kwargs):
        return [
            {
                "id": 7,
                "chat_id": kwargs.get("chat_id") or "friend:alice",
                "source_message_id": "m-1",
                "trigger_reason": "quiet_hours",
                "draft_reply": "晚上回复",
                "metadata": {"chat_id": kwargs.get("chat_id") or "friend:alice"},
                "status": kwargs.get("status") or "pending",
                "created_at": 1,
                "resolved_at": None,
            }
        ]
    async def async_get_pending_reply(pending_id):
        return {
            "id": int(pending_id),
            "chat_id": "friend:alice",
            "source_message_id": "m-1",
            "trigger_reason": "quiet_hours",
            "draft_reply": "晚上回复",
            "metadata": {"chat_id": "friend:alice"},
            "status": "pending",
            "created_at": 1,
            "resolved_at": None,
        }
    async def async_resolve_pending_reply(pending_id, status, draft_reply=None, metadata=None):
        return {
            "id": int(pending_id),
            "chat_id": "friend:alice",
            "source_message_id": "m-1",
            "trigger_reason": "quiet_hours",
            "draft_reply": draft_reply or "晚上回复",
            "metadata": metadata or {},
            "status": status,
            "created_at": 1,
            "resolved_at": 2,
        }
    mem_mgr.get_message_page = MagicMock(side_effect=async_get_message_page)
    mem_mgr.list_chat_summaries = MagicMock(side_effect=async_list_chat_summaries)
    mem_mgr.get_contact_profile = MagicMock(side_effect=async_get_contact_profile)
    mem_mgr.save_contact_prompt = MagicMock(side_effect=async_save_contact_prompt)
    mem_mgr.update_message_feedback = MagicMock(side_effect=async_update_message_feedback)
    mem_mgr.get_profile_prompt_snapshot = MagicMock(side_effect=async_get_profile_prompt_snapshot)
    mem_mgr.expire_pending_replies = AsyncMock(side_effect=async_expire_pending_replies)
    mem_mgr.get_pending_reply_stats = AsyncMock(side_effect=async_get_pending_reply_stats)
    mem_mgr.list_pending_replies = AsyncMock(side_effect=async_list_pending_replies)
    mem_mgr.get_pending_reply = AsyncMock(side_effect=async_get_pending_reply)
    mem_mgr.resolve_pending_reply = AsyncMock(side_effect=async_resolve_pending_reply)
    manager.get_memory_manager.return_value = mem_mgr
    manager.bot.approve_pending_reply = AsyncMock(return_value={"success": True, "pending_reply": {"id": 7, "status": "approved"}})
    manager.bot.reject_pending_reply = AsyncMock(return_value={"success": True, "pending_reply": {"id": 7, "status": "rejected"}})
    manager.bot.refresh_pending_reply_stats = AsyncMock(return_value={})
    
    # Replace the manager in the api module
    original_manager = api_module.manager
    api_module.manager = manager
    yield manager
    # Restore
    api_module.manager = original_manager


@pytest.fixture(autouse=True)
def reset_api_runtime_state():
    api_module._IDEMPOTENCY_CACHE.clear()
    api_module._IDEMPOTENCY_INFLIGHT.clear()
    api_module._API_METRICS_COUNTERS.clear()
    api_module._API_METRICS_DURATION_SUM_MS.clear()
    api_module._API_METRICS_DURATION_COUNT.clear()
    api_module._API_AUTH_FAILURE_COUNTERS.clear()
    api_module._API_METRIC_TRACKED_PATHS.clear()
    yield
    api_module._IDEMPOTENCY_CACHE.clear()
    api_module._IDEMPOTENCY_INFLIGHT.clear()
    api_module._API_METRICS_COUNTERS.clear()
    api_module._API_METRICS_DURATION_SUM_MS.clear()
    api_module._API_METRICS_DURATION_COUNT.clear()
    api_module._API_AUTH_FAILURE_COUNTERS.clear()
    api_module._API_METRIC_TRACKED_PATHS.clear()

@pytest.mark.asyncio
async def test_api_status(client, mock_manager):
    response = await client.get('/api/status')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()


@pytest.mark.asyncio
async def test_api_ping(client, mock_manager):
    response = await client.get('/api/ping')
    assert response.status_code == 200
    data = await response.get_json()
    assert data == {"success": True, "service_running": True}
    mock_manager.get_status.assert_not_called()


@pytest.mark.asyncio
async def test_api_rejects_cross_site_origin(client, mock_manager):
    response = await client.get('/api/status', headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "forbidden_origin"


@pytest.mark.asyncio
async def test_api_rejects_cross_site_without_origin_for_browser(client, mock_manager):
    response = await client.get(
        '/api/status',
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "forbidden_origin"


@pytest.mark.asyncio
async def test_api_allows_electron_cross_site_with_file_origin(client, mock_manager):
    response = await client.get(
        '/api/status',
        headers={
            "Origin": "null",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Electron/31.0.0",
        },
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()


@pytest.mark.asyncio
async def test_api_rejects_cross_site_with_file_triple_slash_origin_without_electron_ua(client, mock_manager):
    response = await client.get(
        '/api/status',
        headers={
            "Origin": "file:///E:/Project/wechat-chat/src/renderer/index.html",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36",
        },
    )
    assert response.status_code == 403
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "forbidden_origin"


@pytest.mark.asyncio
async def test_api_allows_cross_site_with_trusted_local_origin_even_without_electron_ua(client, mock_manager):
    response = await client.get(
        '/api/status',
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36",
        },
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()
    assert response.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:3000"


@pytest.mark.asyncio
async def test_api_allows_ipv6_loopback_host_and_origin(client, mock_manager):
    response = await client.get(
        '/api/status',
        headers={
            "Host": "[::1]:5000",
            "Origin": "http://[::1]:5173",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()


@pytest.mark.asyncio
async def test_api_accepts_authorization_bearer_token(client, mock_manager):
    with patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "unit-test-token"}, clear=False):
        response = await client.get(
            '/api/status',
            headers={"Authorization": "Bearer unit-test-token"},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()


@pytest.mark.asyncio
async def test_api_rejects_invalid_authorization_bearer_token(client, mock_manager):
    with patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "unit-test-token"}, clear=False):
        response = await client.get(
            '/api/status',
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 401
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "unauthorized"


@pytest.mark.asyncio
async def test_api_rejects_query_token_for_non_event_endpoints(client, mock_manager):
    with patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "unit-test-token"}, clear=False):
        response = await client.get("/api/status?token=unit-test-token")

    assert response.status_code == 401
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "unauthorized"


@pytest.mark.asyncio
async def test_api_events_ticket_requires_api_token(client, mock_manager):
    with patch.dict(
        os.environ,
        {
            "WECHAT_BOT_API_TOKEN": "unit-test-token",
            "WECHAT_BOT_SSE_TICKET": "sse-ticket-abc",
        },
        clear=False,
    ):
        response = await client.get("/api/events_ticket")
    assert response.status_code == 401
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "unauthorized"


@pytest.mark.asyncio
async def test_api_events_ticket_returns_ticket_when_authorized(client, mock_manager):
    with patch.dict(
        os.environ,
        {
            "WECHAT_BOT_API_TOKEN": "unit-test-token",
            "WECHAT_BOT_SSE_TICKET": "sse-ticket-abc",
        },
        clear=False,
    ):
        response = await client.get(
            "/api/events_ticket",
            headers={"X-Api-Token": "unit-test-token"},
        )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["ticket"] == "sse-ticket-abc"


@pytest.mark.asyncio
async def test_api_events_stream_rejects_missing_ticket_when_api_token_enabled(client, mock_manager):
    with patch.dict(
        os.environ,
        {
            "WECHAT_BOT_API_TOKEN": "unit-test-token",
            "WECHAT_BOT_SSE_TICKET": "sse-ticket-abc",
        },
        clear=False,
    ):
        response = await client.get("/api/events")
    assert response.status_code == 401
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "unauthorized"


@pytest.mark.asyncio
async def test_api_model_auth_overview_redacts_local_path_details(client, mock_manager):
    overview_payload = {
        "success": True,
        "overview": {
            "cards": [
                {
                    "provider": {"id": "demo"},
                    "auth_states": [
                        {
                            "binding": {
                                "locator_path": "C:/Users/demo/AppData/Local/demo/cookie.db",
                                "metadata": {
                                    "watch_paths": [
                                        "C:/Users/demo/AppData/Local/demo/cookie.db",
                                        "C:/Users/demo/AppData/Local/demo/storage.json",
                                    ],
                                    "cookie_path": "C:/Users/demo/AppData/Local/demo/cookie.db",
                                    "api_key_helper": "python helper.py --token super-secret",
                                },
                                "access_token": "abc123",
                            },
                        }
                    ],
                }
            ]
        },
    }

    with patch.object(api_module.model_auth_center_service, "get_overview", return_value=overview_payload):
        response = await client.get("/api/model_auth/overview")

    assert response.status_code == 200
    data = await response.get_json()
    binding = data["overview"]["cards"][0]["auth_states"][0]["binding"]
    assert binding["locator_path"] == ".../cookie.db"
    assert binding["metadata"]["watch_paths"] == []
    assert binding["metadata"]["cookie_path"] == ".../cookie.db"
    assert binding["metadata"]["api_key_helper"] == "[REDACTED]"
    assert binding["access_token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_api_404_under_api_prefix_returns_json_error(client, mock_manager):
    response = await client.get("/api/__missing_route__")

    assert response.status_code == 404
    assert "application/json" in (response.content_type or "")
    data = await response.get_json()
    assert data["success"] is False
    assert isinstance(data.get("message"), str)
    assert data["message"]


@pytest.mark.asyncio
async def test_api_405_under_api_prefix_returns_json_error(client, mock_manager):
    response = await client.get("/api/start")

    assert response.status_code == 405
    assert "application/json" in (response.content_type or "")
    data = await response.get_json()
    assert data["success"] is False
    assert isinstance(data.get("message"), str)
    assert data["message"]


@pytest.mark.asyncio
async def test_api_metrics_exports_request_and_auth_failure_counters(client, mock_manager):
    mock_manager.export_metrics.return_value = ""

    with patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "metrics-token"}, clear=False):
        ok_response = await client.get("/api/status", headers={"X-Api-Token": "metrics-token"})
        unauthorized_response = await client.get("/api/status")
        metrics_response = await client.get("/api/metrics", headers={"X-Api-Token": "metrics-token"})

    assert ok_response.status_code == 200
    assert unauthorized_response.status_code == 401
    assert metrics_response.status_code == 200
    body = (await metrics_response.get_data()).decode("utf-8")
    assert 'wechat_api_requests_total{method="GET",path="/api/status",status="200"} 1' in body
    assert 'wechat_api_requests_total{method="GET",path="/api/status",status="401"} 1' in body
    assert 'wechat_api_auth_failures_total{reason="unauthorized",path="/api/status"} 1' in body


def test_api_metric_path_cardinality_is_bounded():
    api_module._API_METRIC_TRACKED_PATHS.clear()
    for index in range(400):
        normalized = api_module._bound_metric_path(f"/api/random/{index}")
        if index < api_module._API_METRIC_MAX_PATH_CARDINALITY:
            assert normalized == f"/api/random/{index}"
        else:
            assert normalized == "/api/_other"
    assert len(api_module._API_METRIC_TRACKED_PATHS) == api_module._API_METRIC_MAX_PATH_CARDINALITY


@pytest.mark.asyncio
async def test_api_readiness(client, mock_manager):
    payload = {
        "success": True,
        "ready": False,
        "blocking_count": 2,
        "checks": [
            {
                "key": "admin_permission",
                "status": "failed",
                "blocking": True,
            }
        ],
        "suggested_actions": [
            {
                "action": "retry",
                "label": "重新检查",
                "source_check": "admin_permission",
            }
        ],
        "summary": {
            "title": "还有 2 项准备未完成",
            "detail": "请先处理阻塞项。",
        },
        "checked_at": 123.0,
    }

    with patch.object(api_module.readiness_service, "get_report", return_value=payload) as mock_get_report:
        response = await client.get('/api/readiness?refresh=true')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["blocking_count"] == 2
    assert data["summary"]["title"] == "还有 2 项准备未完成"
    mock_get_report.assert_called_once_with(force_refresh=True)


@pytest.mark.asyncio
async def test_api_test_connection_uses_patch(client, mock_manager):
    snapshot = _build_snapshot(
        {
            "api": {
                "active_preset": "OpenAI",
                "presets": [
                    {
                        "name": "OpenAI",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-test",
                        "model": "gpt-5-mini",
                    }
                ],
            },
            "bot": {},
            "logging": {},
            "agent": {},
            "services": {},
        }
    )

    with patch.object(api_module.config_service, "get_snapshot", return_value=snapshot), \
        patch.object(api_module.config_service, "_merge_patch", return_value={"api": {"active_preset": "Ollama"}, "bot": {}}), \
        patch.object(api_module.config_service, "_validate_config_dict", return_value={"api": {"active_preset": "Ollama"}, "bot": {}}), \
        patch.object(api_module, "probe_config", AsyncMock(return_value=(True, "Ollama", "连接测试成功（已验证服务可访问）"))) as probe_mock:
        response = await client.post(
            '/api/test_connection',
            json={"preset_name": "Ollama", "patch": {"api": {"active_preset": "Ollama"}}},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["preset_name"] == "Ollama"
    probe_mock.assert_awaited_once_with({"api": {"active_preset": "Ollama"}, "bot": {}}, "Ollama")

@pytest.mark.asyncio
async def test_api_start(client, mock_manager):
    response = await client.post('/api/start')
    assert response.status_code == 200
    mock_manager.start.assert_called_once()

@pytest.mark.asyncio
async def test_api_stop(client, mock_manager):
    response = await client.post('/api/stop')
    assert response.status_code == 200
    mock_manager.stop.assert_called_once()


@pytest.mark.asyncio
async def test_api_start_returns_409_when_manager_reports_failure(client, mock_manager):
    mock_manager.start = AsyncMock(return_value={"success": False, "message": "already_running"})
    response = await client.post('/api/start')
    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_api_stop_returns_409_when_manager_reports_failure(client, mock_manager):
    mock_manager.stop = AsyncMock(return_value={"success": False, "message": "not_running"})
    response = await client.post('/api/stop')
    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_api_start_growth(client, mock_manager):
    response = await client.post('/api/growth/start')
    assert response.status_code == 200
    mock_manager.start_growth.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_stop_growth(client, mock_manager):
    response = await client.post('/api/growth/stop')
    assert response.status_code == 200
    mock_manager.stop_growth.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_list_growth_tasks(client, mock_manager):
    response = await client.get('/api/growth/tasks')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["tasks"][0]["task_type"] == "emotion"
    mock_manager.list_growth_tasks.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_growth_task_actions(client, mock_manager):
    clear_response = await client.post('/api/growth/tasks/emotion/clear')
    run_response = await client.post('/api/growth/tasks/emotion/run')
    pause_response = await client.post('/api/growth/tasks/emotion/pause')
    resume_response = await client.post('/api/growth/tasks/emotion/resume')

    assert clear_response.status_code == 200
    assert run_response.status_code == 200
    assert pause_response.status_code == 200
    assert resume_response.status_code == 200

    mock_manager.clear_growth_task.assert_awaited_once_with('emotion')
    mock_manager.run_growth_task_now.assert_awaited_once_with('emotion')
    mock_manager.pause_growth_task.assert_awaited_once_with('emotion')
    mock_manager.resume_growth_task.assert_awaited_once_with('emotion')

@pytest.mark.asyncio
async def test_api_messages(client, mock_manager):
    response = await client.get('/api/messages?limit=10')
    assert response.status_code == 200
    mock_manager.get_memory_manager.assert_called()
    mock_manager.get_memory_manager().get_message_page.assert_called_with(
        limit=10,
        offset=0,
        chat_id='',
        keyword='',
    )
    mock_manager.get_memory_manager().list_chat_summaries.assert_called_once()


@pytest.mark.asyncio
async def test_api_messages_preserves_display_name_fields(client, mock_manager):
    async def _get_message_page(**kwargs):
        return {
            "messages": [
                {
                    "id": 1,
                    "wx_id": "friend:alice",
                    "role": "user",
                    "content": "hello",
                    "timestamp": 1,
                    "sender": "Alice",
                    "sender_display_name": "Alice",
                    "display_name": "Alice",
                    "chat_display_name": "Alice",
                    "is_self": False,
                    "relationship": "friend",
                    "metadata": {},
                }
            ],
            "total": 1,
            "limit": kwargs.get("limit", 50),
            "offset": kwargs.get("offset", 0),
            "has_more": False,
        }

    mock_manager.get_memory_manager().get_message_page = MagicMock(side_effect=_get_message_page)

    response = await client.get('/api/messages?limit=10')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["messages"][0]["display_name"] == "Alice"
    assert data["messages"][0]["chat_display_name"] == "Alice"


@pytest.mark.asyncio
async def test_api_contact_profile(client, mock_manager):
    response = await client.get('/api/contact_profile?chat_id=friend:alice')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["profile"]["chat_id"] == "friend:alice"
    mock_manager.get_memory_manager().get_contact_profile.assert_called_once_with("friend:alice")


@pytest.mark.asyncio
async def test_api_contact_prompt_save(client, mock_manager):
    raw_prompt = compose_system_prompt_template("新的联系人 Prompt")
    response = await client.post(
        '/api/contact_prompt',
        json={"chat_id": "friend:alice", "contact_prompt": raw_prompt},
    )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["profile"]["contact_prompt"] == "新的联系人 Prompt"
    mock_manager.get_memory_manager().save_contact_prompt.assert_called_once_with(
        "friend:alice",
        "新的联系人 Prompt",
        source="user_edit",
    )

@pytest.mark.asyncio
async def test_api_send(client, mock_manager):
    mock_manager.send_message = AsyncMock(return_value={"success": True})
    response = await client.post('/api/send', json={"target": "User", "content": "Hello"})
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    mock_manager.send_message.assert_called_with("User", "Hello")


@pytest.mark.asyncio
async def test_api_send_rejects_overlong_target(client, mock_manager):
    response = await client.post('/api/send', json={"target": "U" * 257, "content": "Hello"})
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "target is too long"


@pytest.mark.asyncio
async def test_api_send_rejects_overlong_content(client, mock_manager):
    response = await client.post('/api/send', json={"target": "User", "content": "x" * 8001})
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "content is too long"


@pytest.mark.asyncio
async def test_api_send_requires_idempotency_key_when_not_testing(client, mock_manager):
    previous_testing = bool(api_module.app.config.get("TESTING"))
    api_module.app.config["TESTING"] = False
    try:
        with (
            patch("backend.api._is_local_request", return_value=True),
            patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "unit-test-token"}, clear=False),
        ):
            response = await client.post(
                '/api/send',
                json={"target": "User", "content": "Hello"},
                headers={"X-Api-Token": "unit-test-token"},
            )
    finally:
        api_module.app.config["TESTING"] = previous_testing

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "idempotency_key_required"
    mock_manager.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_api_rejects_all_api_requests_when_token_is_missing_in_non_testing_mode(client, mock_manager):
    previous_testing = bool(api_module.app.config.get("TESTING"))
    api_module.app.config["TESTING"] = False
    try:
        with (
            patch("backend.api._is_local_request", return_value=True),
            patch.dict(os.environ, {"WECHAT_BOT_API_TOKEN": "", "WECHAT_BOT_SSE_TICKET": ""}, clear=False),
        ):
            response = await client.get('/api/status')
    finally:
        api_module.app.config["TESTING"] = previous_testing

    assert response.status_code == 503
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "api_token_not_configured"
    mock_manager.get_status.assert_not_called()


@pytest.mark.asyncio
async def test_api_send_replays_idempotent_response(client, mock_manager):
    mock_manager.send_message = AsyncMock(return_value={"success": True, "message_id": "msg-1"})
    headers = {"Idempotency-Key": "send-idem-1"}

    first = await client.post('/api/send', json={"target": "User", "content": "Hello"}, headers=headers)
    second = await client.post('/api/send', json={"target": "User", "content": "Hello"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    second_data = await second.get_json()
    assert second_data["success"] is True
    assert second.headers.get("X-Idempotency-Replayed") == "1"
    mock_manager.send_message.assert_awaited_once_with("User", "Hello")


@pytest.mark.asyncio
async def test_api_send_rejects_idempotency_key_reuse_with_different_payload(client, mock_manager):
    mock_manager.send_message = AsyncMock(return_value={"success": True, "message_id": "msg-1"})
    headers = {"Idempotency-Key": "send-idem-conflict"}

    first = await client.post('/api/send', json={"target": "User", "content": "Hello"}, headers=headers)
    second = await client.post('/api/send', json={"target": "User", "content": "Changed"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 400
    data = await second.get_json()
    assert data["success"] is False
    assert "idempotency key was reused" in data["message"]
    mock_manager.send_message.assert_awaited_once_with("User", "Hello")


@pytest.mark.asyncio
async def test_api_send_rejects_when_same_idempotency_key_request_is_stuck_inflight(client, mock_manager):
    mock_manager.send_message = AsyncMock(return_value={"success": True, "message_id": "msg-1"})
    headers = {"Idempotency-Key": "send-idem-stuck"}
    with patch("backend.api._apply_idempotency_guard", AsyncMock(side_effect=RuntimeError("idempotency request is still in progress"))):
        response = await client.post('/api/send', json={"target": "User", "content": "Hello"}, headers=headers)

    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "idempotency request is still in progress"
    mock_manager.send_message.assert_not_awaited()

@pytest.mark.asyncio
async def test_api_usage(client, mock_manager):
    mock_manager.get_usage.return_value = {"total_tokens": 100}
    response = await client.get('/api/usage')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["stats"]["total_tokens"] == 100


@pytest.mark.asyncio
async def test_api_message_feedback(client, mock_manager):
    mock_manager.bot.reply_quality_tracker = MagicMock()
    mock_manager.bot.apply_reply_feedback_change = MagicMock()

    response = await client.post('/api/message_feedback', json={"message_id": 12, "feedback": "unhelpful"})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["feedback"] == "unhelpful"
    mock_manager.get_memory_manager.return_value.update_message_feedback.assert_called_once_with(12, "unhelpful")
    mock_manager.bot.reply_quality_tracker.log_feedback.assert_called_once_with(
        message_id=12,
        feedback="unhelpful",
    )
    mock_manager.bot.apply_reply_feedback_change.assert_called_once_with("helpful", "unhelpful")


@pytest.mark.asyncio
async def test_api_message_feedback_rejects_non_assistant_message(client, mock_manager):
    async def _update_message_feedback(_message_id, feedback):
        return {
            "id": 1,
            "role": "user",
            "feedback": feedback,
            "previous_feedback": "",
            "metadata": {},
        }

    mock_manager.get_memory_manager.return_value.update_message_feedback = MagicMock(side_effect=_update_message_feedback)

    response = await client.post('/api/message_feedback', json={"message_id": 1, "feedback": "helpful"})

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_api_pricing(client):
    snapshot = {
        "version": "2026-03-17",
        "providers": {
            "openai": {
                "label": "OpenAI",
            }
        },
        "updated_at": "2026-03-17T00:00:00+00:00",
    }

    with patch.object(api_module.cost_service, "get_pricing_snapshot", AsyncMock(return_value=snapshot)):
        response = await client.get('/api/pricing')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["version"] == "2026-03-17"
    assert "openai" in data["providers"]


@pytest.mark.asyncio
async def test_api_pricing_refresh(client):
    payload = {
        "success": True,
        "results": {
            "deepseek": {"success": True, "models": 2},
        },
        "updated_at": "2026-03-17T08:00:00+00:00",
    }

    refresh_mock = AsyncMock(return_value=payload)
    with patch.object(api_module.cost_service, "refresh_pricing", refresh_mock):
        response = await client.post('/api/pricing/refresh', json={"providers": ["deepseek"]})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["results"]["deepseek"]["models"] == 2
    refresh_mock.assert_awaited_once_with(providers=["deepseek"])


@pytest.mark.asyncio
async def test_api_costs_summary(client, mock_manager):
    summary_payload = {
        "success": True,
        "filters": {"period": "30d", "preset": "default"},
        "overview": {
            "reply_count": 2,
            "total_tokens": 300,
            "currency_groups": [{"currency": "USD", "total_cost": 0.12}],
        },
        "models": [
            {"provider_id": "openai", "model": "gpt-5-mini", "total_tokens": 300},
        ],
        "options": {"providers": ["openai"], "models": ["gpt-5-mini"], "presets": ["default"]},
        "review_queue": [
            {"id": 1, "chat_id": "friend:alice", "reply_preview": "需要复盘"},
        ],
    }
    config_snapshot = _build_snapshot({"api": {"presets": []}, "bot": {}, "logging": {}})

    with (
        patch.object(api_module.cost_service, "get_summary", AsyncMock(return_value=summary_payload)) as get_summary_mock,
        patch.object(api_module.config_service, "get_snapshot", return_value=config_snapshot),
    ):
        response = await client.get('/api/costs/summary?period=30d&preset=default&include_estimated=true')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["overview"]["total_tokens"] == 300
    assert data["review_queue"][0]["chat_id"] == "friend:alice"
    get_summary_mock.assert_awaited_once()
    assert get_summary_mock.await_args.kwargs["preset"] == "default"


@pytest.mark.asyncio
async def test_api_costs_sessions(client, mock_manager):
    sessions_payload = {
        "success": True,
        "filters": {"period": "today"},
        "total": 1,
        "sessions": [
            {
                "chat_id": "friend:alice",
                "display_name": "Alice",
                "reply_count": 3,
                "currency_groups": [{"currency": "USD", "total_cost": 0.08}],
            }
        ],
    }
    config_snapshot = _build_snapshot({"api": {"presets": []}, "bot": {}, "logging": {}})

    with (
        patch.object(api_module.cost_service, "get_sessions", AsyncMock(return_value=sessions_payload)) as get_sessions_mock,
        patch.object(api_module.config_service, "get_snapshot", return_value=config_snapshot),
    ):
        response = await client.get('/api/costs/sessions?period=today')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["sessions"][0]["chat_id"] == "friend:alice"
    get_sessions_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_costs_session_details(client, mock_manager):
    details_payload = {
        "success": True,
        "chat_id": "friend:alice",
        "total": 1,
        "records": [
            {
                "id": 1,
                "model": "gpt-5-mini",
                "provider_id": "openai",
                "pricing_available": True,
            }
        ],
    }
    config_snapshot = _build_snapshot({"api": {"presets": []}, "bot": {}, "logging": {}})

    with (
        patch.object(api_module.cost_service, "get_session_details", AsyncMock(return_value=details_payload)) as details_mock,
        patch.object(api_module.config_service, "get_snapshot", return_value=config_snapshot),
    ):
        response = await client.get('/api/costs/session_details?chat_id=friend:alice&period=7d')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["records"][0]["model"] == "gpt-5-mini"
    details_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_costs_session_details_requires_chat_id(client):
    response = await client.get('/api/costs/session_details')
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_api_costs_review_queue_export(client, mock_manager):
    export_payload = {
        "success": True,
        "filters": {"period": "7d", "preset": "default", "review_reason": "retrieval_weak", "suggested_action": "tune_retrieval_threshold"},
        "total": 1,
        "items": [
            {
                "id": 2,
                "chat_id": "friend:alice",
                "preset": "default",
                "review_reason": "retrieval_weak",
                "suggested_action": "tune_retrieval_threshold",
                "reply_text": "需要复盘的完整回复",
            }
        ],
    }
    config_snapshot = _build_snapshot({"api": {"presets": []}, "bot": {}, "logging": {}})

    with (
        patch.object(api_module.cost_service, "export_review_queue", AsyncMock(return_value=export_payload)) as export_mock,
        patch.object(api_module.config_service, "get_snapshot", return_value=config_snapshot),
    ):
        response = await client.get('/api/costs/review_queue_export?period=7d&preset=default&review_reason=retrieval_weak&suggested_action=tune_retrieval_threshold')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["items"][0]["preset"] == "default"
    assert data["items"][0]["review_reason"] == "retrieval_weak"
    assert data["items"][0]["suggested_action"] == "tune_retrieval_threshold"
    export_mock.assert_awaited_once()
    assert export_mock.await_args.kwargs["preset"] == "default"
    assert export_mock.await_args.kwargs["review_reason"] == "retrieval_weak"
    assert export_mock.await_args.kwargs["suggested_action"] == "tune_retrieval_threshold"


@pytest.mark.asyncio
async def test_api_costs_review_queue_export_error_is_sanitized(client, mock_manager):
    config_snapshot = _build_snapshot({"api": {"presets": []}, "bot": {}, "logging": {}})

    with (
        patch.object(
            api_module.cost_service,
            "export_review_queue",
            AsyncMock(side_effect=RuntimeError("sensitive-export-error")),
        ),
        patch.object(api_module.config_service, "get_snapshot", return_value=config_snapshot),
    ):
        response = await client.get("/api/costs/review_queue_export?period=7d")

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "export_cost_review_queue_failed"
    assert data["code"] == "export_cost_review_queue_failed"
    assert "sensitive-export-error" not in str(data)


@pytest.mark.asyncio
async def test_api_messages_error(client, mock_manager):
    mock_manager.get_memory_manager().get_message_page.side_effect = Exception("DB Error")
    response = await client.get('/api/messages?limit=10')
    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert "DB Error" in data["message"]

@pytest.mark.asyncio
async def test_api_send_error(client, mock_manager):
    mock_manager.send_message.side_effect = Exception("Send Error")
    response = await client.post('/api/send', json={"target": "User", "content": "Hello"})
    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "send_failed"
    assert data["code"] == "send_failed"

@pytest.mark.asyncio
async def test_api_usage_error(client, mock_manager):
    mock_manager.get_usage.side_effect = Exception("Usage Error")
    response = await client.get('/api/usage')
    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "get_usage_failed"
    assert data["code"] == "get_usage_failed"


@pytest.mark.asyncio
async def test_api_model_catalog(client):
    response = await client.get('/api/model_catalog')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    providers = {provider["id"]: provider for provider in data["providers"]}

    qwen = providers.get("qwen")
    assert qwen is not None
    assert "qwen3.5-plus" in qwen["models"]
    assert "qwen3-coder-next" in qwen["models"]

    google = providers.get("google")
    assert google is not None
    assert google["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert "gemini-3.1-pro-preview" in google["models"]

    doubao = providers.get("doubao")
    assert doubao is not None
    assert doubao["default_model"] == "doubao-seed-1.8"
    assert "doubao-seed-2.0-pro" in doubao["models"]

    openai = providers.get("openai")
    assert openai is not None
    assert openai["default_model"] == "gpt-5.4-mini"
    assert "gpt-5.4-pro" in openai["models"]
    assert "gpt-5.4" in openai["models"]
    assert "gpt-5.3-codex" in openai["models"]
    auth_methods = {item["id"]: item["type"] for item in openai.get("auth_methods", [])}
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["codex_local"] == "local_import"

    assert providers["zhipu"]["default_model"] == "glm-5"
    assert "glm-4.7" in providers["zhipu"]["models"]
    assert providers["openrouter"]["default_model"] == "openrouter/auto"
    assert "google/gemini-3.1-pro-preview" in providers["openrouter"]["models"]
    assert providers["together"]["default_model"] == "moonshotai/Kimi-K2.5"
    assert providers["perplexity"]["models"] == ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]


@pytest.mark.asyncio
async def test_api_auth_providers_status(client):
    payload = {
        "success": True,
        "providers": {
            "openai_codex": {
                "configured": True,
                "detected": True,
                "message": "local auth detected",
            }
        },
        "supported_provider_ids": ["openai_codex"],
    }

    with patch.object(api_module, "get_oauth_provider_statuses", return_value=payload):
        response = await client.get("/api/auth/providers")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["providers"]["openai_codex"]["configured"] is True


@pytest.mark.asyncio
async def test_api_auth_flow_routes(client):
    oauth_payload = {
        "success": True,
        "providers": {
            "openai_codex": {
                "configured": True,
                "detected": True,
                "message": "ready",
            }
        },
        "supported_provider_ids": ["openai_codex"],
    }

    with patch.object(api_module, "launch_oauth_login", return_value={"success": True, "flow_id": "flow-1"}) as start_mock, \
        patch.object(api_module, "submit_auth_callback", return_value={"success": True, "completed": True}) as submit_mock, \
        patch.object(api_module, "logout_oauth_provider", return_value={"success": True, "message": "logged out"}) as logout_mock, \
        patch.object(api_module, "get_oauth_provider_statuses", return_value=oauth_payload):
        start_response = await client.post(
            "/api/auth/providers/openai_codex/start",
            json={"settings": {"name": "OpenAI", "auth_mode": "oauth"}},
        )
        submit_response = await client.post(
            "/api/auth/providers/openai_codex/submit_callback",
            json={"flow_id": "flow-1", "payload": {"code": "abc"}},
        )
        logout_response = await client.post(
            "/api/auth/providers/openai_codex/logout_source",
            json={"settings": {"name": "OpenAI", "auth_mode": "oauth"}},
        )

    assert start_response.status_code == 200
    assert submit_response.status_code == 200
    assert logout_response.status_code == 200

    start_data = await start_response.get_json()
    submit_data = await submit_response.get_json()
    logout_data = await logout_response.get_json()

    assert start_data["flow_id"] == "flow-1"
    assert start_data["oauth"]["providers"]["openai_codex"]["configured"] is True
    assert submit_data["completed"] is True
    assert logout_data["message"] == "logged out"

    start_mock.assert_called_once()
    submit_mock.assert_called_once_with("openai_codex", "flow-1", {"code": "abc"})
    logout_mock.assert_called_once()


@pytest.mark.asyncio
async def test_api_config_masks_key_and_infers_provider(client):
    test_config = {
        "api": {
            "presets": [
                {
                    "name": "Qwen",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "demo-openai-key-123456",
                    "model": "qwen3.5-plus",
                    "alias": "小千",
                    "timeout_sec": 10,
                    "max_retries": 2,
                    "temperature": 0.6,
                    "max_tokens": 512,
                    "allow_empty_key": False,
                }
            ]
        },
        "bot": {},
        "logging": {},
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)):
        response = await client.get('/api/config')

    assert response.status_code == 200
    data = await response.get_json()
    preset = data["api"]["presets"][0]
    assert preset["provider_id"] == "qwen"
    assert preset["api_key_configured"] is True
    assert "api_key" not in preset


@pytest.mark.asyncio
async def test_api_config_marks_ollama_as_no_key_required(client):
    test_config = {
        "api": {
            "presets": [
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "",
                    "model": "qwen3",
                    "alias": "本地",
                    "timeout_sec": 20,
                    "max_retries": 1,
                    "temperature": 0.6,
                    "max_tokens": 512,
                    "allow_empty_key": True,
                }
            ]
        },
        "bot": {},
        "logging": {},
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)):
        response = await client.get('/api/config')

    data = await response.get_json()
    preset = data["api"]["presets"][0]
    assert preset["provider_id"] == "ollama"
    assert preset["api_key_required"] is False
    assert preset["api_key_configured"] is False


@pytest.mark.asyncio
async def test_api_config_masks_langsmith_key(client):
    test_config = {
        "api": {"presets": []},
        "bot": {},
        "logging": {},
        "agent": {
            "enabled": True,
            "langsmith_enabled": True,
            "langsmith_project": "wechat-chat",
            "langsmith_api_key": "lsv2_pt_secret_key",
        },
        "services": {"growth_tasks_enabled": True},
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)):
        response = await client.get("/api/config")

    data = await response.get_json()
    assert data["agent"]["langsmith_enabled"] is True
    assert data["agent"]["langsmith_api_key_configured"] is True
    assert "langsmith_api_key" not in data["agent"]
    assert data["services"]["growth_tasks_enabled"] is True


@pytest.mark.asyncio
async def test_api_config_uses_cached_oauth_status_snapshot(client):
    test_config = {
        "api": {
            "active_preset": "OpenAI",
            "presets": [
                {
                    "name": "OpenAI",
                    "provider_id": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "demo-openai-test-key",
                    "auth_mode": "oauth",
                    "oauth_provider": "openai_codex",
                    "model": "gpt-5.4-mini",
                }
            ],
        },
        "bot": {},
        "logging": {},
        "agent": {},
        "services": {},
    }
    oauth_payload = {
        "success": True,
        "providers": {
            "openai_codex": {
                "configured": True,
                "detected": True,
                "message": "cached local auth detected",
            }
        },
        "supported_provider_ids": ["openai_codex"],
        "refreshed_at": 1234567890,
        "revision": 7,
        "changed_provider_ids": ["openai_codex"],
        "refreshing": True,
        "message": "cached local auth detected",
    }
    captured = {}

    def _fake_auth_summary(settings, *, provider_statuses=None):
        captured["provider_statuses"] = provider_statuses
        return {
            "oauth_supported": True,
            "oauth_ready": True,
            "api_key_ready": True,
            "auth_ready": True,
            "oauth_status": {"configured": True},
            "oauth_source": "openai_codex",
            "oauth_bound": True,
            "oauth_missing_fields": [],
            "oauth_detected_local": True,
            "oauth_experimental": False,
            "oauth_requires_ack": False,
            "oauth_experimental_ack": False,
            "auth_status_summary": "ready",
            "card_state": "active" if settings.get("_is_active") else "oauth_ready",
            "card_rank": 0,
            "card_group": "featured",
        }

    with (
        patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)),
        patch.object(api_module, "get_cached_oauth_provider_statuses", return_value=oauth_payload) as cached_mock,
        patch.object(api_module, "get_preset_auth_summary", side_effect=_fake_auth_summary),
        patch.object(
            api_module,
            "get_oauth_provider_statuses",
            side_effect=AssertionError("live oauth scan should not run for /api/config"),
        ),
    ):
        response = await client.get("/api/config")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["oauth"] == oauth_payload
    assert data["local_auth_sync"] == {
        "refreshing": True,
        "refreshed_at": 1234567890,
        "revision": 7,
        "changed_provider_ids": ["openai_codex"],
        "message": "cached local auth detected",
    }
    assert captured["provider_statuses"] == oauth_payload["providers"]
    cached_mock.assert_called_once_with()


@pytest.mark.asyncio
async def test_api_config_sanitizes_oauth_sensitive_paths(client):
    test_config = {
        "api": {"active_preset": "OpenAI", "presets": []},
        "bot": {},
        "logging": {},
        "agent": {},
        "services": {},
    }
    oauth_payload = {
        "success": True,
        "providers": {
            "openai_codex": {
                "configured": True,
                "session_path": "C:/Users/demo/AppData/Roaming/auth/session.json",
                "message": "ready",
            }
        },
        "message": "ok",
    }

    with (
        patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)),
        patch.object(api_module, "get_cached_oauth_provider_statuses", return_value=oauth_payload),
    ):
        response = await client.get("/api/config")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["oauth"]["providers"]["openai_codex"]["configured"] is True
    assert data["oauth"]["providers"]["openai_codex"]["session_path"] == ".../session.json"


@pytest.mark.asyncio
async def test_api_config_does_not_expose_removed_reply_or_stream_fields(client):
    test_config = {
        "api": {"presets": []},
        "bot": {
            "reply_deadline_sec": 2.0,
            "stream_reply": True,
            "stream_buffer_chars": 30,
            "stream_chunk_max_chars": 200,
            "reply_timeout_fallback_text": "timeout fallback",
        },
        "logging": {},
        "agent": {
            "enabled": True,
            "streaming_enabled": True,
        },
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)):
        response = await client.get("/api/config")

    data = await response.get_json()
    assert "stream_reply" not in data["bot"]
    assert "stream_buffer_chars" not in data["bot"]
    assert "stream_chunk_max_chars" not in data["bot"]
    assert "reply_timeout_fallback_text" not in data["bot"]
    assert "streaming_enabled" not in data["agent"]


@pytest.mark.asyncio
async def test_api_config_audit_reports_unknown_override_paths(client):
    test_config = {
        "api": {"presets": []},
        "bot": {
            "filter_mute": True,
            "profile_update_frequency": 10,
        },
        "logging": {},
        "agent": {},
    }

    with (
        patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(test_config)),
        patch("backend.api.build_config_audit", return_value={"dormant_paths": [], "unknown_override_paths": ["bot.memory_seed_limit"]}),
    ):
        response = await client.get("/api/config/audit")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert "bot.memory_seed_limit" in data["audit"]["unknown_override_paths"]


@pytest.mark.asyncio
async def test_api_ollama_models(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "models": [
            {"name": "qwen3:8b"},
            {"model": "llama3.1:8b"},
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch("backend.api.httpx.get", return_value=mock_response) as mock_get:
        response = await client.get('/api/ollama/models?base_url=http://127.0.0.1:11434/v1')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["models"] == ["qwen3:8b", "llama3.1:8b"]
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_api_ollama_models_rejects_non_local_base_url(client):
    with patch("backend.api.httpx.get") as mock_get:
        response = await client.get("/api/ollama/models?base_url=http://example.com")

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "localhost" in data["message"]
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_api_ollama_models_failure_is_sanitized(client):
    with patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("ollama-secret"))):
        response = await client.get("/api/ollama/models?base_url=http://127.0.0.1:11434/v1")

    assert response.status_code == 502
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "fetch_ollama_models_failed"
    assert data["code"] == "fetch_ollama_models_failed"
    assert data["models"] == []
    assert "ollama-secret" not in str(data)


@pytest.mark.asyncio
async def test_api_logs_rejects_log_file_outside_data_root(client):
    snapshot = _build_snapshot(
        {
            "api": {"presets": []},
            "bot": {},
            "logging": {"file": "C:/Windows/system32/drivers/etc/hosts"},
        }
    )
    with patch.object(api_module.config_service, "get_snapshot", return_value=snapshot):
        response = await client.get("/api/logs")

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "data directory" in data["message"]


@pytest.mark.asyncio
async def test_api_preview_prompt_applies_overrides_and_injections(client):
    preview_config = {
        "bot": {
            "system_prompt": "基础提示",
            "system_prompt_overrides": {
                "项目群": "群聊专用提示"
            },
            "profile_inject_in_prompt": True,
            "emotion_inject_in_prompt": True,
        }
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(preview_config)):
        response = await client.post('/api/preview_prompt', json={
            "sample": {
                "chat_name": "项目群",
                "sender": "小李",
                "relationship": "teammate",
                "emotion": "excited",
                "message": "今晚发版吗？",
                "is_group": True,
            }
        })

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert "群聊专用提示" in data["prompt"]
    assert "# 用户画像" in data["prompt"]
    assert "relationship: teammate" in data["prompt"]
    assert "# 当前情境" in data["prompt"]
    assert "excited" in data["prompt"]
    assert data["summary"]["override_applied"] is True
    assert data["summary"]["profile_injected"] is True
    assert data["summary"]["emotion_injected"] is True


@pytest.mark.asyncio
async def test_api_preview_prompt_uses_contact_prompt_when_chat_id_is_provided(client, mock_manager):
    preview_config = {
        "bot": {
            "system_prompt": "基础提示",
            "system_prompt_overrides": {
                "Alice": "覆盖提示"
            },
            "profile_inject_in_prompt": True,
            "emotion_inject_in_prompt": False,
        }
    }

    with patch.object(api_module.config_service, "get_snapshot", return_value=_build_snapshot(preview_config)):
        response = await client.post('/api/preview_prompt', json={
            "sample": {
                "chat_id": "friend:alice",
                "chat_name": "Alice",
                "sender": "Alice",
                "message": "你好",
            }
        })

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert "数据库中的联系人 Prompt" in data["prompt"]
    assert data["summary"]["contact_prompt_applied"] is True


@pytest.mark.asyncio
async def test_api_save_config_triggers_runtime_reload(client, mock_manager):
    test_config = {
        "api": {
            "active_preset": "OpenAI",
            "presets": [
                {
                    "name": "OpenAI",
                    "provider_id": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "demo-openai-test-key",
                    "model": "gpt-5-mini",
                    "alias": "小欧",
                    "allow_empty_key": False,
                },
                {
                    "name": "DeepSeek",
                    "provider_id": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "demo-deepseek-test-key",
                    "model": "deepseek-chat",
                    "alias": "小深",
                    "allow_empty_key": False,
                },
            ],
        },
        "bot": {},
        "logging": {},
    }

    snapshot = _build_snapshot(test_config)

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async_to_thread = AsyncMock(side_effect=_fake_to_thread)
    save_effective_config = MagicMock(return_value=snapshot)
    with (
        patch("backend.api.asyncio.to_thread", async_to_thread),
        patch.object(api_module.config_service, "get_snapshot", return_value=snapshot),
        patch.object(api_module.config_service, "save_effective_config", save_effective_config),
    ):
        response = await client.post("/api/config", json={"api": {"active_preset": "DeepSeek"}})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["config"]["api"]["active_preset"] == "OpenAI"
    assert data["changed_paths"] == []
    assert isinstance(data["reload_plan"], list)
    assert data["runtime_apply"]["success"] is True
    assert data["default_config_synced"] is True
    mock_manager.reload_runtime_config.assert_awaited_once()
    save_effective_config.assert_called_once()


@pytest.mark.asyncio
async def test_api_save_config_forces_ai_reload_for_agent_changes(client, mock_manager):
    current_config = {
        "api": {
            "active_preset": "OpenAI",
            "presets": [],
        },
        "bot": {},
        "logging": {},
        "agent": {
            "enabled": True,
            "langsmith_enabled": False,
        },
    }
    updated_config = {
        "api": {
            "active_preset": "OpenAI",
            "presets": [],
        },
        "bot": {},
        "logging": {},
        "agent": {
            "enabled": True,
            "langsmith_enabled": True,
        },
    }

    current_snapshot = _build_snapshot(current_config)
    updated_snapshot = _build_snapshot(updated_config)

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(api_module.config_service, "get_snapshot", return_value=current_snapshot),
        patch.object(api_module.config_service, "save_effective_config", return_value=updated_snapshot),
    ):
        response = await client.post("/api/config", json={"agent": {"langsmith_enabled": True}})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert "agent.langsmith_enabled" in data["changed_paths"]
    mock_manager.reload_runtime_config.assert_awaited()
    _, kwargs = mock_manager.reload_runtime_config.await_args
    assert kwargs["force_ai_reload"] is True
    assert "agent.langsmith_enabled" in kwargs["changed_paths"]


@pytest.mark.asyncio
async def test_api_reply_policies_get(client, mock_manager):
    snapshot = _build_snapshot(
        {
            "api": {"presets": []},
            "bot": {
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "manual",
                    "group_mode": "whitelist_only",
                    "quiet_hours": {"start": "00:00", "end": "07:30", "mode": "manual"},
                    "sensitive_keywords": ["contract"],
                    "per_chat_overrides": [],
                    "pending_ttl_hours": 24,
                }
            },
            "logging": {},
            "agent": {},
            "services": {},
        }
    )

    with patch.object(api_module.config_service, "get_snapshot", return_value=snapshot):
        response = await client.get("/api/reply_policies")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["reply_policy"]["new_contact_mode"] == "manual"
    assert data["pending_stats"]["pending"] == 1
    mock_manager.get_memory_manager().expire_pending_replies.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_reply_policies_post_supports_chat_override(client, mock_manager):
    current_config = {
        "api": {"presets": []},
        "bot": {
            "reply_policy": {
                "default_mode": "auto",
                "new_contact_mode": "manual",
                "group_mode": "whitelist_only",
                "quiet_hours": {"start": "00:00", "end": "07:30", "mode": "manual"},
                "sensitive_keywords": [],
                "per_chat_overrides": [],
                "pending_ttl_hours": 24,
            }
        },
        "logging": {},
        "agent": {},
        "services": {},
    }
    updated_config = {
        **current_config,
        "bot": {
            "reply_policy": {
                **current_config["bot"]["reply_policy"],
                "per_chat_overrides": [{"chat_id": "friend:alice", "mode": "manual"}],
            }
        },
    }
    current_snapshot = _build_snapshot(current_config)
    updated_snapshot = _build_snapshot(updated_config)

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(api_module.config_service, "get_snapshot", return_value=current_snapshot),
        patch.object(api_module.config_service, "save_effective_config", return_value=updated_snapshot) as save_mock,
    ):
        response = await client.post(
            "/api/reply_policies",
            json={"chat_id": "friend:alice", "mode": "manual"},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["reply_policy"]["per_chat_overrides"][0]["chat_id"] == "friend:alice"
    mock_manager.reload_runtime_config.assert_awaited()
    save_mock.assert_called_once()


@pytest.mark.asyncio
async def test_api_pending_replies_list_and_approve(client, mock_manager):
    snapshot = _build_snapshot(
        {
            "api": {"presets": []},
            "bot": {
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "manual",
                    "group_mode": "whitelist_only",
                    "quiet_hours": {"start": "00:00", "end": "07:30", "mode": "manual"},
                    "sensitive_keywords": [],
                    "per_chat_overrides": [],
                    "pending_ttl_hours": 24,
                }
            },
            "logging": {},
            "agent": {},
            "services": {},
        }
    )

    with patch.object(api_module.config_service, "get_snapshot", return_value=snapshot):
        list_response = await client.get("/api/pending_replies?chat_id=friend:alice&status=pending&limit=20")
        approve_response = await client.post(
            "/api/pending_replies/7/approve",
            json={"edited_reply": "修改后回复"},
        )

    assert list_response.status_code == 200
    list_data = await list_response.get_json()
    assert list_data["success"] is True
    assert list_data["items"][0]["chat_id"] == "friend:alice"

    assert approve_response.status_code == 200
    approve_data = await approve_response.get_json()
    assert approve_data["success"] is True
    mock_manager.bot.approve_pending_reply.assert_awaited_once_with(7, edited_reply="修改后回复")


@pytest.mark.asyncio
async def test_api_pending_reply_reject_works_without_running_bot(client, mock_manager):
    mock_manager.is_running = False
    mock_manager.bot = None
    snapshot = _build_snapshot(
        {
            "api": {"presets": []},
            "bot": {
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "manual",
                    "group_mode": "whitelist_only",
                    "quiet_hours": {"start": "00:00", "end": "07:30", "mode": "manual"},
                    "sensitive_keywords": [],
                    "per_chat_overrides": [],
                    "pending_ttl_hours": 24,
                }
            },
            "logging": {},
            "agent": {},
            "services": {},
        }
    )

    with patch.object(api_module.config_service, "get_snapshot", return_value=snapshot):
        response = await client.post("/api/pending_replies/7/reject")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    mock_manager.get_memory_manager().resolve_pending_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_backups_create_and_dry_run_restore(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "b1", "mode": "quick"}) as create_mock,
        patch.object(
            api_module.backup_service,
            "list_backups",
            return_value={"success": True, "backups": [{"id": "b1"}], "summary": {"latest_quick_backup_at": 1}},
        ) as list_mock,
        patch.object(
            api_module.config_service,
            "get_snapshot",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ) as plan_mock,
    ):
        create_response = await client.post("/api/backups", json={"mode": "quick", "label": "nightly"})
        dry_run_response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": True})

    assert create_response.status_code == 200
    create_data = await create_response.get_json()
    assert create_data["success"] is True
    assert create_data["backup"]["id"] == "b1"
    create_mock.assert_called_once_with("quick", label="nightly")
    list_mock.assert_called()

    assert dry_run_response.status_code == 200
    dry_run_data = await dry_run_response.get_json()
    assert dry_run_data["success"] is True
    assert dry_run_data["dry_run"] is True
    plan_mock.assert_called_once_with("b1", allow_legacy_unverified=False)


@pytest.mark.asyncio
async def test_api_backups_create_replays_idempotent_response(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    growth_manager = MagicMock()
    growth_manager.is_running = False
    headers = {"Idempotency-Key": "backup-idem-1"}

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "b1", "mode": "quick"}) as create_mock,
        patch.object(
            api_module.backup_service,
            "list_backups",
            return_value={"success": True, "backups": [{"id": "b1"}], "summary": {"latest_quick_backup_at": 1}},
        ) as list_mock,
        patch.object(
            api_module.config_service,
            "get_snapshot",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
    ):
        first = await client.post("/api/backups", json={"mode": "quick", "label": "nightly"}, headers=headers)
        second = await client.post("/api/backups", json={"mode": "quick", "label": "nightly"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    second_data = await second.get_json()
    assert second_data["success"] is True
    assert second.headers.get("X-Idempotency-Replayed") == "1"
    create_mock.assert_called_once_with("quick", label="nightly")
    list_mock.assert_called_once()


@pytest.mark.asyncio
async def test_api_backups_create_rejects_when_runtime_is_running(client, mock_manager):
    mock_manager.is_running = True
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with patch("backend.api.get_growth_manager", return_value=growth_manager):
        response = await client.post("/api/backups", json={"mode": "quick", "label": "nightly"})

    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False
    assert data["running"]["bot"] is True


@pytest.mark.asyncio
async def test_api_backups_restore_requires_backup_id_field(client, mock_manager):
    response = await client.post(
        "/api/backups/restore",
        json={"path": "C:/temp/backup", "dry_run": True},
    )
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "backup_id is required" in data["message"]


@pytest.mark.asyncio
async def test_api_backups_restore_defaults_to_dry_run(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(
            api_module.config_service,
            "get_snapshot",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ) as plan_mock,
        patch.object(api_module.backup_service, "apply_restore") as apply_mock,
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1"})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["dry_run"] is True
    plan_mock.assert_called_once_with("b1", allow_legacy_unverified=False)
    apply_mock.assert_not_called()


@pytest.mark.asyncio
async def test_api_backups_cleanup_supports_dry_run_and_apply(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(
            api_module.backup_service,
            "cleanup_backups",
            side_effect=[
                {
                    "success": True,
                    "dry_run": True,
                    "candidate_count": 2,
                    "delete_candidates": [{"id": "quick-1"}],
                    "deleted_backups": [],
                    "keep_policy": {"keep_quick": 4, "keep_full": 2},
                },
                {
                    "success": True,
                    "dry_run": False,
                    "candidate_count": 1,
                    "deleted_count": 1,
                    "delete_candidates": [{"id": "quick-2"}],
                    "deleted_backups": [{"id": "quick-2"}],
                    "keep_policy": {"keep_quick": 4, "keep_full": 2},
                },
            ],
        ) as cleanup_mock,
    ):
        preview_response = await client.post(
            "/api/backups/cleanup",
            json={"keep_quick": 4, "keep_full": 2, "dry_run": True},
        )
        apply_response = await client.post(
            "/api/backups/cleanup",
            json={"keep_quick": 4, "keep_full": 2, "dry_run": False},
        )

    assert preview_response.status_code == 200
    preview_data = await preview_response.get_json()
    assert preview_data["success"] is True
    assert preview_data["dry_run"] is True
    assert preview_data["candidate_count"] == 2

    assert apply_response.status_code == 200
    apply_data = await apply_response.get_json()
    assert apply_data["success"] is True
    assert apply_data["dry_run"] is False
    assert apply_data["deleted_count"] == 1

    assert cleanup_mock.call_args_list[0].kwargs == {
        "keep_quick": 4,
        "keep_full": 2,
        "apply": False,
    }
    assert cleanup_mock.call_args_list[1].kwargs == {
        "keep_quick": 4,
        "keep_full": 2,
        "apply": True,
    }


@pytest.mark.asyncio
async def test_api_backups_cleanup_failure_is_sanitized(client, mock_manager):
    with patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("cleanup-secret"))):
        response = await client.post(
            "/api/backups/cleanup",
            json={"keep_quick": 4, "keep_full": 2, "dry_run": False},
        )

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "backup_cleanup_failed"
    assert data["code"] == "backup_cleanup_failed"
    assert "cleanup-secret" not in str(data)


@pytest.mark.asyncio
async def test_api_maintenance_lock_blocks_cleanup_apply(client, mock_manager):
    lock = api_module.maintenance_lock
    if lock.locked():
        lock.release()
    await lock.acquire()
    try:
        response = await client.post(
            "/api/backups/cleanup",
            json={"keep_quick": 4, "keep_full": 2, "dry_run": False},
        )
    finally:
        if lock.locked():
            lock.release()

    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False
    assert data["message"] == "maintenance_in_progress"


@pytest.mark.asyncio
async def test_api_backups_restore_applies_and_restarts_runtime(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    events = []

    async def _stop_growth(*args, **kwargs):
        events.append("stop_growth")
        return {"success": True, "message": "growth stopped"}

    async def _start_growth(*args, **kwargs):
        events.append("start_growth")
        return {"success": True, "message": "growth started"}

    async def _stop_bot(*args, **kwargs):
        events.append("stop_bot")
        return {"success": True, "message": "bot stopped"}

    async def _start_bot(*args, **kwargs):
        events.append("start_bot")
        return {"success": True, "message": "bot started"}

    async def _close_memory():
        events.append("close_memory")

    def _create_pre_restore(*args, **kwargs):
        events.append("create_pre_restore")
        return {"id": "pre-1", "mode": "quick"}

    def _apply_restore(*args, **kwargs):
        events.append("apply_restore")
        return {"success": True, "restored_count": 1}

    growth_manager = MagicMock()
    growth_manager.is_running = True
    growth_manager.stop = AsyncMock(side_effect=_stop_growth)
    growth_manager.start = AsyncMock(side_effect=_start_growth)

    mock_manager.is_running = True
    mock_manager.stop = AsyncMock(side_effect=_stop_bot)
    mock_manager.start = AsyncMock(side_effect=_start_bot)
    mock_manager.memory_manager = MagicMock()
    memory_close = AsyncMock(side_effect=_close_memory)
    mock_manager.memory_manager.close = memory_close

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch("backend.api.close_reply_quality_tracker", side_effect=lambda: events.append("close_reply_tracker")) as close_reply_tracker_mock,
        patch.object(api_module, "_collect_restore_auth_checks", return_value={"success": True, "warning_count": 1, "warnings": [{"provider_id": "openai"}]}),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", side_effect=_create_pre_restore),
        patch.object(api_module.backup_service, "apply_restore", side_effect=_apply_restore),
        patch.object(api_module.backup_service, "save_restore_result") as save_result_mock,
        patch.object(api_module.config_service, "reload", return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}})),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["pre_restore_backup"]["id"] == "pre-1"
    assert data["auth_restore_checks"]["warning_count"] == 1
    mock_manager.stop.assert_awaited_once()
    mock_manager.start.assert_awaited_once()
    growth_manager.stop.assert_awaited_once()
    growth_manager.start.assert_awaited_once()
    memory_close.assert_awaited_once()
    close_reply_tracker_mock.assert_called_once()
    assert events.index("create_pre_restore") > events.index("stop_growth")
    assert events.index("create_pre_restore") > events.index("stop_bot")
    assert events.index("create_pre_restore") > events.index("close_memory")
    assert events.index("create_pre_restore") > events.index("close_reply_tracker")
    save_result_mock.assert_called_once()


@pytest.mark.asyncio
async def test_api_backups_restore_fails_fast_when_stop_stage_returns_success_false(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    growth_manager = MagicMock()
    growth_manager.is_running = False

    mock_manager.is_running = True
    mock_manager.bot = MagicMock()
    mock_manager.stop = AsyncMock(return_value={"success": False, "message": "bot stop rejected"})
    mock_manager.start = AsyncMock(return_value={"success": True, "message": "bot started"})
    mock_manager.memory_manager = None

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.config_service,
            "get_snapshot",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-1", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", return_value={"success": True, "restored_count": 1}) as apply_restore_mock,
        patch.object(api_module.backup_service, "save_restore_result"),
        patch.object(
            api_module.config_service,
            "reload",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(api_module, "_collect_restore_auth_checks", return_value={"success": True, "warning_count": 0, "warnings": []}),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code >= 400
    data = await response.get_json()
    assert data["success"] is False
    apply_restore_mock.assert_not_called()
    mock_manager.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_backups_restore_fails_when_restart_stage_returns_success_false(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    growth_manager = MagicMock()
    growth_manager.is_running = False

    mock_manager.is_running = True
    mock_manager.bot = MagicMock()
    mock_manager.stop = AsyncMock(return_value={"success": True, "message": "bot stopped"})
    mock_manager.start = AsyncMock(return_value={"success": False, "message": "bot restart failed"})
    mock_manager.memory_manager = None

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.config_service,
            "get_snapshot",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-1", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", return_value={"success": True, "restored_count": 1}) as apply_restore_mock,
        patch.object(api_module.backup_service, "save_restore_result"),
        patch.object(
            api_module.config_service,
            "reload",
            return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}}),
        ),
        patch.object(api_module, "_collect_restore_auth_checks", return_value={"success": True, "warning_count": 0, "warnings": []}),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code >= 400
    data = await response.get_json()
    assert data["success"] is False
    assert data["restart_results"]["bot"]["success"] is False
    assert apply_restore_mock.call_count == 2
    first_call = apply_restore_mock.call_args_list[0]
    second_call = apply_restore_mock.call_args_list[1]
    assert first_call.args == ("b1",)
    assert first_call.kwargs == {"allow_legacy_unverified": False}
    assert second_call.args == ("pre-1",)


@pytest.mark.asyncio
async def test_api_backups_restore_forwards_legacy_opt_in_flag(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    growth_manager = MagicMock()
    growth_manager.is_running = False
    mock_manager.is_running = False
    mock_manager.bot = None
    mock_manager.memory_manager = None

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "legacy-1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ) as plan_mock,
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-legacy", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", return_value={"success": True, "restored_count": 1}) as apply_mock,
        patch.object(api_module.backup_service, "save_restore_result"),
        patch.object(api_module.config_service, "reload", return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}})),
    ):
        response = await client.post(
            "/api/backups/restore",
            json={"backup_id": "legacy-1", "dry_run": False, "allow_legacy_unverified": True},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    plan_mock.assert_called_once_with("legacy-1", allow_legacy_unverified=True)
    apply_mock.assert_called_once_with("legacy-1", allow_legacy_unverified=True)


@pytest.mark.asyncio
async def test_api_backups_restore_attempts_pre_restore_rollback_when_apply_fails(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    mock_manager.bot = None
    mock_manager.memory_manager = None
    growth_manager = MagicMock()
    growth_manager.is_running = False

    apply_calls = []

    def _apply_restore(backup_ref, **kwargs):
        apply_calls.append({"backup_ref": backup_ref, "kwargs": kwargs})
        if backup_ref == "b1":
            raise RuntimeError("restore failed")
        if backup_ref == "pre-1":
            return {"success": True, "restored_count": 1}
        raise AssertionError("unexpected backup ref")

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-1", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", side_effect=_apply_restore),
        patch.object(api_module.backup_service, "save_restore_result"),
        patch.object(api_module.config_service, "reload", return_value=_build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}})),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["rollback_result"]["success"] is True
    assert apply_calls[0]["backup_ref"] == "b1"
    assert apply_calls[1]["backup_ref"] == "pre-1"


@pytest.mark.asyncio
async def test_api_backups_restore_attempts_rollback_when_reload_fails_after_apply(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    mock_manager.bot = None
    mock_manager.memory_manager = None
    growth_manager = MagicMock()
    growth_manager.is_running = False

    apply_calls = []
    reload_calls = {"count": 0}

    def _apply_restore(backup_ref, **kwargs):
        apply_calls.append({"backup_ref": backup_ref, "kwargs": kwargs})
        return {"success": True, "restored_count": 1}

    def _reload(*args, **kwargs):
        reload_calls["count"] += 1
        if reload_calls["count"] == 1:
            raise RuntimeError("reload failed")
        return _build_snapshot({"api": {}, "bot": {}, "logging": {}, "agent": {}, "services": {}})

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-1", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", side_effect=_apply_restore),
        patch.object(api_module.backup_service, "save_restore_result"),
        patch.object(api_module.config_service, "reload", side_effect=_reload),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["rollback_result"]["success"] is True
    assert data["message"] == "restore_backup_failed"
    assert data["code"] == "restore_backup_failed"
    assert apply_calls[0]["backup_ref"] == "b1"
    assert apply_calls[1]["backup_ref"] == "pre-1"


@pytest.mark.asyncio
async def test_api_backups_restore_sanitizes_restart_exception_message(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = True
    mock_manager.stop = AsyncMock(return_value={"success": True, "message": "bot stopped"})
    mock_manager.start = AsyncMock(side_effect=RuntimeError("bot restart secret"))
    mock_manager.memory_manager = MagicMock()
    mock_manager.memory_manager.close = AsyncMock(return_value=None)

    growth_manager = MagicMock()
    growth_manager.is_running = False

    apply_calls = []

    def _apply_restore(backup_ref, **kwargs):
        apply_calls.append(backup_ref)
        if backup_ref == "b1":
            raise RuntimeError("restore failed")
        return {"success": True, "restored_count": 1}

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup", return_value={"id": "pre-1", "mode": "quick"}),
        patch.object(api_module.backup_service, "apply_restore", side_effect=_apply_restore),
        patch.object(api_module.backup_service, "save_restore_result"),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["restart_results"]["bot"]["success"] is False
    assert data["restart_results"]["bot"]["message"] == "restart_failed"
    assert data["restart_results"]["bot"]["code"] == "restart_failed"
    assert "bot restart secret" not in str(data)
    assert apply_calls == ["b1", "pre-1"]


@pytest.mark.asyncio
async def test_api_backups_restore_recovers_runtime_when_stop_or_close_stage_fails(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _stop_growth(*args, **kwargs):
        return {"success": True, "message": "growth stopped"}

    async def _start_growth(*args, **kwargs):
        return {"success": True, "message": "growth started"}

    async def _stop_bot(*args, **kwargs):
        return {"success": True, "message": "bot stopped"}

    async def _start_bot(*args, **kwargs):
        return {"success": True, "message": "bot started"}

    async def _close_memory():
        raise RuntimeError("close memory failed")

    growth_manager = MagicMock()
    growth_manager.is_running = True
    growth_manager.stop = AsyncMock(side_effect=_stop_growth)
    growth_manager.start = AsyncMock(side_effect=_start_growth)

    mock_manager.is_running = True
    mock_manager.stop = AsyncMock(side_effect=_stop_bot)
    mock_manager.start = AsyncMock(side_effect=_start_bot)
    mock_manager.memory_manager = MagicMock()
    mock_manager.memory_manager.close = AsyncMock(side_effect=_close_memory)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={"backup": {"id": "b1"}, "included_files": ["app_config.json"], "missing_files": [], "valid": True},
        ),
        patch.object(api_module.backup_service, "create_backup") as create_backup_mock,
        patch.object(api_module.backup_service, "apply_restore") as apply_restore_mock,
        patch.object(api_module.backup_service, "save_restore_result"),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "b1", "dry_run": False})

    assert response.status_code == 500
    data = await response.get_json()
    assert data["success"] is False
    assert data["pre_restore_backup"] is None
    assert data["message"] == "restore_backup_failed"
    assert data["code"] == "restore_backup_failed"
    growth_manager.stop.assert_awaited_once()
    mock_manager.stop.assert_awaited_once()
    mock_manager.start.assert_awaited_once()
    growth_manager.start.assert_awaited_once()
    create_backup_mock.assert_not_called()
    apply_restore_mock.assert_not_called()


@pytest.mark.asyncio
async def test_api_backups_restore_reports_invalid_files_message(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(
            api_module.backup_service,
            "build_restore_plan",
            return_value={
                "backup": {"id": "bad-1"},
                "included_files": [],
                "missing_files": [],
                "invalid_files": ["../escape.txt"],
                "valid": False,
            },
        ),
    ):
        response = await client.post("/api/backups/restore", json={"backup_id": "bad-1", "dry_run": False})

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "unsupported paths" in data["message"]


@pytest.mark.asyncio
async def test_api_data_controls_get_returns_supported_scopes(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch.object(
            api_module.data_control_service,
            "build_clear_plan",
            return_value={"success": True, "scopes": ["memory"], "targets": [], "target_count": 0, "existing_target_count": 0, "reclaimable_bytes": 0},
        ) as plan_mock,
        patch.object(
            api_module.data_control_service,
            "list_supported_scopes",
            return_value=["memory", "usage", "export_rag"],
        ),
    ):
        response = await client.get("/api/data_controls")

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["supported_scopes"] == ["memory", "usage", "export_rag"]
    plan_mock.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_api_data_controls_clear_supports_dry_run_and_apply(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.data_control_service,
            "clear",
            side_effect=[
                {
                    "success": True,
                    "dry_run": True,
                    "scopes": ["memory"],
                    "existing_target_count": 2,
                    "reclaimable_bytes": 4096,
                },
                {
                    "success": True,
                    "dry_run": False,
                    "scopes": ["memory"],
                    "deleted_count": 2,
                    "reclaimed_bytes": 4096,
                    "failed_targets": [],
                },
            ],
        ) as clear_mock,
    ):
        preview_response = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": True},
        )
        apply_response = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": False},
        )

    assert preview_response.status_code == 200
    preview_data = await preview_response.get_json()
    assert preview_data["success"] is True
    assert preview_data["dry_run"] is True

    assert apply_response.status_code == 200
    apply_data = await apply_response.get_json()
    assert apply_data["success"] is True
    assert apply_data["dry_run"] is False
    assert apply_data["deleted_count"] == 2

    assert clear_mock.call_args_list[0].args == (["memory"],)
    assert clear_mock.call_args_list[0].kwargs == {"apply": False}
    assert clear_mock.call_args_list[1].args == (["memory"],)
    assert clear_mock.call_args_list[1].kwargs == {"apply": True}


@pytest.mark.asyncio
async def test_api_data_controls_clear_apply_replays_idempotent_response(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    growth_manager = MagicMock()
    growth_manager.is_running = False
    headers = {"Idempotency-Key": "data-clear-idem-1"}

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch.object(
            api_module.data_control_service,
            "clear",
            return_value={
                "success": True,
                "dry_run": False,
                "scopes": ["memory"],
                "deleted_count": 2,
                "reclaimed_bytes": 4096,
                "failed_targets": [],
            },
        ) as clear_mock,
    ):
        first = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": False},
            headers=headers,
        )
        second = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": False},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    second_data = await second.get_json()
    assert second_data["success"] is True
    assert second.headers.get("X-Idempotency-Replayed") == "1"
    clear_mock.assert_called_once_with(["memory"], apply=True)


@pytest.mark.asyncio
async def test_api_data_controls_apply_closes_local_sqlite_handles(client, mock_manager):
    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_manager.is_running = False
    memory_manager = MagicMock()
    memory_manager.close = AsyncMock()
    mock_manager.memory_manager = memory_manager
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with (
        patch("backend.api.asyncio.to_thread", AsyncMock(side_effect=_fake_to_thread)),
        patch("backend.api.get_growth_manager", return_value=growth_manager),
        patch("backend.api.close_reply_quality_tracker") as close_tracker_mock,
        patch.object(
            api_module.data_control_service,
            "clear",
            return_value={
                "success": True,
                "dry_run": False,
                "scopes": ["memory"],
                "deleted_count": 1,
                "reclaimed_bytes": 128,
                "failed_targets": [],
            },
        ),
    ):
        response = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": False},
        )

    assert response.status_code == 200
    memory_manager.close.assert_awaited_once()
    assert mock_manager.memory_manager is None
    close_tracker_mock.assert_called_once()


@pytest.mark.asyncio
async def test_api_data_controls_apply_requires_explicit_scopes(client, mock_manager):
    mock_manager.is_running = False
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with patch("backend.api.get_growth_manager", return_value=growth_manager):
        response = await client.post(
            "/api/data_controls/clear",
            json={"dry_run": False},
        )

    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "scopes is required" in data["message"]


@pytest.mark.asyncio
async def test_api_data_controls_apply_rejects_when_runtime_is_running(client, mock_manager):
    mock_manager.is_running = True
    growth_manager = MagicMock()
    growth_manager.is_running = False

    with patch("backend.api.get_growth_manager", return_value=growth_manager):
        response = await client.post(
            "/api/data_controls/clear",
            json={"scopes": ["memory"], "dry_run": False},
        )

    assert response.status_code == 409
    data = await response.get_json()
    assert data["success"] is False
    assert data["running"]["bot"] is True
