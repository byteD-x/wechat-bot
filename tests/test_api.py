
import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

pytest.importorskip("quart")

from quart import Quart

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
    mem_mgr.get_message_page = MagicMock(side_effect=async_get_message_page)
    mem_mgr.list_chat_summaries = MagicMock(side_effect=async_list_chat_summaries)
    mem_mgr.get_contact_profile = MagicMock(side_effect=async_get_contact_profile)
    mem_mgr.save_contact_prompt = MagicMock(side_effect=async_save_contact_prompt)
    mem_mgr.update_message_feedback = MagicMock(side_effect=async_update_message_feedback)
    mem_mgr.get_profile_prompt_snapshot = MagicMock(side_effect=async_get_profile_prompt_snapshot)
    manager.get_memory_manager.return_value = mem_mgr
    
    # Replace the manager in the api module
    original_manager = api_module.manager
    api_module.manager = manager
    yield manager
    # Restore
    api_module.manager = original_manager

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
async def test_api_messages_error(client, mock_manager):
    mock_manager.get_memory_manager().get_message_page.side_effect = Exception("DB Error")
    response = await client.get('/api/messages?limit=10')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "DB Error" in data["message"]

@pytest.mark.asyncio
async def test_api_send_error(client, mock_manager):
    mock_manager.send_message.side_effect = Exception("Send Error")
    response = await client.post('/api/send', json={"target": "User", "content": "Hello"})
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "Send Error" in data["message"]

@pytest.mark.asyncio
async def test_api_usage_error(client, mock_manager):
    mock_manager.get_usage.side_effect = Exception("Usage Error")
    response = await client.get('/api/usage')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "Usage Error" in data["message"]


@pytest.mark.asyncio
async def test_api_model_catalog(client):
    response = await client.get('/api/model_catalog')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    qwen = next((provider for provider in data["providers"] if provider["id"] == "qwen"), None)
    assert qwen is not None
    assert "qwen3.5-plus" in qwen["models"]


@pytest.mark.asyncio
async def test_api_config_masks_key_and_infers_provider(client):
    test_config = {
        "api": {
            "presets": [
                {
                    "name": "Qwen",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-1234567890abcdef",
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
                    "api_key": "sk-test-openai",
                    "model": "gpt-5-mini",
                    "alias": "小欧",
                    "allow_empty_key": False,
                },
                {
                    "name": "DeepSeek",
                    "provider_id": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-test-deepseek",
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
