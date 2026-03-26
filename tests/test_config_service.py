import asyncio
import io
import json
from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import backend.shared_config as shared_config_module
from backend.core.config_audit import build_reload_plan, diff_config_paths, get_effect_for_path
from backend.core.config_cli import cmd_probe, cmd_validate
from backend.core.config_service import ConfigService
from backend.shared_config import build_default_config, migrate_legacy_config, validate_shared_config
from backend.core.config_probe import probe_config


def _make_preset(name="OpenAI", api_key="sk-test", provider_id="openai"):
    return {
        "name": name,
        "provider_id": provider_id,
        "alias": name,
        "base_url": "https://api.openai.com/v1",
        "api_key": api_key,
        "model": "gpt-5-mini",
        "embedding_model": "",
        "timeout_sec": 10.0,
        "max_retries": 1,
        "temperature": 0.6,
        "max_tokens": 512,
        "allow_empty_key": False,
    }


def _write_shared_config(tmp_path, monkeypatch, payload=None):
    data_root = tmp_path / "data"
    monkeypatch.setenv("WECHAT_BOT_DATA_DIR", str(data_root))
    data_root.mkdir(parents=True, exist_ok=True)
    config_path = data_root / "app_config.json"
    config = validate_shared_config(payload or build_default_config(data_root=data_root), data_root=data_root)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path, config, data_root


def test_config_service_save_effective_config_writes_shared_json(tmp_path, monkeypatch):
    config_path, _, _ = _write_shared_config(
        tmp_path,
        monkeypatch,
        payload={
            **build_default_config(data_root=tmp_path / "seed-data"),
            "api": {
                **build_default_config(data_root=tmp_path / "seed-data")["api"],
                "active_preset": "OpenAI",
                "presets": [_make_preset()],
            },
        },
    )
    service = ConfigService()

    snapshot = service.save_effective_config(
        {
            "bot": {"self_name": "tester"},
            "services": {"growth_tasks_enabled": True},
        },
        config_path=str(config_path),
    )

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert snapshot.bot["self_name"] == "tester"
    assert persisted["bot"]["self_name"] == "tester"
    assert persisted["services"]["growth_tasks_enabled"] is True
    assert persisted["schema_version"] == 1


def test_config_service_prunes_removed_legacy_paths(tmp_path, monkeypatch):
    config_path, _, _ = _write_shared_config(tmp_path, monkeypatch)
    service = ConfigService()

    snapshot = service.save_effective_config(
        {
            "bot": {
                "stream_reply": True,
                "stream_buffer_chars": 64,
                "reply_timeout_fallback_text": "timeout",
            },
            "agent": {"history_strategy": "legacy"},
        },
        config_path=str(config_path),
    )

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "stream_reply" not in persisted["bot"]
    assert "stream_buffer_chars" not in persisted["bot"]
    assert "reply_timeout_fallback_text" not in persisted["bot"]
    assert "history_strategy" not in persisted["agent"]
    assert "stream_reply" not in snapshot.bot


def test_config_service_get_snapshot_caches_per_path(tmp_path, monkeypatch):
    config_path, _, _ = _write_shared_config(tmp_path, monkeypatch)
    service = ConfigService()

    first = service.get_snapshot(config_path=str(config_path))
    second = service.get_snapshot(config_path=str(config_path))

    assert first is second


def test_config_audit_diff_and_effects():
    before = {"bot": {"filter_mute": True}, "api": {"active_preset": "OpenAI"}}
    after = {"bot": {"filter_mute": False}, "api": {"active_preset": "DeepSeek"}}

    changed = diff_config_paths(before, after)
    plan = build_reload_plan(changed)

    assert changed == ["api.active_preset", "bot.filter_mute"]
    assert get_effect_for_path("bot.profile_update_frequency")["mode"] == "live"
    assert get_effect_for_path("bot.contact_prompt_update_frequency")["mode"] == "live"
    assert any(item["component"] == "ai_client" for item in plan)


