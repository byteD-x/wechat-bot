import os
import tempfile
import time
from types import SimpleNamespace

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
            "compat_mode": False,
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


def test_bot_manager_health_checks_report_compat_mode_and_missing_db_connection():
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
            "compat_mode": True,
            "ai_health": {
                "status": "warning",
                "detail": "Compatibility-only AI probe",
            },
        })

        assert checks["ai"]["level"] == "warning"
        assert checks["wechat"]["status"] == "warning"
        assert "cannot be fully verified" in checks["wechat"]["message"]
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
