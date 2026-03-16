import json
from pathlib import Path

from backend.config import DEFAULT_CONFIG
from backend.core.config_audit import build_reload_plan, diff_config_paths, get_effect_for_path
from backend.core.config_service import ConfigService


def test_config_service_update_override_persists_and_prunes_removed_paths(tmp_path):
    service = ConfigService()
    override_path = tmp_path / "config_override.json"
    override_path.write_text(
        json.dumps(
            {
                "bot": {
                    "compat_ui_enabled": True,
                    "memory_seed_limit": 20,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = service.update_override(
        {
            "bot": {"self_name": "tester"},
            "agent": {"history_strategy": "legacy"},
        },
        override_path=str(override_path),
    )

    persisted = json.loads(override_path.read_text(encoding="utf-8"))
    assert snapshot.version >= 1
    assert persisted["bot"]["self_name"] == "tester"
    assert "compat_ui_enabled" not in persisted.get("bot", {})
    assert "memory_seed_limit" not in persisted.get("bot", {})
    assert "history_strategy" not in persisted.get("agent", {})


def test_config_service_get_snapshot_caches_per_path():
    service = ConfigService()
    config = {
        "api": {"base_url": "http://localhost", "api_key": "sk-test", "model": "gpt-4o"},
        "bot": {"self_name": "tester"},
        "logging": {"level": "INFO", "file": "test.log"},
        "agent": {"enabled": True},
    }

    published = service.publish(config, config_path="backend/config.py")
    cached = service.get_snapshot(config_path="backend/config.py")

    assert cached is published


def test_config_audit_diff_and_effects():
    before = {"bot": {"filter_mute": True}, "api": {"active_preset": "OpenAI"}}
    after = {"bot": {"filter_mute": False}, "api": {"active_preset": "DeepSeek"}}

    changed = diff_config_paths(before, after)
    plan = build_reload_plan(changed)

    assert changed == ["api.active_preset", "bot.filter_mute"]
    assert get_effect_for_path("bot.profile_update_frequency")["mode"] == "live"
    assert any(item["component"] == "ai_client" for item in plan)


def test_default_config_drops_removed_legacy_paths():
    bot = DEFAULT_CONFIG["bot"]
    agent = DEFAULT_CONFIG["agent"]

    assert "capability_strict" not in bot
    assert "memory_seed_on_first_reply" not in bot
    assert "memory_seed_limit" not in bot
    assert "memory_seed_load_more" not in bot
    assert "memory_seed_load_more_interval_sec" not in bot
    assert "memory_seed_group" not in bot
    assert "history_log_interval_sec" not in bot
    assert "poll_interval_sec" not in bot
    assert "history_strategy" not in agent
