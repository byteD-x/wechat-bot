import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from backend.bot_manager import BotManager
from backend.utils.config_watcher import ConfigReloadWatcher


def test_config_reload_watcher_debounces_manual_events():
    with tempfile.TemporaryDirectory() as temp_dir:
        watched = os.path.join(temp_dir, "config.py")
        watcher = ConfigReloadWatcher(
            [watched],
            debounce_ms=50,
            preferred_mode="polling",
        )

        assert watcher.mode == "polling"
        assert watcher.notify_path_changed(watched) is True
        assert watcher.consume_change(now=time.monotonic()) is False
        assert watcher.consume_change(now=time.monotonic() + 0.06) is True
        assert watcher.consume_change(now=time.monotonic() + 0.12) is False


def test_config_reload_watcher_updates_runtime_settings():
    with tempfile.TemporaryDirectory() as temp_dir:
        watched = os.path.join(temp_dir, "config.py")
        other = os.path.join(temp_dir, "override.json")
        watcher = ConfigReloadWatcher([watched], debounce_ms=10, preferred_mode="polling")
        watcher.update(paths=[watched, other], debounce_ms=25, preferred_mode="auto")

        status = watcher.get_status()
        assert status["preferred_mode"] == "auto"
        assert status["debounce_ms"] == 25
        assert os.path.abspath(other) in status["watch_paths"]


def test_bot_manager_health_checks_include_dashboard_fields():
    manager = BotManager.get_instance()
    original_bot = manager.bot
    original_memory = manager.memory_manager
    try:
        manager.bot = SimpleNamespace(
            ai_client=object(),
            memory=SimpleNamespace(db_path="data/chat_memory.db", _conn=object()),
        )
        manager.memory_manager = manager.bot.memory
        checks = manager._build_health_checks({
            "model": "gpt-test",
            "transport_status": "connected",
            "transport_warning": "",
            "ai_health": {
                "status": "healthy",
                "detail": "Last AI call succeeded",
            },
        })

        assert checks["ai"]["status"] == "healthy"
        assert checks["ai"]["level"] == "healthy"
        assert checks["ai"]["message"] == "Last AI call succeeded"
        assert checks["wechat"]["level"] == "healthy"
        assert checks["database"]["message"] == "data/chat_memory.db"
    finally:
        manager.bot = original_bot
        manager.memory_manager = original_memory


def test_bot_manager_health_checks_report_connected_transport_and_missing_db_connection():
    manager = BotManager.get_instance()
    original_bot = manager.bot
    original_memory = manager.memory_manager
    original_running = manager.is_running
    try:
        manager.is_running = True
        manager.bot = SimpleNamespace(
            ai_client=object(),
            memory=SimpleNamespace(db_path="data/chat_memory.db", _conn=None),
        )
        manager.memory_manager = manager.bot.memory
        checks = manager._build_health_checks({
            "transport_status": "connected",
            "transport_warning": "",
            "ai_health": {
                "status": "warning",
                "detail": "Transport connected but runtime check is degraded",
            },
        })

        assert checks["ai"]["level"] == "warning"
        assert checks["wechat"]["status"] == "healthy"
        assert "Verified active WeChat connection" in checks["wechat"]["message"]
        assert checks["database"]["status"] == "warning"
        assert "no active connection" in checks["database"]["message"]
    finally:
        manager.bot = original_bot
        manager.memory_manager = original_memory
        manager.is_running = original_running


def test_bot_manager_export_metrics_includes_core_values(monkeypatch):
    manager = BotManager.get_instance()
    monkeypatch.setattr(manager, "get_status", lambda: {
        "running": True,
        "is_paused": False,
        "today_replies": 3,
        "today_tokens": 120,
        "total_replies": 30,
        "total_tokens": 5000,
        "startup": {"progress": 100},
        "config_reload": {"mode": "watchdog"},
        "system_metrics": {
            "cpu_percent": 12.5,
            "process_memory_mb": 256.0,
            "system_memory_percent": 42.0,
            "pending_tasks": 2,
            "merge_pending_chats": 1,
            "merge_pending_messages": 4,
            "ai_latency_ms": 333.3,
        },
        "health_checks": {
            "ai": {"status": "healthy"},
            "wechat": {"status": "degraded"},
        },
    })

    metrics = manager.export_metrics()
    assert "wechat_bot_running 1" in metrics
    assert "wechat_bot_today_replies 3" in metrics
    assert 'wechat_bot_config_reload_mode{mode="watchdog"} 1' in metrics
    assert 'wechat_bot_health_check{component="wechat",status="degraded"} 1' in metrics


