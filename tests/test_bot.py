import sys
import types
import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock, ANY

sys.modules.setdefault("aiosqlite", types.SimpleNamespace())

from backend.bot import WeChatBot
from backend.bot_event_flow import build_incoming_broadcast_payload
from backend.bot_reply_flow import build_outgoing_broadcast_payload
from backend.config_schemas import BotConfig

TEST_LOG_PATH = "data/runtime/test/test.log"


def _build_mock_bot_manager():
    manager = MagicMock()
    manager.update_startup_state = AsyncMock()
    manager.notify_status_change = AsyncMock()
    manager.broadcast_event = AsyncMock()
    manager.apply_pause_state = AsyncMock()
    manager.set_issue = MagicMock()
    manager.clear_issue = MagicMock()
    manager._invalidate_status_cache = MagicMock()
    return manager


def _build_snapshot(config):
    snapshot = MagicMock()
    snapshot.to_dict.return_value = config
    snapshot.config = config
    snapshot.api = config.get("api", {})
    snapshot.bot = config.get("bot", {})
    snapshot.logging = config.get("logging", {})
    snapshot.agent = config.get("agent", {})
    return snapshot


def _build_config_service(config=None, *, error=None):
    service = MagicMock()
    if error is not None:
        service.get_snapshot.side_effect = error
        service.reload.side_effect = error
    elif config is not None:
        service.get_snapshot.return_value = _build_snapshot(config)
        service.reload.return_value = _build_snapshot(config)
    service.publish.side_effect = lambda next_config, **kwargs: _build_snapshot(next_config)
    service.sync_default_config_snapshot.return_value = False
    return service


def _build_pending_reply_memory():
    memory = MagicMock()
    memory.expire_pending_replies = AsyncMock(return_value=0)
    memory.get_pending_reply_stats = AsyncMock(
        return_value={
            "total": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "expired": 0,
            "failed": 0,
            "latest_created_at": 0,
            "by_status": {},
        }
    )
    return memory


def test_bot_schema_allows_zero_reply_deadline():
    assert BotConfig(reply_deadline_sec=0).reply_deadline_sec == 0

