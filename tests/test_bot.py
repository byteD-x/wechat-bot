
import pytest
import asyncio
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

@pytest.mark.asyncio
async def test_bot_initialization(mock_config):
    # Mock load_config
    with patch("backend.bot.load_config", return_value=mock_config):
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
    with patch("backend.bot.load_config", side_effect=Exception("Config load failed")):
        with patch("backend.bot.get_file_mtime", return_value=123456.0):
            bot = WeChatBot("config.yaml")
            wx = await bot.initialize()
            assert wx is None

@pytest.mark.asyncio
async def test_bot_initialization_vector_memory_error(mock_config):
    # Test vector memory init failure
    config_with_rag = mock_config.copy()
    config_with_rag["bot"]["rag_enabled"] = True
    
    with patch("backend.bot.load_config", return_value=config_with_rag):
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
    assert status["compat_mode"] is False
    assert "3.9.12.51" in status["transport_warning"]

@pytest.mark.asyncio
async def test_bot_run_loop(mock_config):
    mock_bot_manager = _build_mock_bot_manager()
    with patch("backend.bot.load_config", return_value=mock_config), \
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
    with patch("backend.bot.load_config", return_value=mock_config), \
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
