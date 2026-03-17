import json
from pathlib import Path

from backend.config import DEFAULT_CONFIG
from backend.core.config_audit import build_reload_plan, diff_config_paths, get_effect_for_path
from backend.core.config_service import ConfigService
from backend.utils.config import load_config_py


def test_config_service_update_override_persists_and_prunes_removed_paths(tmp_path):
    service = ConfigService()
    override_path = tmp_path / "config_override.json"
    override_path.write_text(
        json.dumps(
            {
                "bot": {
                    "compat_ui_enabled": True,
                    "memory_seed_limit": 20,
                    "stream_reply": True,
                    "reply_timeout_fallback_text": "timeout fallback",
                    "reply_empty_fallback_text": "empty fallback",
                    "stream_buffer_chars": 64,
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
    assert "stream_reply" not in persisted.get("bot", {})
    assert "stream_buffer_chars" not in persisted.get("bot", {})
    assert "reply_timeout_fallback_text" not in persisted.get("bot", {})
    assert "reply_empty_fallback_text" not in persisted.get("bot", {})
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
    assert get_effect_for_path("bot.contact_prompt_update_frequency")["mode"] == "live"
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
    assert "stream_reply" not in bot
    assert "stream_buffer_chars" not in bot
    assert "contact_prompt_update_frequency" in bot
    assert "stream_chunk_max_chars" not in bot
    assert "reply_timeout_fallback_text" not in bot
    assert "reply_error_fallback_text" not in bot
    assert "reply_empty_fallback_text" not in bot
    assert "history_strategy" not in agent
    assert "streaming_enabled" not in agent


def test_config_service_write_default_config_file_syncs_non_sensitive_fields(tmp_path):
    service = ConfigService()
    config_path = tmp_path / "config.py"
    config_path.write_text(
        "\n".join(
            [
                "from copy import deepcopy",
                "CONFIG = {",
                "    'api': {",
                "        'api_key': 'YOUR_API_KEY',",
                "        'active_preset': 'OpenAI',",
                "        'presets': [",
                "            {'name': 'OpenAI', 'provider_id': 'openai', 'api_key': 'YOUR_OPENAI_KEY', 'allow_empty_key': False},",
                "            {'name': 'Ollama', 'provider_id': 'ollama', 'api_key': '', 'allow_empty_key': True},",
                "        ],",
                "    },",
                "    'bot': {'self_name': 'old-name', 'allow_filehelper_self_message': False},",
                "    'logging': {'level': 'INFO', 'file': 'test.log', 'max_bytes': 1024, 'backup_count': 1, 'format': 'text', 'log_message_content': False, 'log_reply_content': False},",
                "    'agent': {'enabled': True, 'langsmith_api_key': ''},",
                "}",
                "DEFAULT_CONFIG = deepcopy(CONFIG)",
            ]
        ),
        encoding="utf-8",
    )

    payload = {
        "api": {
            "api_key": "sk-live-secret",
            "active_preset": "DeepSeek",
            "presets": [
                {
                    "name": "DeepSeek",
                    "provider_id": "deepseek",
                    "api_key": "sk-deepseek-secret",
                    "allow_empty_key": False,
                },
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "api_key": "",
                    "allow_empty_key": True,
                },
            ],
        },
        "bot": {
            "self_name": "new-name",
            "allow_filehelper_self_message": True,
        },
        "logging": {
            "level": "DEBUG",
            "file": "test.log",
            "max_bytes": 1024,
            "backup_count": 1,
            "format": "text",
            "log_message_content": False,
            "log_reply_content": False,
        },
        "agent": {
            "enabled": True,
            "langsmith_api_key": "lsv2-secret",
        },
    }

    sanitized = service._sanitize_default_config_payload(payload)
    service._write_default_config_file(str(config_path), sanitized)
    written = load_config_py(str(config_path))

    assert written["bot"]["self_name"] == "new-name"
    assert written["bot"]["allow_filehelper_self_message"] is True
    assert written["api"]["active_preset"] == "DeepSeek"
    assert written["api"]["api_key"] == "YOUR_API_KEY"
    assert written["api"]["presets"][0]["api_key"] == "YOUR_DEEPSEEK_KEY"
    assert written["api"]["presets"][1]["api_key"] == ""
    assert written["agent"]["langsmith_api_key"] == ""


def test_sync_default_config_snapshot_skips_identical_write(tmp_path):
    service = ConfigService()
    config_path = tmp_path / "config.py"
    config_path.write_text(
        "\n".join(
            [
                "from copy import deepcopy",
                "CONFIG = {'api': {'api_key': 'YOUR_API_KEY', 'active_preset': 'OpenAI', 'presets': []}, 'bot': {'self_name': 'tester'}, 'logging': {'level': 'INFO', 'file': 'test.log', 'max_bytes': 1024, 'backup_count': 1, 'format': 'text', 'log_message_content': False, 'log_reply_content': False}, 'agent': {'enabled': True, 'langsmith_api_key': ''}}",
                "DEFAULT_CONFIG = deepcopy(CONFIG)",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "api": {"api_key": "sk-live-secret", "active_preset": "OpenAI", "presets": []},
        "bot": {"self_name": "tester"},
        "logging": {"level": "INFO", "file": "test.log", "max_bytes": 1024, "backup_count": 1, "format": "text", "log_message_content": False, "log_reply_content": False},
        "agent": {"enabled": True, "langsmith_api_key": ""},
    }

    assert service.sync_default_config_snapshot(payload, config_path=str(config_path)) is True
    assert service.sync_default_config_snapshot(payload, config_path=str(config_path)) is False


def test_save_effective_config_persists_api_keys_to_data_file(tmp_path):
    service = ConfigService()
    config_path = tmp_path / "config.py"
    override_path = tmp_path / "config_override.json"
    api_keys_path = tmp_path / "api_keys.py"
    config_path.write_text(
        "\n".join(
            [
                "from copy import deepcopy",
                "CONFIG = {",
                "    'api': {",
                "        'base_url': 'https://api.openai.com/v1',",
                "        'api_key': 'YOUR_API_KEY',",
                "        'model': 'gpt-5-mini',",
                "        'alias': '小欧',",
                "        'timeout_sec': 8,",
                "        'max_retries': 1,",
                "        'temperature': 0.6,",
                "        'max_tokens': 512,",
                "        'allow_empty_key': False,",
                "        'active_preset': 'OpenAI',",
                "        'presets': [",
                "            {'name': 'OpenAI', 'provider_id': 'openai', 'alias': '小欧', 'base_url': 'https://api.openai.com/v1', 'api_key': 'YOUR_OPENAI_KEY', 'model': 'gpt-5-mini', 'timeout_sec': 10, 'max_retries': 2, 'temperature': 0.6, 'max_tokens': 512, 'allow_empty_key': False},",
                "            {'name': 'Ollama', 'provider_id': 'ollama', 'alias': '本地', 'base_url': 'http://127.0.0.1:11434/v1', 'api_key': '', 'model': 'qwen3', 'timeout_sec': 20, 'max_retries': 1, 'temperature': 0.6, 'max_tokens': 512, 'allow_empty_key': True},",
                "        ],",
                "    },",
                "    'bot': {'self_name': 'tester', 'allow_filehelper_self_message': True},",
                "    'logging': {'level': 'INFO', 'file': 'test.log', 'max_bytes': 1024, 'backup_count': 1, 'format': 'text', 'log_message_content': False, 'log_reply_content': False},",
                "    'agent': {'enabled': True, 'graph_mode': 'state_graph', 'langsmith_enabled': False, 'langsmith_project': 'wechat-chat', 'langsmith_endpoint': None, 'langsmith_api_key': None, 'retriever_top_k': 3, 'retriever_score_threshold': 1.0, 'retriever_rerank_mode': 'lightweight', 'retriever_cross_encoder_model': None, 'retriever_cross_encoder_device': None, 'embedding_cache_ttl_sec': 300.0, 'background_fact_extraction_enabled': True, 'emotion_fast_path_enabled': True, 'max_parallel_retrievers': 3},",
                "}",
                "DEFAULT_CONFIG = deepcopy(CONFIG)",
            ]
        ),
        encoding="utf-8",
    )
    api_keys_path.write_text(
        "API_KEYS = {'default': '', 'presets': {}}\n",
        encoding="utf-8",
    )

    snapshot = service.save_effective_config(
        {
            "api": {
                "active_preset": "OpenAI",
                "presets": [
                    {
                        "name": "OpenAI",
                        "provider_id": "openai",
                        "alias": "小欧",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-openai-secret",
                        "model": "gpt-5-mini",
                        "timeout_sec": 10,
                        "max_retries": 2,
                        "temperature": 0.6,
                        "max_tokens": 512,
                        "allow_empty_key": False,
                    },
                    {
                        "name": "Ollama",
                        "provider_id": "ollama",
                        "alias": "本地",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "api_key": "",
                        "model": "qwen3",
                        "timeout_sec": 20,
                        "max_retries": 1,
                        "temperature": 0.6,
                        "max_tokens": 512,
                        "allow_empty_key": True,
                    },
                ],
            },
            "bot": {
                "allow_filehelper_self_message": False,
            },
        },
        config_path=str(config_path),
        override_path=str(override_path),
        api_keys_path=str(api_keys_path),
    )

    persisted_override = json.loads(override_path.read_text(encoding="utf-8"))
    persisted_api_keys = service._read_api_keys_file(str(api_keys_path))
    written_default = load_config_py(str(config_path))

    assert "api_key" not in persisted_override.get("api", {})
    assert "api_key" not in persisted_override["api"]["presets"][0]
    assert persisted_api_keys["presets"]["OpenAI"] == "sk-openai-secret"
    assert written_default["api"]["presets"][0]["api_key"] == "YOUR_OPENAI_KEY"
    assert written_default["bot"]["allow_filehelper_self_message"] is False
