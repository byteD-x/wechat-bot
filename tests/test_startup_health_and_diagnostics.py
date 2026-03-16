from backend.bot_manager import get_bot_manager


def test_startup_suppresses_diagnostics_and_marks_wechat_connecting():
    manager = get_bot_manager()

    prev_is_running = manager.is_running
    prev_last_issue = manager._last_issue
    prev_bot = manager.bot
    try:
        manager.is_running = True
        manager._last_issue = None
        manager.bot = None

        status = {
            "startup": {"active": True, "stage": "connect_wechat"},
            "transport_status": "disconnected",
            "transport_warning": "",
            "ai_health": {"status": "unknown", "detail": ""},
        }

        assert manager._build_diagnostics(status) is None

        checks = manager._build_health_checks(status)
        assert checks["wechat"]["status"] == "warning"
        assert "连接" in (checks["wechat"].get("message") or "")
    finally:
        manager.is_running = prev_is_running
        manager._last_issue = prev_last_issue
        manager.bot = prev_bot