def test_validate_shared_config_normalizes_paths_to_data_root(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("WECHAT_BOT_DATA_DIR", str(data_root))
    payload = build_default_config(data_root=data_root)
    payload["bot"]["memory_db_path"] = "data/chat_memory.db"
    payload["bot"]["export_rag_dir"] = "data/chat_exports/聊天记录"
    payload["logging"]["file"] = "data/logs/app.log"

    normalized = validate_shared_config(payload, data_root=data_root)

    assert normalized["bot"]["memory_db_path"] == str((data_root / "chat_memory.db").resolve())
    assert normalized["bot"]["export_rag_dir"] == str((data_root / "chat_exports" / "聊天记录").resolve())
    assert normalized["logging"]["file"] == str((data_root / "logs" / "app.log").resolve())


def test_migrate_legacy_config_writes_shared_config_and_backup(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    (project_root / "backend").mkdir(parents=True, exist_ok=True)
    (project_root / "data").mkdir(parents=True, exist_ok=True)
    (project_root / "shared").mkdir(parents=True, exist_ok=True)
    (project_root / "backend" / "config.py").write_text("# legacy\n", encoding="utf-8")
    (project_root / "data" / "config_override.json").write_text("{}", encoding="utf-8")
    (project_root / "data" / "api_keys.py").write_text("API_KEYS = {}\n", encoding="utf-8")
    (project_root / "prompt_overrides.py").write_text("PROMPT_OVERRIDES = {}\n", encoding="utf-8")
    (project_root / "shared" / "model_catalog.json").write_text(
        (Path(__file__).resolve().parents[1] / "shared" / "model_catalog.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    data_root = tmp_path / "shared-data"
    monkeypatch.setenv("WECHAT_BOT_DATA_DIR", str(data_root))
    monkeypatch.setattr(shared_config_module, "get_project_root", lambda: project_root)

    base_config = deepcopy(shared_config_module.DEFAULT_CONFIG)
    base_config["api"]["active_preset"] = "OpenAI"
    base_config["api"]["presets"] = [_make_preset(api_key="")]
    base_config["bot"]["memory_db_path"] = "data/chat_memory.db"
    base_config["bot"]["export_rag_dir"] = "data/chat_exports/聊天记录"
    base_config["logging"]["file"] = "data/logs/wechat_bot.log"
    monkeypatch.setattr(shared_config_module, "DEFAULT_CONFIG", base_config)
    monkeypatch.setattr(
        shared_config_module,
        "_apply_api_keys",
        lambda payload: payload["api"]["presets"][0].__setitem__("api_key", "migrated-demo-key"),
    )
    monkeypatch.setattr(
        shared_config_module,
        "_apply_prompt_overrides",
        lambda payload: payload["bot"].__setitem__("system_prompt_overrides", {"Alice": "Hi"}),
    )
    monkeypatch.setattr(
        shared_config_module,
        "_apply_config_overrides",
        lambda payload: payload["api"].__setitem__("active_preset", "DeepSeek"),
    )
    monkeypatch.setattr(shared_config_module, "_auto_select_active_preset", lambda payload: None)

    result = migrate_legacy_config(force=True)
    config_path = Path(shared_config_module.get_app_config_path())
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    backups = sorted((data_root / "backups").glob("legacy-config-*"))

    assert result["api"]["presets"][0]["api_key"] == ""
    assert result["api"]["presets"][0]["credential_ref"].startswith("provider-auth::openai::api_key::")
    assert persisted["api"]["active_preset"] == "DeepSeek"
    assert persisted["api"]["presets"][0]["api_key"] == ""
    assert persisted["api"]["presets"][0]["credential_ref"] == result["api"]["presets"][0]["credential_ref"]
    assert persisted["bot"]["system_prompt_overrides"] == {"Alice": "Hi"}
    assert Path(persisted["bot"]["memory_db_path"]).is_absolute()
    assert backups
    assert (backups[-1] / "config_override.json").exists()
    assert (backups[-1] / "api_keys.py").exists()


def test_config_cli_validate_merges_patch_without_web_service(tmp_path, monkeypatch, capsys):
    config_path, _, _ = _write_shared_config(
        tmp_path,
        monkeypatch,
        payload={
            **build_default_config(data_root=tmp_path / "seed-data"),
            "api": {
                **build_default_config(data_root=tmp_path / "seed-data")["api"],
                "active_preset": "OpenAI",
                "presets": [_make_preset()],
            },
        },
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"services": {"growth_tasks_enabled": True}})))

    exit_code = cmd_validate(Namespace(base_path=str(config_path), stdin=True))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["config"]["services"]["growth_tasks_enabled"] is True


def test_config_cli_probe_success_without_web_service(tmp_path, monkeypatch, capsys):
    config_path, _, _ = _write_shared_config(
        tmp_path,
        monkeypatch,
        payload={
            **build_default_config(data_root=tmp_path / "seed-data"),
            "api": {
                **build_default_config(data_root=tmp_path / "seed-data")["api"],
                "active_preset": "OpenAI",
                "presets": [_make_preset()],
            },
        },
    )

    async def _fake_probe_config(config, preset_name=""):
        return True, config.get("api", {}).get("active_preset", ""), "连接测试成功（已验证服务可访问）"

    monkeypatch.setattr("backend.core.config_cli.probe_config", _fake_probe_config)

    exit_code = cmd_probe(Namespace(base_path=str(config_path), stdin=False, preset_name=""))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["preset_name"] == "OpenAI"
    assert "已验证服务可访问" in payload["message"]


def test_config_cli_probe_failure_without_web_service(tmp_path, monkeypatch, capsys):
    config_path, _, _ = _write_shared_config(
        tmp_path,
        monkeypatch,
        payload={
            **build_default_config(data_root=tmp_path / "seed-data"),
            "api": {
                **build_default_config(data_root=tmp_path / "seed-data")["api"],
                "active_preset": "OpenAI",
                "presets": [_make_preset()],
            },
        },
    )

    async def _fake_probe_config(config, preset_name=""):
        return False, preset_name, "连接测试失败，请检查配置或网络"

    monkeypatch.setattr("backend.core.config_cli.probe_config", _fake_probe_config)

    exit_code = cmd_probe(Namespace(base_path=str(config_path), stdin=False, preset_name="OpenAI"))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["success"] is False
    assert payload["preset_name"] == "OpenAI"


def test_probe_config_allows_ollama_cloud_model(monkeypatch):
    monkeypatch.setattr(
        "backend.core.factory._fetch_ollama_models",
        lambda _base_url, timeout_sec=3.0: [
            {
                "name": "deepseek-v3.2:cloud",
                "model": "deepseek-v3.2:cloud",
                "remote_host": "https://ollama.com",
            }
        ],
    )
    class _FakeClient:
        async def probe_fast(self):
            return True, "completion"

        async def close(self):
            return None

    monkeypatch.setattr("backend.core.config_probe.build_ai_client", lambda prepared, bot_cfg: _FakeClient())

    success, preset_name, message = asyncio.run(
        probe_config(
            {
                "api": {
                    "active_preset": "Ollama",
                    "presets": [
                        {
                            "name": "Ollama",
                            "provider_id": "ollama",
                            "base_url": "http://127.0.0.1:11434/v1",
                            "api_key": "",
                            "model": "deepseek-v3.2:cloud",
                            "allow_empty_key": True,
                        }
                    ],
                },
                "bot": {},
            },
            "Ollama",
        )
    )

    assert success is True
    assert preset_name == "Ollama"
    assert "连接测试成功" in message