def test_bot_manager_status_log_message_is_human_readable():
    manager = BotManager.get_instance()
    message = manager._build_status_log_message({
        "running": True,
        "is_paused": False,
        "uptime": "00:03:21",
        "transport_status": "connected",
        "runtime_preset": "DeepSeek-R1",
        "health_checks": {
            "ai": {"status": "healthy", "message": "Last AI call succeeded"},
            "wechat": {"status": "healthy", "message": "Verified active WeChat connection"},
        },
        "startup": {"active": False},
        "diagnostics": None,
    })

    assert "机器人运行中" in message
    assert "已运行 00:03:21" in message
    assert "微信已连接" in message
    assert "AI可用：DeepSeek-R1" in message


def test_bot_manager_status_log_message_surfaces_warnings():
    manager = BotManager.get_instance()
    message = manager._build_status_log_message({
        "running": True,
        "is_paused": False,
        "transport_status": "disconnected",
        "transport_warning": "注入失败，请重新连接微信",
        "health_checks": {
            "ai": {"status": "warning", "message": "模型返回空内容，已回退"},
            "wechat": {"status": "error", "message": "WeChat disconnected"},
        },
        "startup": {"active": False},
        "diagnostics": {
            "level": "error",
            "title": "微信连接已断开",
            "detail": "当前未检测到有效的微信连接。",
        },
    })

    assert "微信异常：注入失败，请重新连接微信" in message
    assert "AI状态：模型返回空内容，已回退" in message
    assert "诊断：微信连接已断开" in message


def test_bot_manager_log_status_change_skips_duplicate_snapshot():
    manager = BotManager.get_instance()
    original_snapshot = manager._last_status_log_snapshot
    try:
        manager._last_status_log_snapshot = None
        status = {
            "running": True,
            "is_paused": False,
            "uptime": "00:00:10",
            "transport_status": "connected",
            "runtime_preset": "Qwen3",
            "health_checks": {
                "ai": {"status": "healthy", "message": "ok"},
                "wechat": {"status": "healthy", "message": "ok"},
                "database": {"status": "healthy", "message": "ok"},
            },
            "startup": {"active": False},
            "diagnostics": None,
        }

        with patch("backend.bot_manager.logger.info") as mock_info:
            manager._log_status_change(status)
            manager._log_status_change(status)

        mock_info.assert_called_once()
    finally:
        manager._last_status_log_snapshot = original_snapshot


def test_bot_manager_get_status_includes_growth_runtime_fields():
    manager = BotManager.get_instance()
    original_bot = manager.bot
    original_running = manager.is_running
    original_status_cache = manager._status_cache
    original_status_cache_time = manager._status_cache_time
    try:
        manager.is_running = True
        manager._status_cache = None
        manager._status_cache_time = 0.0
        manager.bot = SimpleNamespace(
            get_export_rag_status=lambda: {"enabled": True},
            get_agent_status=lambda: {
                "engine": "langgraph",
                "growth_mode": "background_only",
                "growth_tasks_pending": 2,
                "last_growth_error": "emotion step boom",
                "ai_health": {"status": "healthy", "detail": "ok"},
            },
            get_transport_status=lambda: {"transport_status": "connected", "transport_warning": ""},
            get_runtime_status=lambda: {"pending_tasks": 1, "merge_pending_chats": 0, "merge_pending_messages": 0},
        )

        status = manager.get_status()

        assert status["growth_mode"] == "background_only"
        assert status["growth_tasks_pending"] == 2
        assert status["last_growth_error"] == "emotion step boom"
        assert status["config_snapshot"]["version"] >= 1
        assert status["config_snapshot"]["valid"] is True
    finally:
        manager.bot = original_bot
        manager.is_running = original_running
        manager._status_cache = original_status_cache
        manager._status_cache_time = original_status_cache_time