@pytest.mark.asyncio
async def test_bot_initialization(mock_config):
    mock_service = _build_config_service(mock_config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        with patch("backend.bot.get_file_mtime", return_value=123456.0):
            bot = WeChatBot("config.yaml")

            # Mock internal components
            bot.memory = _build_pending_reply_memory()

            # Mock select_ai_client
            with patch("backend.bot.select_ai_client", return_value=(AsyncMock(), "default")):
                # Mock reconnect_wechat
                mock_wx = MagicMock()
                with patch("backend.bot.reconnect_wechat", return_value=mock_wx):
                    wx = await bot.initialize()
                    assert wx is mock_wx
                    assert bot.config == mock_config
                    assert bot.config_mtime == 123456.0

@pytest.mark.asyncio
async def test_bot_apply_config(mock_config):
    bot = WeChatBot("config.yaml")
    bot.config = mock_config
    
    with patch("backend.bot.setup_logging") as mock_setup_logging:
        bot._apply_config()
        assert bot.bot_cfg == mock_config["bot"]
        assert bot.api_cfg == mock_config["api"]
        mock_setup_logging.assert_called()


@pytest.mark.asyncio
async def test_schedule_export_rag_sync_uses_runtime_backlog_when_available():
    bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot.export_rag = SimpleNamespace(enabled=True, auto_ingest=True)
    bot.ai_client = SimpleNamespace(
        update_runtime_dependencies=MagicMock(),
        schedule_export_rag_sync=AsyncMock(),
    )

    await bot._schedule_export_rag_sync(force=True)

    bot.ai_client.update_runtime_dependencies.assert_called_once()
    bot.ai_client.schedule_export_rag_sync.assert_awaited_once_with(force=True)
    await asyncio.sleep(0)
    bot.bot_manager.notify_status_change.assert_awaited_once()

@pytest.mark.asyncio
async def test_bot_initialization_config_error(mock_config):
    # Test config load failure
    mock_service = _build_config_service(error=Exception("Config load failed"))
    with patch("backend.bot.get_config_service", return_value=mock_service):
        with patch("backend.bot.get_file_mtime", return_value=123456.0):
            bot = WeChatBot("config.yaml")
            wx = await bot.initialize()
            assert wx is None

@pytest.mark.asyncio
async def test_bot_initialization_vector_memory_error(mock_config):
    # Test vector memory init failure
    config_with_rag = mock_config.copy()
    config_with_rag["bot"]["rag_enabled"] = True

    mock_service = _build_config_service(config_with_rag)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        with patch("backend.bot.get_file_mtime", return_value=123456.0):
            bot = WeChatBot("config.yaml")
            bot.memory = _build_pending_reply_memory()
            
            # Mock VectorMemory to raise exception
            with patch("backend.bot.VectorMemory", side_effect=Exception("VectorDB failed")):
                with patch("backend.bot.select_ai_client", return_value=(AsyncMock(), "default")):
                    with patch("backend.bot.reconnect_wechat", return_value=MagicMock()):
                        await bot.initialize()
                        # Should continue even if vector memory fails
                        assert bot.vector_memory is None


def test_bot_vector_memory_master_switch_disables_rag(mock_config):
    bot = WeChatBot("config.yaml")
    bot.config = mock_config
    bot.bot_cfg = dict(mock_config["bot"])
    bot.bot_cfg["vector_memory_enabled"] = False
    bot.bot_cfg["rag_enabled"] = True
    bot.bot_cfg["export_rag_enabled"] = True

    assert bot._vector_memory_requested() is False


def test_bot_transport_status_preserves_preferred_backend_when_disconnected():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {
        "required_wechat_version": "",
    }

    with patch(
        "backend.bot.get_last_transport_error",
        return_value="已安装 wcferry 仅支持微信 3.9.12.51，当前为 3.9.12.17",
    ):
        status = bot.get_transport_status()

    assert status["transport_backend"] == "wcferry"
    assert status["transport_status"] == "disconnected"
    assert status["silent_mode"] is True
    assert "3.9.12.51" in status["transport_warning"]

@pytest.mark.asyncio
async def test_bot_run_loop(mock_config):
    mock_bot_manager = _build_mock_bot_manager()
    mock_service = _build_config_service(mock_config)
    with patch("backend.bot.get_config_service", return_value=mock_service), \
         patch("backend.bot.get_file_mtime", return_value=123456.0), \
         patch("backend.bot.select_ai_client", return_value=(AsyncMock(), "default")), \
         patch("backend.bot.reconnect_wechat", return_value=MagicMock()), \
         patch("backend.bot.normalize_new_messages", return_value=[]), \
         patch("backend.bot.get_bot_manager", return_value=mock_bot_manager):
         
        bot = WeChatBot("config.yaml")
        bot.memory = _build_pending_reply_memory()
        bot.memory.close = AsyncMock()
        await bot.initialize()
        
        bot._stop_event = asyncio.Event()
        
        # Stop after one iteration
        async def mock_sleep(delay):
            print(f"DEBUG: mock_sleep called with {delay}")
            bot._stop_event.set()
            
        with patch("asyncio.sleep", side_effect=mock_sleep):
             with patch("backend.bot.IPCManager"):
                 # Mock to_thread for poll_new_messages
                 with patch("asyncio.to_thread", return_value={}):
                     print("DEBUG: Starting run loop")
                     try:
                         await asyncio.wait_for(bot.run(), timeout=2.0)
                     except asyncio.TimeoutError:
                         print("DEBUG: Timeout reached")
                         # Force stop
                         bot._stop_event.set()

@pytest.mark.asyncio
async def test_bot_run_loop_wx_exception(mock_config):
    mock_bot_manager = _build_mock_bot_manager()
    mock_service = _build_config_service(mock_config)
    with patch("backend.bot.get_config_service", return_value=mock_service), \
         patch("backend.bot.get_file_mtime", return_value=123456.0), \
         patch("backend.bot.select_ai_client", return_value=(AsyncMock(), "default")), \
         patch("backend.bot.reconnect_wechat", return_value=None), \
         patch("backend.bot.normalize_new_messages", return_value=[]), \
         patch("backend.bot.get_bot_manager", return_value=mock_bot_manager):
         
        bot = WeChatBot("config.yaml")
        bot.memory = _build_pending_reply_memory()
        bot.memory.close = AsyncMock()
        # No need to call initialize here as run() calls it
        
        bot._stop_event = asyncio.Event()
        
        async def mock_sleep(delay):
            print(f"DEBUG: mock_sleep exception called with {delay}")
            bot._stop_event.set()
            
        with patch("asyncio.sleep", side_effect=mock_sleep):
             with patch("backend.bot.IPCManager"):
                 # Mock to_thread to raise exception
                 with patch("asyncio.to_thread", side_effect=Exception("WX Error")):
                     try:
                         await asyncio.wait_for(bot.run(), timeout=2.0)
                     except asyncio.TimeoutError:
                         print("DEBUG: Timeout reached in exception test")


@pytest.mark.asyncio
async def test_bot_run_exits_when_initialize_returns_none():
    mock_bot_manager = _build_mock_bot_manager()
    with patch("backend.bot.get_bot_manager", return_value=mock_bot_manager):
        bot = WeChatBot("config.yaml")
        bot.initialize = AsyncMock(return_value=None)

        await bot.run()

        bot.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_reload_runtime_config_refreshes_watcher_for_non_ai_changes():
    config = {
        "bot": {
            "config_reload_mode": "auto",
            "config_reload_debounce_ms": 500,
            "reload_ai_client_module": False,
        },
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    mock_service = _build_config_service(config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot.config = config
    bot._apply_config()
    bot.api_signature = "same-signature"
    bot.runtime_preset_name = "Ollama"
    bot._ensure_config_reload_watcher = MagicMock()
    bot._ensure_vector_memory = MagicMock()
    bot._schedule_export_rag_sync = AsyncMock()

    new_config = {
        "bot": {
            "config_reload_mode": "watchdog",
            "config_reload_debounce_ms": 1500,
            "reload_ai_client_module": False,
        },
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }

    with patch("backend.bot.compute_api_signature", return_value="same-signature"):
        result = await bot.reload_runtime_config(new_config=new_config)

    assert result["success"] is True
    bot._ensure_config_reload_watcher.assert_called_once()
    bot._schedule_export_rag_sync.assert_awaited_once_with(force=True)
    bot.bot_manager.notify_status_change.assert_awaited_once()
    assert bot.bot_cfg["config_reload_mode"] == "watchdog"
    assert bot.bot_cfg["config_reload_debounce_ms"] == 1500


@pytest.mark.asyncio
async def test_reload_runtime_config_honors_reload_ai_client_module():
    config = {
        "bot": {"reload_ai_client_module": True},
        "api": {
            "active_preset": "DeepSeek",
            "base_url": "http://localhost",
            "api_key": "sk-test",
            "model": "gpt-4o",
        },
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    mock_service = _build_config_service(config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot.config = config
    bot._apply_config()
    bot.api_signature = "same-signature"
    bot.runtime_preset_name = "Ollama"
    bot._ensure_config_reload_watcher = MagicMock()
    bot._ensure_vector_memory = MagicMock()
    bot._schedule_export_rag_sync = AsyncMock()
    bot.ai_client = AsyncMock()
    new_client = AsyncMock()

    with patch("backend.bot.compute_api_signature", return_value="same-signature"), \
         patch("backend.bot.reload_ai_module", new=AsyncMock()) as mock_reload_module, \
         patch("backend.bot.select_ai_client", new=AsyncMock(return_value=(new_client, "DeepSeek"))):
        result = await bot.reload_runtime_config(
            new_config=config,
            strict_active_preset=False,
        )

    assert result["success"] is True
    mock_reload_module.assert_awaited_once()
    assert bot.ai_client is new_client
    assert bot.runtime_preset_name == "DeepSeek"
    bot.bot_manager.notify_status_change.assert_awaited_once()


@pytest.mark.asyncio
async def test_reload_runtime_config_reconnects_transport_for_transport_changes():
    config = {
        "bot": {
            "required_wechat_version": "",
            "reload_ai_client_module": False,
        },
        "api": {
            "base_url": "http://localhost",
            "api_key": "sk-test",
            "model": "gpt-4o",
        },
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    next_config = {
        "bot": {
            "required_wechat_version": "3.9.12.51",
            "reload_ai_client_module": False,
        },
        "api": {
            "base_url": "http://localhost",
            "api_key": "sk-test",
            "model": "gpt-4o",
        },
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    mock_service = _build_config_service(config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        bot = WeChatBot("config.yaml")

    bot.bot_manager = _build_mock_bot_manager()
    bot.config = config
    bot._apply_config()
    bot.api_signature = "same-signature"
    bot.runtime_preset_name = "Ollama"
    bot._ensure_config_reload_watcher = MagicMock()
    bot._ensure_vector_memory = MagicMock()
    bot._schedule_export_rag_sync = AsyncMock()
    bot.wx = MagicMock()
    new_wx = MagicMock()

    with patch("backend.bot.compute_api_signature", return_value="same-signature"), \
         patch("backend.bot.get_file_mtime", return_value=123456.0), \
         patch("backend.bot.reconnect_wechat", new=AsyncMock(return_value=new_wx)) as mock_reconnect:
        result = await bot.reload_runtime_config(
            new_config=next_config,
            changed_paths=["bot.required_wechat_version"],
        )

    assert result["success"] is True
    assert result["transport_reconnect_required"] is True
    assert result["transport_reconnected"] is True
    assert bot.wx is new_wx
    mock_reconnect.assert_awaited_once()
    bot.bot_manager.notify_status_change.assert_awaited_once()


def test_bot_load_effective_config_uses_config_service_snapshot(mock_config):
    mock_service = _build_config_service(mock_config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        bot = WeChatBot("config.yaml")

    loaded = bot._load_effective_config()

    assert loaded == mock_config
    mock_service.get_snapshot.assert_called_once_with(
        config_path="config.yaml",
        force_reload=False,
    )
    mock_service.sync_default_config_snapshot.assert_called_once_with(
        mock_config,
        config_path="config.yaml",
    )


@pytest.mark.asyncio
async def test_reload_runtime_config_without_new_config_uses_config_service_reload():
    current_config = {
        "bot": {
            "config_reload_mode": "auto",
            "config_reload_debounce_ms": 500,
            "reload_ai_client_module": False,
        },
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    next_config = {
        "bot": {
            "config_reload_mode": "watchdog",
            "config_reload_debounce_ms": 900,
            "reload_ai_client_module": False,
        },
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": TEST_LOG_PATH, "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    mock_service = _build_config_service(current_config)
    mock_service.reload.return_value = _build_snapshot(next_config)

    with patch("backend.bot.get_config_service", return_value=mock_service):
        bot = WeChatBot("config.yaml")

    bot.bot_manager = _build_mock_bot_manager()
    bot.config = current_config
    bot._apply_config()
    bot.api_signature = "same-signature"
    bot.runtime_preset_name = "Ollama"
    bot._ensure_config_reload_watcher = MagicMock()
    bot._ensure_vector_memory = MagicMock()
    bot._schedule_export_rag_sync = AsyncMock()

    with patch("backend.bot.compute_api_signature", return_value="same-signature"), \
         patch("backend.bot.get_file_mtime", return_value=123456.0):
        result = await bot.reload_runtime_config()

    assert result["success"] is True
    mock_service.reload.assert_called_once_with(config_path="config.yaml")
    mock_service.sync_default_config_snapshot.assert_called_once_with(
        next_config,
        config_path="config.yaml",
    )
    bot._ensure_config_reload_watcher.assert_called_once()
    bot.bot_manager.notify_status_change.assert_awaited_once()
    assert bot.bot_cfg["config_reload_mode"] == "watchdog"


@pytest.mark.asyncio
async def test_handle_event_voice_transcription_failure_sends_configured_reply():
    bot = WeChatBot("config.yaml")
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()
    bot.config = {"bot": {}, "api": {}, "logging": {}, "agent": {}}
    bot.bot_cfg = {"voice_to_text": True, "voice_to_text_fail_reply": "voice failed"}

    event = SimpleNamespace(
        chat_name="chat",
        sender="user",
        content="[voice]",
        msg_type="voice",
        is_group=False,
        is_self=False,
        raw_item=object(),
        timestamp=None,
    )
    wx = MagicMock()

    with patch("backend.bot.should_respond", return_value=(True, "")), \
         patch("backend.bot.should_reply_with_reason", return_value=(True, "ok")), \
         patch("backend.bot.transcribe_voice_message", new=AsyncMock(return_value=(None, "bad audio"))), \
         patch("backend.bot.send_message", return_value=(True, None)) as mock_send:
        await bot.handle_event(wx, event)

    mock_send.assert_called_once_with(wx, "chat", "voice failed", bot.bot_cfg)


def test_build_incoming_broadcast_payload_uses_friend_chat_id_and_bot_recipient():
    event = SimpleNamespace(
        chat_name="Alice",
        sender="wxid_alice",
        content="hello",
        is_group=False,
        timestamp=123.0,
    )

    payload = build_incoming_broadcast_payload(event)

    assert payload["chat_id"] == "friend:Alice"
    assert payload["recipient"] == "Bot"
    assert payload["timestamp"] == 123.0


def test_build_outgoing_broadcast_payload_uses_reply_metadata():
    event = SimpleNamespace(
        chat_name="Alice",
        sender="wxid_alice",
        content="hello",
        is_group=False,
        timestamp=123.0,
    )

    payload = build_outgoing_broadcast_payload(
        chat_id="friend:Alice",
        event=event,
        reply_text="done",
        response_metadata={"model": "test-model"},
    )

    assert payload["chat_id"] == "friend:Alice"
    assert payload["sender"] == "Bot"
    assert payload["recipient"] == "Alice"
    assert payload["metadata"]["model"] == "test-model"


def test_build_reply_metadata_includes_retrieval_summary():
    bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot.reply_quality_tracker = MagicMock()
    bot.runtime_preset_name = "Test"
    bot.ai_client = SimpleNamespace(
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
        provider_id="",
        base_url="",
    )

    prepared = SimpleNamespace(
        response_metadata={},
        timings={},
        trace={},
        memory_context=[
            {"role": "system", "content": "Relevant past memories:\n1. hello", "hit_count": 2},
            {
                "role": "system",
                "content": "以下内容来自你与当前联系人的真实历史聊天，仅用于模仿你本人常用语气、措辞和节奏，\n1. hi",
            },
        ],
    )
    event = SimpleNamespace(chat_name="Alice", sender="wxid_alice")

    with patch("backend.bot.estimate_exchange_tokens", return_value=(8, 12, 20)), \
         patch("backend.bot.get_pricing_catalog") as mock_catalog:
        mock_catalog.return_value.resolve_price.return_value = None
        metadata = bot._build_reply_metadata(
            prepared=prepared,
            event=event,
            chat_id="friend:Alice",
            user_text="hello",
            reply_text="done",
            streamed=False,
        )

    assert metadata["retrieval"]["augmented"] is True
    assert metadata["retrieval"]["runtime_hit_count"] == 2
    assert metadata["retrieval"]["export_rag_used"] is True


def test_reply_quality_status_summarizes_session_counters():
    bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot._notify_runtime_status_changed = MagicMock()
    bot.reply_quality_tracker = MagicMock()
    bot.reply_quality_tracker.get_recent_summaries.return_value = {
        "24h": {"attempted": 6, "successful": 5, "success_rate": 83.3, "helpful_count": 2},
        "7d": {"attempted": 20, "successful": 15, "success_rate": 75.0, "unhelpful_count": 3},
    }

    bot._record_reply_attempt()
    bot._record_reply_attempt()
    bot._record_reply_success({
        "delayed_reply": True,
        "retrieval": {
            "augmented": True,
            "runtime_hit_count": 3,
        },
    })
    bot._record_reply_empty()
    bot._record_reply_failure()

    quality = bot.get_runtime_status()["reply_quality"]

    assert quality["attempted"] == 2
    assert quality["successful"] == 1
    assert quality["empty"] == 1
    assert quality["failed"] == 1
    assert quality["delayed"] == 1
    assert quality["retrieval_augmented"] == 1
    assert quality["retrieval_hit_count"] == 3
    assert quality["success_rate"] == 50.0
    assert quality["history_24h"]["success_rate"] == 83.3
    assert quality["history_24h"]["helpful_count"] == 2
    assert quality["history_7d"]["success_rate"] == 75.0
    assert quality["history_7d"]["unhelpful_count"] == 3
    assert "回复成功率 50.0%" in quality["status_text"]


def test_apply_reply_feedback_change_updates_session_counters():
    bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot._notify_runtime_status_changed = MagicMock()

    bot.apply_reply_feedback_change("", "helpful")
    bot.apply_reply_feedback_change("helpful", "unhelpful")
    bot.apply_reply_feedback_change("unhelpful", "")

    assert bot.reply_quality_stats["helpful_count"] == 0
    assert bot.reply_quality_stats["unhelpful_count"] == 0
    assert bot._notify_runtime_status_changed.call_count == 3


@pytest.mark.asyncio
async def test_handle_control_command_pause_replies_and_updates_pause_state():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {
        "control_commands_enabled": True,
        "control_reply_visible": True,
        "control_command_prefix": "/",
        "control_allowed_users": [],
    }
    bot.wx_lock = asyncio.Lock()
    bot.bot_manager = _build_mock_bot_manager()
    event = SimpleNamespace(chat_name="chat", sender="owner", content="/pause lunch", is_group=False)
    wx = MagicMock()

    command_result = SimpleNamespace(
        should_reply=True,
        command="pause",
        args=["lunch"],
        response="已暂停",
    )

    with patch("backend.bot_event_flow.parse_control_command", return_value=command_result), \
         patch("backend.bot_event_flow.send_message", return_value=(True, None)) as mock_send:
        handled = await bot._handle_control_command(wx, event, trace_id="trace-1")

    assert handled is True
    bot.bot_manager.apply_pause_state.assert_awaited_once_with(
        True,
        reason="lunch",
        propagate_to_bot=False,
    )
    mock_send.assert_called_once_with(wx, "chat", "已暂停", bot.bot_cfg)


@pytest.mark.asyncio
async def test_send_text_message_propagates_transport_failure():
    bot = WeChatBot("config.yaml")
    bot.wx = MagicMock()
    bot.wx_lock = asyncio.Lock()
    bot.bot_cfg = {"send_exact_match": True}
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()

    with patch("asyncio.to_thread", new=AsyncMock(return_value=(False, "not found"))):
        result = await bot.send_text_message("missing-chat", "hello")

    assert result["success"] is False
    assert "not found" in result["message"]
    bot.ipc.log_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_smart_reply_uses_natural_split_config():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_deadline_sec": 3.0,
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "natural_split_enabled": True,
        "natural_split_min_chars": 11,
        "natural_split_max_chars": 22,
        "natural_split_max_segments": 4,
        "natural_split_delay_sec": [0.4, 0.9],
        "emoji_policy": "keep",
        "reply_suffix": "",
    }
    bot.ai_client = MagicMock()
    event = SimpleNamespace(chat_name="chat", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.split_reply_naturally", return_value=["seg1", "seg2"]) as mock_split, \
         patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks, \
         patch("backend.bot.random.uniform", return_value=0.5) as mock_uniform, \
         patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        await bot._send_smart_reply(MagicMock(), event, "reply body")

    mock_split.assert_called_once_with("reply body", min_chars=11, max_chars=22, max_segments=4)
    assert mock_send_chunks.await_count == 2
    mock_uniform.assert_called_once_with(0.4, 0.9)
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_process_and_reply_skips_empty_reply_when_invoke_returns_empty():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"reply_deadline_sec": 2.0}
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "Ollama"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )
    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=AsyncMock(return_value=""),
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )
    bot._send_smart_reply = AsyncMock()
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()

    event = SimpleNamespace(
        chat_name="文件传输助手",
        sender="wxid_xxx",
        content="1",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    await bot._process_and_reply(MagicMock(), event, "1", "1")

    bot.ai_client.invoke.assert_awaited_once_with(prepared)
    bot._send_smart_reply.assert_not_awaited()
    bot.ai_client.finalize_request.assert_not_awaited()
    assert prepared.response_metadata["empty_reply"] is True


@pytest.mark.asyncio
async def test_process_and_reply_uses_direct_reply_when_invoke_has_content():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"reply_deadline_sec": 2.0}
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "Ollama"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )
    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=AsyncMock(return_value="direct reply"),
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )
    bot._send_smart_reply = AsyncMock(return_value="direct reply")
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()
    bot.evaluate_outgoing_reply_policy = AsyncMock(return_value={"should_queue": False})

    event = SimpleNamespace(
        chat_name="文件传输助手",
        sender="wxid_xxx",
        content="1",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    await bot._process_and_reply(MagicMock(), event, "1", "1")

    bot.ai_client.invoke.assert_awaited_once_with(prepared)
    bot._send_smart_reply.assert_awaited_once()
    bot.ai_client.finalize_request.assert_awaited_once()
    assert prepared.response_metadata.get("deadline_missed") is not True


@pytest.mark.asyncio
async def test_process_and_reply_uses_direct_reply_when_deadline_disabled():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"reply_deadline_sec": 0}
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "Qwen"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )
    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=AsyncMock(return_value="direct reply"),
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )
    bot._send_smart_reply = AsyncMock(return_value="direct reply")
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()
    bot.evaluate_outgoing_reply_policy = AsyncMock(return_value={"should_queue": False})

    event = SimpleNamespace(
        chat_name="chat",
        sender="user",
        content="hello",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    await bot._process_and_reply(MagicMock(), event, "hello", "hello")

    bot.ai_client.invoke.assert_awaited_once_with(prepared)
    bot._send_smart_reply.assert_awaited_once_with(
        ANY,
        event,
        "direct reply",
        trace_id=ANY,
    )
    bot.ai_client.finalize_request.assert_awaited_once()
    assert prepared.response_metadata.get("deadline_missed") is not True
    assert prepared.response_metadata.get("delayed_reply") is not True
    assert prepared.response_metadata.get("response_deadline_sec") is None
    assert not bot.pending_tasks


@pytest.mark.asyncio
async def test_process_and_reply_propagates_invoke_failure_when_deadline_disabled():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"reply_deadline_sec": 0}
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "Qwen"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )
    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=AsyncMock(side_effect=RuntimeError("Request timed out.")),
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )
    bot._send_smart_reply = AsyncMock()
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()

    event = SimpleNamespace(
        chat_name="chat",
        sender="user",
        content="hello",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    with pytest.raises(RuntimeError, match="Request timed out\\."):
        await bot._process_and_reply(MagicMock(), event, "hello", "hello")

    bot.ai_client.invoke.assert_awaited_once_with(prepared)
    bot._send_smart_reply.assert_not_awaited()
    bot.ai_client.finalize_request.assert_not_awaited()
    assert prepared.response_metadata["response_error"] == "Request timed out."
    assert prepared.response_metadata.get("deadline_missed") is not True
    assert prepared.response_metadata.get("delayed_reply") is not True
    assert not bot.pending_tasks
    bot._set_ai_health.assert_called_with(
        "error",
        "Last AI call failed: Request timed out.",
        error=True,
    )


@pytest.mark.asyncio
async def test_send_smart_reply_raises_when_send_reply_chunks_fails():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "emoji_policy": "keep",
        "reply_suffix": "",
    }
    event = SimpleNamespace(chat_name="chat", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(False, "transport down"))):
        with pytest.raises(RuntimeError, match="发送失败"):
            await bot._send_smart_reply(MagicMock(), event, "reply body")


@pytest.mark.asyncio
async def test_approve_pending_reply_keeps_pending_when_send_fails():
    bot = WeChatBot("config.yaml")
    bot.bot_manager = _build_mock_bot_manager()
    bot.memory = MagicMock()
    bot.memory.get_pending_reply = AsyncMock(
        return_value={
            "id": 7,
            "chat_id": "friend:alice",
            "draft_reply": "draft",
            "metadata": {"trace_id": "trace-1"},
            "status": "pending",
        }
    )
    bot.memory.update_pending_reply = AsyncMock(
        return_value={
            "id": 7,
            "chat_id": "friend:alice",
            "draft_reply": "edited reply",
            "metadata": {"trace_id": "trace-1", "approval_error": "transport down"},
            "status": "pending",
        }
    )
    bot.memory.resolve_pending_reply = AsyncMock()
    bot.expire_stale_pending_replies = AsyncMock()
    bot.refresh_pending_reply_stats = AsyncMock(return_value={"pending": 1})
    bot._notify_runtime_status_changed = MagicMock()
    bot._record_pending_reply_resolved = MagicMock()
    bot._record_reply_attempt = MagicMock()
    bot._rehydrate_pending_prepared_request = MagicMock(
        return_value=SimpleNamespace(
            event=SimpleNamespace(chat_name="alice", sender="alice"),
            user_text="hello",
        )
    )
    bot._send_smart_reply = AsyncMock(side_effect=RuntimeError("transport down"))
    bot._finalize_reply_delivery = AsyncMock()
    bot.wx = MagicMock()
    bot.ai_client = MagicMock()

    result = await bot.approve_pending_reply(7, edited_reply="edited reply")

    assert result["success"] is False
    assert "approve failed" in result["message"]
    bot.memory.update_pending_reply.assert_awaited_once()
    bot.memory.resolve_pending_reply.assert_not_awaited()
    bot._record_pending_reply_resolved.assert_not_called()
    bot._record_reply_attempt.assert_not_called()
    bot._finalize_reply_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_and_reply_schedules_delayed_reply_when_invoke_exceeds_deadline():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"reply_deadline_sec": 0.01}
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "test"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )

    async def _slow_invoke(_prepared):
        await asyncio.sleep(0.15)
        return "late reply"

    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=_slow_invoke,
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )
    bot._send_smart_reply = AsyncMock(return_value="late reply")
    bot.evaluate_outgoing_reply_policy = AsyncMock(return_value={"should_queue": False})

    event = SimpleNamespace(
        chat_name="chat",
        sender="user",
        content="hello",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    await bot._process_and_reply(MagicMock(), event, "hello", "hello")
    if bot.pending_tasks:
        await asyncio.gather(*list(bot.pending_tasks), return_exceptions=True)

    bot._send_smart_reply.assert_awaited_once_with(
        ANY,
        event,
        "late reply",
        trace_id=ANY,
    )
    bot.ai_client.finalize_request.assert_awaited_once()
    assert prepared.response_metadata["deadline_missed"] is True
    assert prepared.response_metadata["delayed_reply"] is True
