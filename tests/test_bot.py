
import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock
from backend.bot import WeChatBot


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
    return service

@pytest.mark.asyncio
async def test_bot_initialization(mock_config):
    mock_service = _build_config_service(mock_config)
    with patch("backend.bot.get_config_service", return_value=mock_service):
        with patch("backend.bot.get_file_mtime", return_value=123456.0):
            bot = WeChatBot("config.yaml")

            # Mock internal components
            bot.memory = MagicMock()

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
            bot.memory = MagicMock()
            
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
        "transport_backend": "hook_wcferry",
        "required_wechat_version": "",
    }

    with patch(
        "backend.bot.get_last_transport_error",
        return_value="已安装 wcferry 仅支持微信 3.9.12.51，当前为 3.9.12.17",
    ):
        status = bot.get_transport_status()

    assert status["transport_backend"] == "hook_wcferry"
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
        bot.memory = MagicMock()
        bot.memory.close = AsyncMock()
        await bot.initialize()
        
        bot._stop_event = asyncio.Event()
        
        # Stop after one iteration
        async def mock_sleep(delay):
            print(f"DEBUG: mock_sleep called with {delay}")
            bot._stop_event.set()
            
        with patch("asyncio.sleep", side_effect=mock_sleep):
             with patch("backend.bot.IPCManager"):
                 # Mock to_thread for GetNextNewMessage
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
        bot.memory = MagicMock()
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
    }
    next_config = {
        "bot": {
            "config_reload_mode": "watchdog",
            "config_reload_debounce_ms": 900,
            "reload_ai_client_module": False,
        },
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "agent": {"enabled": True},
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
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
        raw_item=object(),
        timestamp=None,
    )
    wx = MagicMock()

    with patch("backend.bot.should_respond", return_value=(True, "")), \
         patch("backend.bot.should_reply", return_value=True), \
         patch("backend.bot.transcribe_voice_message", new=AsyncMock(return_value=(None, "bad audio"))), \
         patch("backend.bot.send_message", return_value=(True, None)) as mock_send:
        await bot.handle_event(wx, event)

    mock_send.assert_called_once_with(wx, "chat", "voice failed", bot.bot_cfg)


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
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "reply_quote_mode": "none",
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
async def test_send_smart_reply_raises_when_send_reply_chunks_fails():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "reply_quote_mode": "none",
        "emoji_policy": "keep",
        "reply_suffix": "",
    }
    event = SimpleNamespace(chat_name="chat", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(False, "transport down"))):
        with pytest.raises(RuntimeError, match="发送失败"):
            await bot._send_smart_reply(MagicMock(), event, "reply body")


@pytest.mark.asyncio
async def test_stream_smart_reply_raises_when_send_reply_chunks_fails():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "stream_buffer_chars": 1,
        "stream_chunk_max_chars": 10,
        "reply_quote_mode": "none",
        "emoji_policy": "keep",
        "reply_suffix": "",
    }

    async def _stream_reply(_prepared):
        yield "hello"

    bot.ai_client = SimpleNamespace(stream_reply=_stream_reply)
    event = SimpleNamespace(chat_name="chat", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(False, "transport down"))):
        with pytest.raises(RuntimeError, match="发送失败"):
            await bot._stream_smart_reply(MagicMock(), event, MagicMock())
