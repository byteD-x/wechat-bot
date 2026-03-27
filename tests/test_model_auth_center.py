from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.model_auth.services.center import ModelAuthCenterService
from backend.model_auth.services.health import run_profile_health_check
from backend.model_auth.providers.registry import get_provider_definition
from backend.model_auth.services.migration import (
    _select_runtime_profile,
    ensure_provider_auth_center_config,
    hydrate_runtime_settings,
    project_provider_auth_center,
)
from backend.model_auth.domain.enums import AuthMethodType
from backend.model_auth.domain.models import AuthMethodDefinition
from backend.model_auth.services.status import build_provider_overview_cards
from backend.model_auth.sync.orchestrator import LocalAuthSyncOrchestrator
from backend.model_auth.storage.credential_store import CredentialStore


def _base_config() -> dict:
    return {
        "schema_version": 1,
        "api": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "YOUR_API_KEY",
            "auth_mode": "api_key",
            "model": "gpt-5-mini",
            "alias": "小欧",
            "timeout_sec": 8,
            "max_retries": 1,
            "temperature": 0.6,
            "max_tokens": 512,
            "allow_empty_key": False,
            "active_preset": "OpenAI",
            "presets": [
                {
                    "name": "OpenAI",
                    "provider_id": "openai",
                    "alias": "小欧",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "demo-openai-test-key",
                    "auth_mode": "api_key",
                    "model": "gpt-5-mini",
                    "timeout_sec": 8,
                    "max_retries": 1,
                    "temperature": 0.6,
                    "max_tokens": 512,
                    "allow_empty_key": False,
                }
            ],
        },
        "bot": {"self_name": "测试", "system_prompt": ""},
        "logging": {"level": "INFO", "file": "data/logs/test.log", "max_bytes": 1024, "backup_count": 1, "format": "text"},
        "agent": {},
        "services": {"growth_tasks_enabled": False},
    }


def _broken_credential_entry(provider_id: str, method_type: str, *, payload: str = "bm90LWpzb24=") -> dict:
    return {
        "provider_id": provider_id,
        "method_type": method_type,
        "updated_at": 0,
        "format": "dpapi",
        "payload": payload,
    }


def _write_google_gemini_auth_files(tmp_path, *, project_id: str | None) -> tuple[str, str]:
    creds = {
        "access_token": "google-access-token-123",
        "refresh_token": "google-refresh-token-456",
        "expiry_date": 4102444800000,
    }
    accounts = {
        "active": "gemini@example.com",
    }
    if project_id:
        creds["project_id"] = project_id
        accounts["project_id"] = project_id
    creds_path = tmp_path / "google-oauth.json"
    accounts_path = tmp_path / "google-accounts.json"
    creds_path.write_text(json.dumps(creds), encoding="utf-8")
    accounts_path.write_text(json.dumps(accounts), encoding="utf-8")
    return str(creds_path), str(accounts_path)


def test_migrate_legacy_api_key_into_provider_auth_center(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)

    center = config["api"]["provider_auth_center"]
    openai_entry = center["providers"]["openai"]
    assert openai_entry["selected_profile_id"].startswith("openai:api_key:")
    assert openai_entry["auth_profiles"][0]["credential_ref"].startswith("provider-auth::openai::api_key::")
    assert config["api"]["presets"][0]["api_key"] == ""
    assert config["api"]["presets"][0]["credential_ref"] == openai_entry["auth_profiles"][0]["credential_ref"]
    assert store.get(openai_entry["auth_profiles"][0]["credential_ref"]).payload["api_key"] == "demo-openai-test-key"


def test_hydrate_runtime_settings_reads_secure_api_key(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    record = store.set(
        "provider-auth::openai::api_key::primary",
        provider_id="openai",
        method_type="api_key",
        payload={"api_key": "demo-secure-value"},
    )
    hydrated = hydrate_runtime_settings(
        {"auth_mode": "api_key", "api_key": "", "credential_ref": record.ref},
        credential_store=store,
    )
    assert hydrated["api_key"] == "demo-secure-value"


def test_hydrate_runtime_settings_treats_unreadable_secret_as_missing(tmp_path, caplog):
    ref = "provider-auth::openai::api_key::broken"
    (tmp_path / "creds.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    ref: _broken_credential_entry("openai", "api_key"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = CredentialStore(str(tmp_path / "creds.json"))

    caplog.set_level("WARNING")

    assert store.get(ref) is None
    assert store.has(ref) is False

    hydrated = hydrate_runtime_settings(
        {"auth_mode": "api_key", "api_key": "", "credential_ref": ref},
        credential_store=store,
    )

    assert hydrated["api_key"] == ""
    assert "读取认证凭据失败" in caplog.text


def test_api_key_profile_with_unreadable_secret_becomes_invalid_and_reconfigurable(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    entry = config["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "api_key")
    ref = profile["credential_ref"]
    (tmp_path / "creds.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    ref: _broken_credential_entry("openai", "api_key"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    api_key_state = next(state for state in openai_card.auth_states if state.method_id == "api_key")
    action_ids = {item["id"] for item in api_key_state.actions}

    assert api_key_state.status.value == "invalid"
    assert api_key_state.summary == "API Key 需要重新配置"
    assert api_key_state.detail == "这条已保存的 API Key 无法读取，请重新填写。"
    assert "show_api_key_form" in action_ids


def test_project_provider_auth_center_respects_selected_profile(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    center = config["api"]["provider_auth_center"]
    openai_entry = center["providers"]["openai"]
    openai_entry["auth_profiles"].append(
        {
            "id": "openai:codex_local:chatgpt",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "ChatGPT 本机登录",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {},
        }
    )
    openai_entry["selected_profile_id"] = "openai:codex_local:chatgpt"

    projected = project_provider_auth_center(config["api"])
    openai_preset = next(item for item in projected["presets"] if item["provider_id"] == "openai")
    assert openai_preset["auth_mode"] == "oauth"
    assert openai_preset["oauth_provider"] == "openai_codex"
    assert openai_preset["provider_auth_profile_id"] == "openai:codex_local:chatgpt"


def test_select_runtime_profile_prefers_oauth_over_api_key_in_auto_mode(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    entry = config["api"]["provider_auth_center"]["providers"]["openai"]
    api_profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "api_key")
    entry["auth_profiles"].append(
        {
            "id": "openai:codex_local:chatgpt",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "ChatGPT OAuth",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {"runtime_ready": True},
        }
    )
    entry["selected_profile_id"] = api_profile["id"]
    entry.setdefault("metadata", {})
    entry["metadata"]["selection_mode"] = "auto"

    profile, _ = _select_runtime_profile(entry)

    assert profile is not None
    assert profile["id"] == "openai:codex_local:chatgpt"


def test_select_runtime_profile_falls_back_to_api_key_when_manual_oauth_unavailable(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    entry = config["api"]["provider_auth_center"]["providers"]["openai"]
    api_profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "api_key")
    entry["auth_profiles"].append(
        {
            "id": "openai:codex_local:chatgpt",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "ChatGPT OAuth",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {"runtime_ready": False},
        }
    )
    entry["selected_profile_id"] = "openai:codex_local:chatgpt"
    entry.setdefault("metadata", {})
    entry["metadata"]["selection_mode"] = "manual"

    profile, _ = _select_runtime_profile(entry)

    assert profile is not None
    assert profile["id"] == api_profile["id"]


def test_project_provider_auth_center_uses_method_runtime_defaults_for_kimi_local_auth(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["kimi"] = {
        "provider_id": "kimi",
        "legacy_preset_name": "Kimi",
        "alias": "",
        "default_model": "kimi-thinking-preview",
        "default_base_url": "https://api.moonshot.cn/v1",
        "selected_profile_id": "kimi:kimi_code_local:work",
        "auth_profiles": [
            {
                "id": "kimi:kimi_code_local:work",
                "provider_id": "kimi",
                "method_id": "kimi_code_local",
                "method_type": "local_import",
                "label": "Kimi 本机登录",
                "credential_ref": "",
                "credential_source": "local_config_file",
                "binding": {
                    "source": "kimi_code_credentials",
                    "source_type": "kimi_code_local",
                    "credential_source": "local_config_file",
                    "sync_policy": "follow",
                    "follow_local_auth": True,
                },
                "metadata": {"runtime_ready": True},
            }
        ],
        "metadata": {"project_to_runtime": True},
    }

    projected = project_provider_auth_center(config["api"])
    kimi_preset = next(item for item in projected["presets"] if item["provider_id"] == "kimi")

    assert kimi_preset["auth_mode"] == "oauth"
    assert kimi_preset["oauth_provider"] == "kimi_code_local"
    assert kimi_preset["base_url"] == "https://api.kimi.com/coding/v1"
    assert kimi_preset["model"] == "kimi-for-coding"
    assert kimi_preset["provider_auth_profile_id"] == "kimi:kimi_code_local:work"


def test_migrate_moonshot_oauth_profile_into_kimi_provider(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "Kimi OAuth"
    config["api"]["presets"] = [
        {
            "name": "Kimi OAuth",
            "provider_id": "moonshot",
            "alias": "Kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "api_key": "YOUR_API_KEY",
            "auth_mode": "oauth",
            "oauth_provider": "kimi_code_local",
            "oauth_source": "kimi_code_credentials",
            "model": "kimi-k2-turbo-preview",
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    kimi_entry = normalized["api"]["provider_auth_center"]["providers"]["kimi"]
    profile = next(item for item in kimi_entry["auth_profiles"] if item["method_id"] == "kimi_code_local")
    profile.setdefault("metadata", {})["runtime_ready"] = True
    projected = project_provider_auth_center(normalized["api"])
    kimi_preset = next(item for item in projected["presets"] if item["provider_id"] == "kimi")

    assert kimi_entry["selected_profile_id"] == profile["id"]
    assert profile["provider_id"] == "kimi"
    assert kimi_preset["provider_id"] == "kimi"
    assert kimi_preset["oauth_provider"] == "kimi_code_local"
    assert all(item["provider_id"] != "moonshot" for item in projected["presets"])


def test_migrate_moonshot_api_key_profile_into_kimi_provider(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "Moonshot"
    config["api"]["presets"] = [
        {
            "name": "Moonshot",
            "provider_id": "moonshot",
            "alias": "Kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "api_key": "ms-test-key-1234567890",
            "auth_mode": "api_key",
            "model": "kimi-k2-turbo-preview",
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    kimi_entry = normalized["api"]["provider_auth_center"]["providers"]["kimi"]
    profile = next(item for item in kimi_entry["auth_profiles"] if item["method_id"] == "api_key")
    projected = project_provider_auth_center(normalized["api"])
    kimi_preset = next(item for item in projected["presets"] if item["provider_id"] == "kimi")

    assert profile["provider_id"] == "kimi"
    assert kimi_entry["selected_profile_id"] == profile["id"]
    assert kimi_preset["provider_id"] == "kimi"
    assert kimi_preset["auth_mode"] == "api_key"
    assert all(item["provider_id"] != "moonshot" for item in projected["presets"])


def test_migrate_qwen_coding_plan_api_key_into_dedicated_method(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "Qwen Coding Plan"
    config["api"]["presets"] = [
        {
            "name": "Qwen Coding Plan",
            "provider_id": "qwen",
            "alias": "代码助手",
            "base_url": "https://coding.dashscope.aliyuncs.com/v1/chat/completions",
            "api_key": "demo-coding-plan-key",
            "auth_mode": "api_key",
            "model": "qwen3-coder-plus",
            "allow_empty_key": False,
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["qwen"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "coding_plan_api_key")

    assert entry["selected_profile_id"] == profile["id"]
    assert profile["metadata"]["base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert profile["metadata"]["model"] == "qwen3-coder-plus"
    assert store.get(profile["credential_ref"]).payload["api_key"] == "demo-coding-plan-key"


def test_migrate_zhipu_coding_plan_api_key_into_dedicated_method(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "GLM Coding Plan"
    config["api"]["presets"] = [
        {
            "name": "GLM Coding Plan",
            "provider_id": "zhipu",
            "alias": "代码助手",
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
            "api_key": "demo-glm-coding-plan-key",
            "auth_mode": "api_key",
            "model": "glm-5",
            "allow_empty_key": False,
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["zhipu"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "coding_plan_api_key")

    assert entry["selected_profile_id"] == profile["id"]
    assert profile["metadata"]["base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert profile["metadata"]["model"] == "glm-5"
    assert store.get(profile["credential_ref"]).payload["api_key"] == "demo-glm-coding-plan-key"


def test_migrate_kimi_coding_plan_api_key_into_dedicated_method(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "Kimi Coding Plan"
    config["api"]["presets"] = [
        {
            "name": "Kimi Coding Plan",
            "provider_id": "kimi",
            "alias": "代码助手",
            "base_url": "https://api.kimi.com/coding/v1/chat/completions",
            "api_key": "demo-kimi-coding-plan-key",
            "auth_mode": "api_key",
            "model": "kimi-for-coding",
            "allow_empty_key": False,
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["kimi"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "coding_plan_api_key")

    assert entry["selected_profile_id"] == profile["id"]
    assert profile["metadata"]["base_url"] == "https://api.kimi.com/coding/v1"
    assert profile["metadata"]["model"] == "kimi-for-coding"
    assert store.get(profile["credential_ref"]).payload["api_key"] == "demo-kimi-coding-plan-key"


def test_migrate_minimax_coding_plan_api_key_into_dedicated_method(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "MiniMax Coding Plan"
    config["api"]["presets"] = [
        {
            "name": "MiniMax Coding Plan",
            "provider_id": "minimax",
            "alias": "代码助手",
            "base_url": "https://api.minimaxi.com/anthropic/messages",
            "api_key": "demo-minimax-coding-plan-key",
            "auth_mode": "api_key",
            "model": "MiniMax-M2.5",
            "allow_empty_key": False,
        }
    ]

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["minimax"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "coding_plan_api_key")

    assert entry["selected_profile_id"] == profile["id"]
    assert profile["metadata"]["base_url"] == "https://api.minimaxi.com/anthropic"
    assert profile["metadata"]["model"] == "MiniMax-M2.5"
    assert store.get(profile["credential_ref"]).payload["api_key"] == "demo-minimax-coding-plan-key"


def test_provider_overview_marks_local_auth_as_available_and_following(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["openai"]["auth_profiles"] = []
    config["api"]["provider_auth_center"]["providers"]["openai"]["selected_profile_id"] = ""
    monkeypatch.setattr(
        "backend.model_auth.services.status.get_legacy_status_map",
        lambda: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "ChatGPT 工作号",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "_sync_watch_mode": "polling",
                "_sync_refreshed_at": 123,
            }
        },
    )

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    placeholder = next(state for state in openai_card.auth_states if state.method_id == "codex_local")
    assert placeholder.status.value == "available_to_import"

    config["api"]["provider_auth_center"]["providers"]["openai"]["auth_profiles"] = [
        {
            "id": "openai:codex_local:work",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "工作号",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {},
        }
    ]
    config["api"]["provider_auth_center"]["providers"]["openai"]["selected_profile_id"] = "openai:codex_local:work"
    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    state = next(item for item in openai_card.auth_states if item.default_selected)
    assert state.status.value == "following_local_auth"
    assert openai_card.metadata["provider_sync"]["code"] == "following_local_auth"
    assert openai_card.metadata["provider_sync"]["watch_mode"] == "polling"


def test_provider_overview_marks_local_account_switch_in_sync_metadata(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["openai"]["auth_profiles"] = [
        {
            "id": "openai:codex_local:work",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "工作账号",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "account_label": "旧工作号",
                "metadata": {
                    "local_sync": {
                        "account_key": "old-work@example.com",
                        "last_seen_at": 123,
                    }
                },
            },
            "metadata": {},
        }
    ]
    config["api"]["provider_auth_center"]["providers"]["openai"]["selected_profile_id"] = "openai:codex_local:work"
    monkeypatch.setattr(
        "backend.model_auth.services.status.get_legacy_status_map",
        lambda: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "新工作号",
                "account_email": "new-work@example.com",
                "auth_path": str(tmp_path / "codex-auth.json"),
            }
        },
    )

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    state = next(item for item in openai_card.auth_states if item.default_selected)

    assert state.metadata["local_sync"]["account_switched"] is True
    assert state.metadata["local_sync"]["account_label"] == "新工作号"
    assert state.account_email == "new-work@example.com"
    assert state.account_label == "new-work@example.com"
    assert openai_card.selected_label == "new-work@example.com"


def test_provider_overview_builds_shared_source_group_metadata_for_google_qwen_and_kimi(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr(
        "backend.model_auth.services.status.get_legacy_status_map",
        lambda: {
            "google_gemini_cli": {
                "detected": True,
                "configured": True,
                "account_email": "gemini@example.com",
                "account_label": "Gemini 工作账号",
            },
            "qwen_oauth": {
                "detected": True,
                "configured": True,
                "account_email": "qwen@example.com",
                "account_label": "Qwen 工作账号",
            },
            "kimi_code_local": {
                "detected": True,
                "configured": True,
                "account_email": "kimi@example.com",
                "account_label": "Kimi 工作账号",
            },
        },
    )

    cards = build_provider_overview_cards(config, credential_store=store)

    google_card = next(card for card in cards if card.provider.id == "google")
    google_oauth = next(state for state in google_card.auth_states if state.method_id == "google_oauth")
    google_local = next(state for state in google_card.auth_states if state.method_id == "gemini_cli_local")
    assert google_oauth.metadata["source_group"]["id"] == google_local.metadata["source_group"]["id"]
    assert google_oauth.metadata["source_group"]["shared_auth_provider_id"] == "google_gemini_cli"
    assert google_oauth.metadata["source_group"]["account_key"] == "gemini@example.com"

    qwen_card = next(card for card in cards if card.provider.id == "qwen")
    qwen_local = next(state for state in qwen_card.auth_states if state.method_id == "qwen_local")
    qwen_oauth = next(state for state in qwen_card.auth_states if state.method_id == "qwen_oauth")
    assert qwen_local.metadata["source_group"]["id"] == qwen_oauth.metadata["source_group"]["id"]
    assert qwen_local.metadata["source_group"]["shared_auth_provider_id"] == "qwen_oauth"
    assert qwen_local.metadata["source_group"]["account_key"] == "qwen@example.com"

    kimi_card = next(card for card in cards if card.provider.id == "kimi")
    kimi_local = next(state for state in kimi_card.auth_states if state.method_id == "kimi_code_local")
    kimi_oauth = next(state for state in kimi_card.auth_states if state.method_id == "kimi_code_oauth")
    assert kimi_local.metadata["source_group"]["id"] == kimi_oauth.metadata["source_group"]["id"]
    assert kimi_local.metadata["source_group"]["shared_auth_provider_id"] == "kimi_code_local"
    assert kimi_local.metadata["source_group"]["account_key"] == "kimi@example.com"


def test_provider_overview_keeps_different_google_accounts_in_separate_source_groups(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    google_entry = config["api"]["provider_auth_center"]["providers"]["google"]
    google_entry["auth_profiles"] = [
        {
            "id": "google:google_oauth:work",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "work@example.com",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "account_label": "work@example.com",
                "metadata": {
                    "account_email": "work@example.com",
                    "local_sync": {
                        "account_key": "work@example.com",
                    },
                },
            },
            "metadata": {"runtime_ready": False},
        },
        {
            "id": "google:google_oauth:other",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "other@example.com",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "account_label": "other@example.com",
                "metadata": {
                    "account_email": "other@example.com",
                    "local_sync": {
                        "account_key": "other@example.com",
                    },
                },
            },
            "metadata": {"runtime_ready": False},
        },
    ]
    google_entry["selected_profile_id"] = "google:google_oauth:work"
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    google_card = next(card for card in cards if card.provider.id == "google")
    group_ids = {
        state.metadata["source_group"]["id"]
        for state in google_card.auth_states
        if state.method_id == "google_oauth"
    }

    assert group_ids == {
        "google_gemini_cli:work@example.com",
        "google_gemini_cli:other@example.com",
    }


def test_provider_overview_marks_web_session_local_auth_as_available_and_following(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["doubao"]["auth_profiles"] = []
    config["api"]["provider_auth_center"]["providers"]["doubao"]["selected_profile_id"] = ""
    monkeypatch.setattr(
        "backend.model_auth.services.status.get_legacy_status_map",
        lambda: {
            "doubao_session": {
                "detected": True,
                "configured": True,
                "account_label": "Chrome Default browser session",
                "browser_name": "Chrome",
                "browser_profile": "Default",
                "cookie_count": 6,
                "auth_cookie_count": 2,
                "session_path": str(tmp_path / "doubao-cookies.sqlite"),
                "indexeddb_path": str(tmp_path / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"),
                "local_storage_path": str(tmp_path / "Local Storage" / "leveldb"),
                "private_storage_path": str(tmp_path / "Doubao" / "User Data"),
                "watch_paths": [
                    str(tmp_path / "doubao-cookies.sqlite"),
                    str(tmp_path / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"),
                    str(tmp_path / "Local Storage" / "leveldb"),
                ],
                "_sync_watch_mode": "watchdog",
                "_sync_refreshed_at": 456,
            }
        },
    )

    cards = build_provider_overview_cards(config, credential_store=store)
    doubao_card = next(card for card in cards if card.provider.id == "doubao")
    placeholder = next(state for state in doubao_card.auth_states if state.method_id == "doubao_web_session")
    action_ids = {item["id"] for item in placeholder.actions}

    assert placeholder.status.value == "available_to_import"
    assert "bind_local_auth" in action_ids
    assert placeholder.binding.metadata["private_storage_path"].replace("\\", "/").endswith("Doubao/User Data")

    config["api"]["provider_auth_center"]["providers"]["doubao"]["auth_profiles"] = [
        {
            "id": "doubao:doubao_web_session:local-browser",
            "provider_id": "doubao",
            "method_id": "doubao_web_session",
            "method_type": "web_session",
            "label": "Doubao Browser",
            "credential_ref": "",
            "credential_source": "browser_session",
            "binding": {
                "source": "browser_session",
                "source_type": "doubao_session",
                "credential_source": "browser_session",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "locator_path": str(tmp_path / "doubao-cookies.sqlite"),
                "account_label": "Chrome Default browser session",
                "metadata": {
                    "indexeddb_path": str(tmp_path / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"),
                    "local_storage_path": str(tmp_path / "Local Storage" / "leveldb"),
                },
            },
            "metadata": {},
        }
    ]
    config["api"]["provider_auth_center"]["providers"]["doubao"]["selected_profile_id"] = (
        "doubao:doubao_web_session:local-browser"
    )
    cards = build_provider_overview_cards(config, credential_store=store)
    doubao_card = next(card for card in cards if card.provider.id == "doubao")
    state = next(item for item in doubao_card.auth_states if item.default_selected)
    configured_action_ids = {item["id"] for item in state.actions}

    assert state.status.value == "following_local_auth"
    assert doubao_card.metadata["provider_sync"]["code"] == "following_local_auth"
    assert doubao_card.metadata["provider_sync"]["watch_mode"] == "watchdog"
    assert state.binding.metadata["indexeddb_path"].endswith(".indexeddb.leveldb")
    assert state.binding.metadata["private_storage_path"].replace("\\", "/").endswith("Doubao/User Data")
    assert "show_session_form" in configured_action_ids
    assert "start_browser_auth" in configured_action_ids


def test_configured_api_key_profile_keeps_api_key_form_action(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    api_key_state = next(
        state
        for state in openai_card.auth_states
        if state.method_id == "api_key" and state.default_selected
    )
    action_ids = {item["id"] for item in api_key_state.actions}

    assert api_key_state.status.value == "connected"
    assert "show_api_key_form" in action_ids


def test_provider_overview_exposes_provider_level_sync_and_health_summary(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")

    assert openai_card.metadata["provider_sync"]["code"] == "not_detected"
    assert openai_card.metadata["provider_health"]["code"] == "not_checked"
    assert openai_card.metadata["provider_counts"]["connected"] >= 1


def test_provider_card_sort_prioritizes_connected_before_available(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})
    cards = build_provider_overview_cards(config, credential_store=store)
    assert cards[0].provider.id == "openai"


def test_registry_exposes_google_oauth_and_local_import_methods():
    provider = get_provider_definition("google")
    assert provider is not None
    method_types = {method.id: method.type.value for method in provider.auth_methods}
    methods = {method.id: method for method in provider.auth_methods}
    assert method_types["google_oauth"] == "oauth"
    assert method_types["gemini_cli_local"] == "local_import"
    assert methods["google_oauth"].requires_fields == ("oauth_project_id",)
    assert methods["gemini_cli_local"].requires_fields == ("oauth_project_id",)


def test_registry_exposes_claude_oauth_and_local_import_methods():
    provider = get_provider_definition("anthropic")
    assert provider is not None
    method_types = {method.id: method.type.value for method in provider.auth_methods}
    methods = {method.id: method for method in provider.auth_methods}

    assert method_types["claude_code_oauth"] == "oauth"
    assert method_types["claude_code_local"] == "local_import"
    assert method_types["claude_vertex_local"] == "local_import"
    assert methods["claude_code_oauth"].metadata["browser_flow_completion"] == "local_rescan"
    assert methods["claude_code_local"].metadata["browser_flow_completion"] == "local_rescan"
    assert methods["claude_vertex_local"].requires_fields == ("oauth_project_id", "oauth_location")


def test_registry_models_kimi_as_oauth_and_local_import_instead_of_web_session():
    provider = get_provider_definition("kimi")
    legacy_alias = get_provider_definition("moonshot")
    bailian_alias = get_provider_definition("bailian")
    assert provider is not None
    assert legacy_alias is not None
    assert bailian_alias is not None
    method_ids = {method.id for method in provider.auth_methods}
    assert legacy_alias.id == "kimi"
    assert bailian_alias.id == "qwen"
    assert "kimi_code_oauth" in method_ids
    assert "kimi_code_local" in method_ids
    assert "kimi_web_session" not in method_ids


def test_registry_health_check_capability_tracks_runtime_supported_methods():
    openai = get_provider_definition("openai")
    yuanbao = get_provider_definition("yuanbao")

    assert openai is not None
    assert yuanbao is not None
    assert openai.capability.supports_health_check is True
    assert yuanbao.capability.supports_health_check is False


def test_select_runtime_profile_accepts_runtime_method_without_legacy_provider_id(monkeypatch):
    method = AuthMethodDefinition(
        id="browser_bound",
        type=AuthMethodType.OAUTH,
        label="Browser Bound",
        runtime_supported=True,
        auth_provider_id="custom_browser_adapter",
        legacy_provider_id="",
    )
    monkeypatch.setattr(
        "backend.model_auth.services.migration.get_provider_method",
        lambda provider_id, method_id: method if provider_id == "custom" and method_id == "browser_bound" else None,
    )
    monkeypatch.setattr(
        "backend.model_auth.services.migration.get_provider_definition",
        lambda provider_id: {"id": provider_id},
    )

    profile, context = _select_runtime_profile(
        {
            "provider_id": "custom",
            "selected_profile_id": "custom:browser_bound:default",
            "auth_profiles": [
                {
                    "id": "custom:browser_bound:default",
                    "provider_id": "custom",
                    "method_id": "browser_bound",
                    "method_type": "oauth",
                    "label": "Browser Bound",
                    "metadata": {"runtime_ready": True},
                }
            ],
        }
    )

    assert profile is not None
    assert profile["id"] == "custom:browser_bound:default"
    assert context["method"].auth_provider_id == "custom_browser_adapter"


def test_placeholder_actions_use_method_aware_labels_for_non_oauth_browser_flows(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    local_state = next(state for state in openai_card.auth_states if state.method_id == "codex_local")
    action_labels = {item["id"]: item["label"] for item in local_state.actions}

    assert action_labels["start_browser_auth"] == "打开 ChatGPT / Codex 登录页"
    assert "通过 OAuth 登录" not in action_labels.values()


def test_placeholder_actions_preserve_oauth_wording_for_real_oauth_methods(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    qwen_card = next(card for card in cards if card.provider.id == "qwen")
    oauth_state = next(state for state in qwen_card.auth_states if state.method_id == "qwen_oauth")
    action_labels = {item["id"]: item["label"] for item in oauth_state.actions}

    assert action_labels["start_browser_auth"] == "通过 Qwen OAuth 登录"


def test_shared_auth_source_group_metadata_reuses_same_group_id_for_shared_login_sources(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    shared_statuses = {
        "google_oauth": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Google 工作号",
            "account_email": "work@example.com",
            "local_source_label": "google_gemini_cli",
            "message": "已检测到 Google 登录。",
        },
        "gemini_cli_local": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Gemini 工作号",
            "account_email": "work@example.com",
            "local_source_label": "google_gemini_cli",
            "message": "已检测到 Gemini CLI 登录。",
        },
        "qwen_local": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Qwen 本机号",
            "account_email": "qwen@example.com",
            "local_source_label": "qwen_oauth",
            "message": "已检测到 Qwen 本机登录。",
        },
        "qwen_oauth": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Qwen OAuth 号",
            "account_email": "qwen@example.com",
            "local_source_label": "qwen_oauth",
            "message": "已检测到 Qwen OAuth 登录。",
        },
        "kimi_code_local": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Kimi 本机号",
            "account_email": "kimi@example.com",
            "local_source_label": "kimi_code_local",
            "message": "已检测到 Kimi 本机登录。",
        },
        "kimi_code_oauth": {
            "detected": True,
            "configured": True,
            "runtime_available": True,
            "account_label": "Kimi OAuth 号",
            "account_email": "kimi@example.com",
            "local_source_label": "kimi_code_local",
            "message": "已检测到 Kimi OAuth 登录。",
        },
    }
    monkeypatch.setattr(
        "backend.model_auth.services.status.get_method_local_status",
        lambda method, legacy_statuses=None: deepcopy(shared_statuses.get(method.id, {})),
    )

    cards = build_provider_overview_cards(config, credential_store=store)
    google_card = next(card for card in cards if card.provider.id == "google")
    qwen_card = next(card for card in cards if card.provider.id == "qwen")
    kimi_card = next(card for card in cards if card.provider.id == "kimi")

    google_oauth = next(state for state in google_card.auth_states if state.method_id == "google_oauth")
    google_local = next(state for state in google_card.auth_states if state.method_id == "gemini_cli_local")
    qwen_local = next(state for state in qwen_card.auth_states if state.method_id == "qwen_local")
    qwen_oauth = next(state for state in qwen_card.auth_states if state.method_id == "qwen_oauth")
    kimi_local = next(state for state in kimi_card.auth_states if state.method_id == "kimi_code_local")
    kimi_oauth = next(state for state in kimi_card.auth_states if state.method_id == "kimi_code_oauth")

    assert google_oauth.metadata["source_group"]["id"] == google_local.metadata["source_group"]["id"]
    assert qwen_local.metadata["source_group"]["id"] == qwen_oauth.metadata["source_group"]["id"]
    assert kimi_local.metadata["source_group"]["id"] == kimi_oauth.metadata["source_group"]["id"]
    assert google_oauth.metadata["source_group"]["shared_auth_provider_id"] == "google_gemini_cli"
    assert qwen_oauth.metadata["source_group"]["shared_auth_provider_id"] == "qwen_oauth"
    assert kimi_local.metadata["source_group"]["shared_auth_provider_id"] == "kimi_code_local"


def test_shared_auth_source_group_keeps_different_emails_separate(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["google"]["auth_profiles"] = [
        {
            "id": "google:google_oauth:work",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "工作账号",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "account_label": "工作账号",
                "metadata": {"account_email": "work@example.com"},
            },
            "metadata": {"runtime_ready": True},
        },
        {
            "id": "google:gemini_cli_local:other",
            "provider_id": "google",
            "method_id": "gemini_cli_local",
            "method_type": "local_import",
            "label": "私人账号",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
                "account_label": "私人账号",
                "metadata": {"account_email": "other@example.com"},
            },
            "metadata": {"runtime_ready": True},
        },
    ]
    config["api"]["provider_auth_center"]["providers"]["google"]["selected_profile_id"] = "google:google_oauth:work"
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(config, credential_store=store)
    google_card = next(card for card in cards if card.provider.id == "google")
    work_state = next(state for state in google_card.auth_states if state.metadata.get("profile_id") == "google:google_oauth:work")
    other_state = next(state for state in google_card.auth_states if state.metadata.get("profile_id") == "google:gemini_cli_local:other")

    assert work_state.metadata["source_group"]["id"] != other_state.metadata["source_group"]["id"]
    assert work_state.account_label == "work@example.com"
    assert other_state.account_label == "other@example.com"


def test_web_session_profile_without_secret_becomes_invalid(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["yuanbao"]["auth_profiles"] = [
        {
            "id": "yuanbao:yuanbao_web_session:browser",
            "provider_id": "yuanbao",
            "method_id": "yuanbao_web_session",
            "method_type": "web_session",
            "label": "浏览器 Session",
            "credential_ref": "missing-session-ref",
            "credential_source": "imported_session",
            "binding": {"source": "imported_session", "source_type": "web_session", "credential_source": "imported_session", "sync_policy": "import_copy"},
            "metadata": {},
        }
    ]
    config["api"]["provider_auth_center"]["providers"]["yuanbao"]["selected_profile_id"] = "yuanbao:yuanbao_web_session:browser"
    cards = build_provider_overview_cards(config, credential_store=store)
    yuanbao_card = next(card for card in cards if card.provider.id == "yuanbao")
    session_state = next(state for state in yuanbao_card.auth_states if state.method_id == "yuanbao_web_session")
    assert session_state.status.value == "invalid"


def test_web_session_profile_with_unreadable_secret_requires_reimport(tmp_path):
    ref = "broken-session-ref"
    (tmp_path / "creds.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    ref: _broken_credential_entry("yuanbao", "web_session"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["yuanbao"]["auth_profiles"] = [
        {
            "id": "yuanbao:yuanbao_web_session:browser",
            "provider_id": "yuanbao",
            "method_id": "yuanbao_web_session",
            "method_type": "web_session",
            "label": "Browser Session",
            "credential_ref": ref,
            "credential_source": "imported_session",
            "binding": {"source": "imported_session", "source_type": "web_session", "credential_source": "imported_session", "sync_policy": "import_copy"},
            "metadata": {},
        }
    ]
    config["api"]["provider_auth_center"]["providers"]["yuanbao"]["selected_profile_id"] = "yuanbao:yuanbao_web_session:browser"

    cards = build_provider_overview_cards(config, credential_store=store)
    yuanbao_card = next(card for card in cards if card.provider.id == "yuanbao")
    session_state = next(state for state in yuanbao_card.auth_states if state.method_id == "yuanbao_web_session")

    assert session_state.status.value == "invalid"
    assert session_state.summary == "会话需要重新导入"
    assert session_state.detail == "这份已导入的会话无法读取，请重新导入或重新连接这家服务方。"


@pytest.mark.asyncio
async def test_api_key_health_check_maps_invalid_credentials(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    record = store.set(
        "provider-auth::openai::api_key::primary",
        provider_id="openai",
        method_type="api_key",
        payload={"api_key": "sk-bad"},
    )
    entry = {
        "provider_id": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-mini",
        "alias": "小欧",
        "metadata": {},
    }
    profile = {
        "id": "openai:api_key:primary",
        "provider_id": "openai",
        "method_id": "api_key",
        "method_type": "api_key",
        "label": "主账号",
        "credential_ref": record.ref,
        "metadata": {},
    }

    async def fake_probe_fast(self):
        raise RuntimeError("401 Unauthorized")

    async def fake_close(self):
        return None

    monkeypatch.setattr("backend.model_auth.services.health.AIClient.probe_fast", fake_probe_fast)
    monkeypatch.setattr("backend.model_auth.services.health.AIClient.close", fake_close)

    result = await run_profile_health_check(entry, profile, credential_store=store)
    assert not result.ok
    assert result.error_code == "api_key_invalid"


@pytest.mark.asyncio
async def test_api_key_health_check_reports_unreadable_secret_without_probing(tmp_path, monkeypatch):
    ref = "provider-auth::openai::api_key::broken"
    (tmp_path / "creds.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    ref: _broken_credential_entry("openai", "api_key"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = CredentialStore(str(tmp_path / "creds.json"))
    entry = {
        "provider_id": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-mini",
        "alias": "小欧",
        "metadata": {},
    }
    profile = {
        "id": "openai:api_key:broken",
        "provider_id": "openai",
        "method_id": "api_key",
        "method_type": "api_key",
        "label": "主账号",
        "credential_ref": ref,
        "metadata": {},
    }
    probed = {"called": False}

    async def fake_probe_fast(self):
        probed["called"] = True
        return True, "responses"

    async def fake_close(self):
        return None

    monkeypatch.setattr("backend.model_auth.services.health.AIClient.probe_fast", fake_probe_fast)
    monkeypatch.setattr("backend.model_auth.services.health.AIClient.close", fake_close)

    result = await run_profile_health_check(entry, profile, credential_store=store)

    assert not result.ok
    assert result.error_code == "credential_unreadable"
    assert result.message == "已保存的 API Key 无法读取，请重新填写。"
    assert result.can_retry is False
    assert probed["called"] is False


@pytest.mark.asyncio
async def test_kimi_local_health_check_uses_local_follow_runtime_defaults(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.json"))
    share_dir = tmp_path / ".kimi"
    credentials_dir = share_dir / "credentials"
    credentials_dir.mkdir(parents=True)
    (share_dir / "config.toml").write_text(
        '\n'.join(
            [
                '[providers.kimi-for-coding]',
                'type = "kimi"',
                'base_url = "https://api.kimi.com/coding/v1"',
                'model = "kimi-k2-turbo-preview"',
                'api_key = "ms-local-kimi-key-1234567890"',
            ]
        ),
        encoding="utf-8",
    )
    (credentials_dir / "kimi.json").write_text(
        '{"access_token": "kimi-access-token-1234567890"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))

    captured = {}

    class FakeAIClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def probe_fast(self):
            return True, "model"

        async def close(self):
            return None

    monkeypatch.setattr("backend.model_auth.services.health.AIClient", FakeAIClient)

    entry = {
        "provider_id": "kimi",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-thinking-preview",
        "alias": "Kimi",
        "metadata": {},
    }
    profile = {
        "id": "kimi:kimi_code_local:work",
        "provider_id": "kimi",
        "method_id": "kimi_code_local",
        "method_type": "local_import",
        "label": "Kimi 本机登录",
        "credential_ref": "",
        "binding": {
            "source": "kimi_code_credentials",
            "source_type": "kimi_code_local",
            "credential_source": "local_config_file",
            "sync_policy": "follow",
            "follow_local_auth": True,
        },
        "metadata": {},
    }

    result = await run_profile_health_check(entry, profile, credential_store=store)

    assert result.ok
    assert captured["base_url"] == "https://api.kimi.com/coding/v1"
    assert captured["model"] == "kimi-for-coding"
    assert callable(captured["api_key"])
    assert captured["api_key"]() == "ms-local-kimi-key-1234567890"


def test_persisted_active_provider_wins_over_legacy_active_preset(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    config["api"]["provider_auth_center"]["providers"]["qwen"] = {
        "provider_id": "qwen",
        "legacy_preset_name": "Qwen",
        "alias": "",
        "default_model": "qwen3.5-plus",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "selected_profile_id": "qwen:api_key:default",
        "auth_profiles": [
            {
                "id": "qwen:api_key:default",
                "provider_id": "qwen",
                "method_id": "api_key",
                "method_type": "api_key",
                "label": "Qwen API Key",
                "credential_ref": "provider-auth::qwen::api_key::default",
                "credential_source": "manual_input",
                "binding": {
                    "source": "manual_input",
                    "source_type": "api_key",
                    "credential_source": "manual_input",
                    "sync_policy": "manual",
                },
                "metadata": {},
            }
        ],
        "metadata": {"project_to_runtime": True},
    }
    config["api"]["provider_auth_center"]["active_provider_id"] = "qwen"
    config["api"]["active_preset"] = "OpenAI"

    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    assert normalized["api"]["provider_auth_center"]["active_provider_id"] == "qwen"
    assert normalized["api"]["active_preset"] == "Qwen"


def test_build_provider_overview_uses_injected_credential_store_for_migration(tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    cards = build_provider_overview_cards(_base_config(), credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    api_key_state = next(state for state in openai_card.auth_states if state.method_id == "api_key")
    assert api_key_state.status.value == "connected"
    assert store.get("provider-auth::openai::api_key::openai") is not None


def test_local_auth_sync_orchestrator_caches_snapshot_until_forced_refresh(monkeypatch):
    payloads = iter(
        [
            {
                "success": True,
                "providers": {
                    "openai_codex": {
                        "detected": True,
                        "configured": True,
                        "account_label": "工作号 A",
                    }
                },
            },
            {
                "success": True,
                "providers": {
                    "openai_codex": {
                        "detected": True,
                        "configured": True,
                        "account_label": "工作号 B",
                    }
                },
            },
        ]
    )

    monkeypatch.setattr(
        "backend.model_auth.sync.orchestrator.get_auth_provider_statuses",
        lambda: next(payloads),
    )
    orchestrator = LocalAuthSyncOrchestrator(poll_interval_sec=60, stale_after_sec=600)

    first = orchestrator.get_snapshot(force_refresh=True, reason="test_first")
    cached = orchestrator.get_snapshot()
    second = orchestrator.get_snapshot(force_refresh=True, reason="test_second")

    assert first["revision"] == 1
    assert cached["revision"] == 1
    assert first["providers"]["openai_codex"]["account_label"] == "工作号 A"
    assert second["revision"] == 2
    assert second["providers"]["openai_codex"]["account_label"] == "工作号 B"
    assert "openai_codex" in second["changed_provider_ids"]


def test_local_auth_sync_orchestrator_updates_watch_paths_from_local_sources(monkeypatch):
    monkeypatch.setattr(
        "backend.model_auth.sync.orchestrator.get_auth_provider_statuses",
        lambda: {
            "success": True,
            "providers": {
                "openai_codex": {
                    "detected": True,
                    "configured": True,
                    "auth_path": "C:/auth/openai.json",
                },
                "google_gemini_cli": {
                    "detected": True,
                    "configured": True,
                    "oauth_creds_path": "C:/auth/gemini-oauth.json",
                    "google_accounts_path": "C:/auth/gemini-accounts.json",
                },
                "claude_code_local": {
                    "detected": True,
                    "configured": True,
                    "auth_path": "C:/auth/claude.json",
                    "managed_settings_path": "C:/ProgramData/ClaudeCode/managed-settings.json",
                    "watch_paths": [
                        "C:/auth/claude.json",
                        "C:/ProgramData/ClaudeCode/managed-settings.json",
                    ],
                },
                "doubao_session": {
                    "detected": True,
                    "configured": True,
                    "private_storage_path": "C:/Users/demo/AppData/Local/ByteDance/Doubao/User Data",
                    "session_path": "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
                    "indexeddb_path": "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/IndexedDB/https_yuanbao.tencent.com_0.indexeddb.leveldb",
                    "watch_paths": [
                        "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
                        "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/IndexedDB/https_yuanbao.tencent.com_0.indexeddb.leveldb",
                        "C:/Users/demo/AppData/Local/ByteDance/Doubao/User Data",
                    ],
                },
            },
        },
    )
    orchestrator = LocalAuthSyncOrchestrator(poll_interval_sec=60, stale_after_sec=600)
    captured = {}
    monkeypatch.setattr(orchestrator._watcher, "update", lambda *, paths=None, **kwargs: captured.setdefault("paths", list(paths or [])))
    monkeypatch.setattr(
        orchestrator._watcher,
        "get_status",
        lambda: {"mode": "polling", "preferred_mode": "auto", "debounce_ms": 1200, "watch_paths": captured.get("paths", [])},
    )

    snapshot = orchestrator.get_snapshot(force_refresh=True, reason="watch_path_test")

    assert snapshot["watcher"]["watch_path_count"] == 8
    assert "C:/auth/openai.json" in captured["paths"]
    assert "C:/auth/gemini-oauth.json" in captured["paths"]
    assert "C:/auth/gemini-accounts.json" in captured["paths"]
    assert "C:/auth/claude.json" in captured["paths"]
    assert "C:/ProgramData/ClaudeCode/managed-settings.json" in captured["paths"]
    assert "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/Network/Cookies" in captured["paths"]
    assert "C:/Users/demo/AppData/Local/Google/Chrome/User Data/Default/IndexedDB/https_yuanbao.tencent.com_0.indexeddb.leveldb" in captured["paths"]
    assert "C:/Users/demo/AppData/Local/ByteDance/Doubao/User Data" in captured["paths"]


def test_local_auth_sync_orchestrator_start_schedules_initial_refresh_without_blocking(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def _slow_refresh():
        started.set()
        assert release.wait(timeout=5.0)
        return {
            "success": True,
            "providers": {
                "openai_codex": {
                    "detected": True,
                    "configured": True,
                    "account_label": "Work A",
                }
            },
        }

    monkeypatch.setattr("backend.model_auth.sync.orchestrator.get_auth_provider_statuses", _slow_refresh)
    orchestrator = LocalAuthSyncOrchestrator(poll_interval_sec=60, stale_after_sec=600)

    try:
        started_at = time.perf_counter()
        orchestrator.start()
        elapsed = time.perf_counter() - started_at

        assert elapsed < 0.1
        assert started.wait(timeout=0.5) is True

        snapshot = orchestrator.get_snapshot(reason="startup_probe")
        assert snapshot["refreshing"] is True
        assert snapshot["refreshed_at"] == 0
        assert snapshot["revision"] == 0

        release.set()
        assert orchestrator._refresh_thread is not None
        orchestrator._refresh_thread.join(timeout=1.0)

        refreshed = orchestrator.get_snapshot(reason="startup_complete")
        assert refreshed["refreshing"] is False
        assert refreshed["revision"] == 1
        assert refreshed["providers"]["openai_codex"]["account_label"] == "Work A"
    finally:
        release.set()
        orchestrator.stop()


def test_scan_forces_local_auth_snapshot_refresh(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store
    calls = {"start": 0, "refresh": 0}

    class _DummySync:
        def start(self):
            calls["start"] += 1

        def force_refresh(self, *, reason: str = ""):
            calls["refresh"] += 1
            calls["reason"] = reason
            return {"success": True, "providers": {}, "refreshed_at": 1}

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")})

    result = service.scan()

    assert result["success"] is True
    assert calls["start"] == 1
    assert calls["refresh"] == 1
    assert calls["reason"] == "manual_scan"


def test_model_auth_center_get_overview_exposes_local_auth_sync_progress(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store
    calls = {"start": 0}

    class _DummySync:
        def start(self):
            calls["start"] += 1

        def get_snapshot(self, *, force_refresh: bool = False, reason: str = ""):
            return {
                "success": True,
                "providers": {},
                "refreshed_at": 0,
                "revision": 7,
                "changed_provider_ids": ["openai_codex"],
                "message": "",
                "refreshing": True,
                "pending_reason": "startup",
            }

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    result = service.get_overview()

    assert calls["start"] == 1
    assert result["success"] is True
    assert result["overview"]["local_auth_sync"] == {
        "refreshing": True,
        "refreshed_at": 0,
        "revision": 7,
        "changed_provider_ids": ["openai_codex"],
        "message": "",
    }


def test_update_provider_defaults_keeps_unconfigured_provider_out_of_runtime_projection(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["api_key"] = "YOUR_API_KEY"
    config["api"]["presets"][0]["api_key"] = "YOUR_API_KEY"
    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: deepcopy(cfg))

    saved_config = service.update_provider_defaults({"provider_id": "openai", "default_model": "gpt-5"})
    entry = saved_config["api"]["provider_auth_center"]["providers"]["openai"]
    assert entry["metadata"]["project_to_runtime"] is False
    projected = project_provider_auth_center(saved_config["api"])
    assert projected["presets"]
    assert projected["presets"][0]["provider_id"] == "openai"


def test_update_provider_defaults_syncs_selected_profile_runtime_model(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: deepcopy(cfg))

    saved_config = service.update_provider_defaults({"provider_id": "openai", "default_model": "gpt-5.4"})
    entry = saved_config["api"]["provider_auth_center"]["providers"]["openai"]
    selected = next(
        item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"]
    )
    projected = project_provider_auth_center(saved_config["api"])
    openai_preset = next(item for item in projected["presets"] if item["provider_id"] == "openai")

    assert selected["metadata"]["model"] == "gpt-5.4"
    assert openai_preset["model"] == "gpt-5.4"


def test_update_provider_defaults_keeps_specialized_profile_runtime_model(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    qwen_entry = normalized["api"]["provider_auth_center"]["providers"]["qwen"]
    qwen_entry["selected_profile_id"] = "qwen:coding_plan_api_key:coding-plan"
    qwen_entry["auth_profiles"] = [
        {
            "id": "qwen:coding_plan_api_key:coding-plan",
            "provider_id": "qwen",
            "method_id": "coding_plan_api_key",
            "method_type": "api_key",
            "label": "Coding Plan",
            "credential_ref": "",
            "credential_source": "manual_input",
            "binding": {
                "source": "manual_input",
                "source_type": "api_key",
                "credential_source": "manual_input",
                "sync_policy": "manual",
            },
            "metadata": {
                "base_url": "https://coding.dashscope.aliyuncs.com/v1",
                "model": "qwen3-coder-plus",
            },
        }
    ]

    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: deepcopy(cfg))

    saved_config = service.update_provider_defaults({"provider_id": "qwen", "default_model": "qwen-max-latest"})
    entry = saved_config["api"]["provider_auth_center"]["providers"]["qwen"]
    selected = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert entry["default_model"] == "qwen-max-latest"
    assert selected["metadata"]["model"] == "qwen3-coder-plus"


def test_update_provider_defaults_persists_dynamic_runtime_fields(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    monkeypatch.setattr(
        "backend.model_auth.services.center._runtime_metadata_field_names",
        lambda provider_id, method=None: ("oauth_project_id", "oauth_location", "workspace_id", "region"),
    )
    monkeypatch.setattr(
        "backend.model_auth.services.migration._runtime_metadata_field_names",
        lambda provider_id, method=None: ("oauth_project_id", "oauth_location", "workspace_id", "region"),
    )
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: deepcopy(cfg))

    saved_config = service.update_provider_defaults(
        {
            "provider_id": "openai",
            "workspace_id": "proj-123",
            "region": "cn-hangzhou",
        }
    )
    entry = saved_config["api"]["provider_auth_center"]["providers"]["openai"]
    projected = project_provider_auth_center(saved_config["api"])
    openai_preset = next(item for item in projected["presets"] if item["provider_id"] == "openai")

    assert entry["metadata"]["workspace_id"] == "proj-123"
    assert entry["metadata"]["region"] == "cn-hangzhou"
    assert openai_preset["workspace_id"] == "proj-123"
    assert openai_preset["region"] == "cn-hangzhou"


def test_start_browser_auth_passes_dynamic_runtime_fields_to_oauth_launcher(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["openai"].setdefault("metadata", {}).update(
        {
            "workspace_id": "proj-123",
            "region": "cn-hangzhou",
        }
    )
    service = ModelAuthCenterService()
    captured = {}

    monkeypatch.setattr(
        "backend.model_auth.services.migration._runtime_metadata_field_names",
        lambda provider_id, method=None: ("oauth_project_id", "oauth_location", "workspace_id", "region"),
    )
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.launch_oauth_login",
        lambda provider_key, settings=None: captured.update(
            {
                "provider_key": provider_key,
                "settings": dict(settings or {}),
            }
        ) or {
            "success": True,
            "flow_id": "flow-123",
            "created_at": 1,
            "message": "ok",
        },
    )
    monkeypatch.setattr(
        service,
        "_save_and_render",
        lambda cfg, **kwargs: {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")},
    )

    result = service.start_browser_auth({"provider_id": "openai", "method_id": "codex_local"})

    assert result["success"] is True
    assert captured["provider_key"] == "openai_codex"
    assert captured["settings"]["workspace_id"] == "proj-123"
    assert captured["settings"]["region"] == "cn-hangzhou"


def test_start_browser_auth_passes_google_project_id_to_oauth_launcher(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["google"].setdefault("metadata", {}).update(
        {
            "oauth_project_id": "demo-google-project",
        }
    )
    service = ModelAuthCenterService()
    captured = {}

    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.launch_oauth_login",
        lambda provider_key, settings=None: captured.update(
            {
                "provider_key": provider_key,
                "settings": dict(settings or {}),
            }
        ) or {
            "success": True,
            "flow_id": "flow-456",
            "created_at": 1,
            "message": "ok",
        },
    )
    monkeypatch.setattr(
        service,
        "_save_and_render",
        lambda cfg, **kwargs: {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")},
    )

    result = service.start_browser_auth({"provider_id": "google", "method_id": "google_oauth"})

    assert result["success"] is True
    assert captured["provider_key"] == "google_gemini_cli"
    assert captured["settings"]["oauth_project_id"] == "demo-google-project"


def test_complete_browser_auth_creates_oauth_profile_before_local_source_is_detected(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    config = _base_config()
    config["api"]["active_preset"] = "Qwen"
    config["api"]["presets"] = [
        {
            "name": "Qwen",
            "provider_id": "qwen",
            "alias": "",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "YOUR_API_KEY",
            "auth_mode": "api_key",
            "model": "qwen3.5-plus",
            "allow_empty_key": False,
        }
    ]
    normalized = ensure_provider_auth_center_config(config, credential_store=store)
    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.submit_auth_callback",
        lambda provider_key, flow_id, payload=None: {"completed": True, "message": "ok"},
    )
    monkeypatch.setattr("backend.model_auth.services.center.get_legacy_status_map", lambda force_refresh=False: {})
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.complete_browser_auth(
        {"provider_id": "qwen", "method_id": "qwen_oauth", "flow_id": "flow-1"}
    )
    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["qwen"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "qwen_oauth")
    assert result["success"] is True
    assert profile["credential_source"] == "oauth_callback"
    assert profile["binding"]["metadata"]["awaiting_local_sync"] is True
    assert profile["metadata"]["runtime_ready"] is False
    assert (
        profile["metadata"]["runtime_unavailable_reason"]
        == "已登录，但还没检测到可同步的本机登录状态。"
    )


def test_save_api_key_supports_provider_specific_method_id(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.save_api_key(
        {
            "provider_id": "qwen",
            "method_id": "coding_plan_api_key",
            "label": "Coding Plan 主账号",
            "api_key": "demo-provider-secure-value",
            "set_default": True,
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["qwen"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "coding_plan_api_key")

    assert result["success"] is True
    assert entry["selected_profile_id"] == profile["id"]
    assert profile["metadata"]["base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert profile["metadata"]["model"] == "qwen3-coder-next"
    assert store.get(profile["credential_ref"]).payload["api_key"] == "demo-provider-secure-value"


def test_save_api_key_normalizes_runtime_endpoint_base_url(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    service.save_api_key(
        {
            "provider_id": "qwen",
            "method_id": "coding_plan_api_key",
            "label": "Coding Plan Endpoint",
            "api_key": "demo-provider-secure-value",
            "default_base_url": "https://coding.dashscope.aliyuncs.com/v1/chat/completions",
            "default_model": "qwen3-coder-plus",
            "set_default": True,
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["qwen"]
    profile = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert entry["default_base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert profile["metadata"]["base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert profile["metadata"]["model"] == "qwen3-coder-plus"


def test_save_api_key_prefers_provider_default_model_over_method_recommendation(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["openai"]["default_model"] = "gpt-5.3-codex"
    service = ModelAuthCenterService()
    service._credential_store = store
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.save_api_key(
        {
            "provider_id": "openai",
            "method_id": "api_key",
            "label": "Primary Key",
            "api_key": "demo-openai-secure-value",
            "set_default": True,
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert result["success"] is True
    assert profile["metadata"]["model"] == "gpt-5.3-codex"


def test_save_api_key_keeps_existing_oauth_selected_in_auto_mode(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    openai_entry = normalized["api"]["provider_auth_center"]["providers"]["openai"]
    openai_entry["auth_profiles"].append(
        {
            "id": "openai:codex_local:chatgpt",
            "provider_id": "openai",
            "method_id": "codex_local",
            "method_type": "local_import",
            "label": "ChatGPT OAuth",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "codex_auth_json",
                "source_type": "openai_codex",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {"runtime_ready": True},
        }
    )
    openai_entry["selected_profile_id"] = "openai:codex_local:chatgpt"
    openai_entry.setdefault("metadata", {})
    openai_entry["metadata"]["selection_mode"] = "auto"
    service = ModelAuthCenterService()
    service._credential_store = store
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    saved = {}

    def _capture(cfg, **kwargs):
        saved["config"] = deepcopy(cfg)
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    service.save_api_key(
        {
            "provider_id": "openai",
            "method_id": "api_key",
            "label": "Primary Key",
            "api_key": "demo-openai-fallback",
            "set_default": False,
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    assert entry["selected_profile_id"] == "openai:codex_local:chatgpt"
    assert entry["metadata"]["selection_mode"] == "auto"


def test_bind_local_auth_supports_web_session_follow_mode(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "doubao_session": {
                "detected": True,
                "configured": True,
                "account_label": "Chrome Default browser session",
                "browser_name": "Chrome",
                "browser_profile": "Default",
                "cookie_count": 7,
                "auth_cookie_count": 3,
                "session_path": str(tmp_path / "doubao-cookies.sqlite"),
                "indexeddb_path": str(tmp_path / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"),
                "local_storage_path": str(tmp_path / "Local Storage" / "leveldb"),
                "private_storage_path": str(tmp_path / "Doubao" / "User Data"),
                "watch_paths": [
                    str(tmp_path / "doubao-cookies.sqlite"),
                    str(tmp_path / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"),
                    str(tmp_path / "Local Storage" / "leveldb"),
                ],
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.bind_local_auth(
        {"provider_id": "doubao", "method_id": "doubao_web_session", "label": "Local Browser Session"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["doubao"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "doubao_web_session")

    assert result["success"] is True
    assert profile["credential_source"] == "browser_session"
    assert profile["binding"]["credential_source"] == "browser_session"
    assert profile["binding"]["follow_local_auth"] is True
    assert profile["binding"]["metadata"]["browser_name"] == "Chrome"
    assert profile["binding"]["metadata"]["cookie_count"] == 7
    assert profile["binding"]["metadata"]["indexeddb_path"].endswith(".indexeddb.leveldb")
    assert profile["binding"]["metadata"]["private_storage_path"].replace("\\", "/").endswith("Doubao/User Data")
    assert len(profile["binding"]["metadata"]["watch_paths"]) == 3


def test_bind_local_auth_falls_back_to_openai_codex_when_method_id_is_generic(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "ChatGPT Work",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.bind_local_auth(
        {"provider_id": "openai", "method_id": "oauth", "label": "ChatGPT Work"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert result["success"] is True
    assert profile["method_id"] == "codex_local"


def test_bind_local_auth_prefers_account_email_for_profile_label(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "ChatGPT Work",
                "account_email": "work@example.com",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    service.bind_local_auth({"provider_id": "openai", "method_id": "codex_local"})

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert profile["label"] == "work@example.com"
    assert profile["binding"]["account_label"] == "work@example.com"
    assert profile["binding"]["metadata"]["account_email"] == "work@example.com"


def test_complete_browser_auth_prefers_account_email_after_local_rescan(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "runtime_available": True,
                "account_label": "ChatGPT Work",
                "account_email": "work@example.com",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    service.complete_browser_auth(
        {
            "provider_id": "openai",
            "method_id": "codex_local",
            "flow_id": "__local_rescan__",
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["id"] == entry["selected_profile_id"])

    assert profile["label"] == "work@example.com"
    assert profile["binding"]["account_label"] == "work@example.com"
    assert profile["binding"]["metadata"]["account_email"] == "work@example.com"


def test_import_local_auth_copy_stores_runtime_snapshot_and_marks_profile_imported(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    class _Resolved:
        def __init__(self, settings):
            self.settings = settings

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "ChatGPT Work",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    monkeypatch.setattr(
        "backend.model_auth.services.center.resolve_oauth_settings",
        lambda settings: _Resolved(
            {
                "api_key": "snapshot-token",
                "base_url": "https://api.openai.com/v1",
                "auth_transport": "openai",
                "extra_headers": {"X-Test": "1"},
                "resolved_auth_metadata": {"source": "snapshot"},
            }
        ),
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.import_local_auth_copy(
        {"provider_id": "openai", "method_id": "codex_local", "label": "Imported ChatGPT"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "codex_local")
    snapshot = store.get(profile["credential_ref"])

    assert result["success"] is True
    assert profile["binding"]["sync_policy"] == "import_copy"
    assert profile["binding"]["follow_local_auth"] is False
    assert profile["metadata"]["runtime_ready"] is True
    assert snapshot is not None
    assert snapshot.payload["kind"] == "runtime_context_snapshot"
    assert snapshot.payload["api_key"] == "snapshot-token"
    assert snapshot.payload["adapter_id"] == "openai_codex"

    cards = build_provider_overview_cards(saved["config"], credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")
    imported_state = next(item for item in openai_card.auth_states if item.method_id == "codex_local" and item.default_selected)
    action_ids = {item["id"] for item in imported_state.actions}

    assert imported_state.status.value == "imported"
    assert "bind_local_auth" in action_ids


def test_complete_browser_auth_supports_flowless_local_rescan(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.submit_auth_callback",
        lambda provider_key, flow_id, payload=None: (_ for _ in ()).throw(AssertionError("submit_auth_callback should not be used")),
    )
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "account_label": "ChatGPT Browser",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.complete_browser_auth(
        {
            "provider_id": "openai",
            "method_id": "codex_local",
            "flow_id": "__local_rescan__",
            "label": "ChatGPT Browser",
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "codex_local")

    assert result["success"] is True
    assert profile["credential_source"] == "local_config_file"
    assert profile["binding"]["source_type"] == "openai_codex"
    assert profile["binding"]["follow_local_auth"] is True
    assert profile["metadata"]["runtime_ready"] is True


def test_complete_browser_auth_ignores_flow_id_for_openai_local_rescan(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.submit_auth_callback",
        lambda provider_key, flow_id, payload=None: (_ for _ in ()).throw(
            AssertionError("submit_auth_callback should not be used for local_rescan providers")
        ),
    )
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "openai_codex": {
                "detected": True,
                "configured": True,
                "runtime_available": True,
                "account_label": "ChatGPT Browser",
                "auth_path": str(tmp_path / "codex-auth.json"),
                "local_source_label": "codex_auth_json",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        saved["config"] = deepcopy(cfg)
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.complete_browser_auth(
        {"provider_id": "openai", "method_id": "codex_local", "flow_id": "flow-openai-1"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["openai"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "codex_local")

    assert result["success"] is True
    assert profile["credential_source"] == "local_config_file"
    assert profile["binding"]["source_type"] == "openai_codex"
    assert profile["metadata"]["runtime_ready"] is True


def test_complete_browser_auth_ignores_flow_id_for_google_local_rescan(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.submit_auth_callback",
        lambda provider_key, flow_id, payload=None: (_ for _ in ()).throw(
            AssertionError("submit_auth_callback should not be used for local_rescan providers")
        ),
    )
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "google_gemini_cli": {
                "detected": True,
                "configured": True,
                "runtime_available": True,
                "account_label": "Gemini CLI Browser",
                "local_source_label": "gemini_cli_oauth",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        saved["config"] = deepcopy(cfg)
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.complete_browser_auth(
        {"provider_id": "google", "method_id": "google_oauth", "flow_id": "flow-google-1"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["google"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "google_oauth")

    assert result["success"] is True
    assert profile["credential_source"] == "local_config_file"
    assert profile["binding"]["source_type"] == "google_gemini_cli"
    assert profile["binding"]["follow_local_auth"] is True
    assert profile["metadata"]["runtime_ready"] is True


def test_complete_browser_auth_ignores_flow_id_for_claude_local_rescan(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.submit_auth_callback",
        lambda provider_key, flow_id, payload=None: (_ for _ in ()).throw(
            AssertionError("submit_auth_callback should not be used for local_rescan providers")
        ),
    )
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "claude_code_local": {
                "detected": True,
                "configured": True,
                "runtime_available": True,
                "account_label": "Claude Code Browser",
                "local_source_label": "claude_code_local",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        saved["config"] = deepcopy(cfg)
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.complete_browser_auth(
        {"provider_id": "anthropic", "method_id": "claude_code_oauth", "flow_id": "flow-claude-1"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["anthropic"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "claude_code_oauth")

    assert result["success"] is True
    assert profile["credential_source"] == "local_config_file"
    assert profile["binding"]["source_type"] == "claude_code_local"
    assert profile["binding"]["follow_local_auth"] is True
    assert profile["metadata"]["runtime_ready"] is True


def test_bind_local_auth_prefers_system_keychain_credential_source(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store

    class _DummySync:
        def start(self):
            return None

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.get_legacy_status_map",
        lambda force_refresh=False: {
            "claude_code_local": {
                "detected": True,
                "configured": False,
                "account_label": "Claude Code keychain credential",
                "keychain_provider": "windows_credential_manager",
                "keychain_targets": ["LegacyGeneric:target=ClaudeCode/oauth"],
                "keychain_locator": "keychain://windows_credential_manager/anthropic/claudecode-oauth",
                "runtime_unavailable_reason": "已检测到本机 Claude 钥匙串状态，但当前运行时仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。",
            }
        },
    )
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.bind_local_auth(
        {"provider_id": "anthropic", "method_id": "claude_code_local", "label": "Claude Keychain"}
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["anthropic"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "claude_code_local")

    assert result["success"] is True
    assert profile["credential_source"] == "system_keychain"
    assert profile["binding"]["credential_source"] == "system_keychain"
    assert profile["binding"]["locator_path"].startswith("keychain://windows_credential_manager/anthropic/")
    assert profile["binding"]["metadata"]["keychain_provider"] == "windows_credential_manager"
    assert profile["binding"]["metadata"]["keychain_targets"] == ["LegacyGeneric:target=ClaudeCode/oauth"]
    assert profile["metadata"]["runtime_ready"] is False
    assert (
        profile["metadata"]["runtime_unavailable_reason"]
        == "已检测到本机 Claude 钥匙串状态，但当前运行时仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。"
    )


def test_provider_health_summary_uses_checked_result(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["openai"]
    entry["auth_profiles"][0]["metadata"]["health"] = {
        "ok": False,
        "state": "error",
        "checked_at": 123456,
        "message": "401 Unauthorized",
        "error_code": "api_key_invalid",
        "can_retry": True,
    }
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(normalized, credential_store=store)
    openai_card = next(card for card in cards if card.provider.id == "openai")

    assert openai_card.metadata["provider_health"]["code"] == "warning"
    assert openai_card.metadata["provider_health"]["error_code"] == "api_key_invalid"
    assert openai_card.metadata["provider_health"]["checked_at"] == 123456


def test_google_runtime_profile_reuses_detected_project_id_without_manual_metadata(monkeypatch, tmp_path):
    creds_path, accounts_path = _write_google_gemini_auth_files(tmp_path, project_id="gemini-project-001")
    monkeypatch.setenv("WECHAT_BOT_GEMINI_OAUTH_PATH", creds_path)
    monkeypatch.setenv("WECHAT_BOT_GEMINI_ACCOUNTS_PATH", accounts_path)
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    google_entry = normalized["api"]["provider_auth_center"]["providers"]["google"]
    google_entry["selected_profile_id"] = "google:google_oauth:work"
    google_entry["auth_profiles"] = [
        {
            "id": "google:google_oauth:work",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "Gemini OAuth",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {},
        }
    ]
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(normalized, credential_store=store)
    google_card = next(card for card in cards if card.provider.id == "google")
    google_state = next(
        state for state in google_card.auth_states if state.metadata.get("profile_id") == "google:google_oauth:work"
    )
    action_ids = {item["id"] for item in google_state.actions}

    assert google_state.metadata["runtime_ready"] is True
    assert google_card.metadata["provider_health"]["code"] == "not_checked"
    assert "test_profile" in action_ids

    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        service,
        "_save_and_render",
        lambda cfg, **kwargs: {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")},
    )

    result = service.set_active_provider({"provider_id": "google"})

    assert result["success"] is True


def test_google_runtime_profile_blocks_without_project_id_and_hides_test_action(monkeypatch, tmp_path):
    creds_path, accounts_path = _write_google_gemini_auth_files(tmp_path, project_id=None)
    monkeypatch.setenv("WECHAT_BOT_GEMINI_OAUTH_PATH", creds_path)
    monkeypatch.setenv("WECHAT_BOT_GEMINI_ACCOUNTS_PATH", accounts_path)
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    google_entry = normalized["api"]["provider_auth_center"]["providers"]["google"]
    google_entry["selected_profile_id"] = "google:google_oauth:work"
    google_entry["auth_profiles"] = [
        {
            "id": "google:google_oauth:work",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "Gemini OAuth",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {},
        }
    ]
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(normalized, credential_store=store)
    google_card = next(card for card in cards if card.provider.id == "google")
    google_state = next(
        state for state in google_card.auth_states if state.metadata.get("profile_id") == "google:google_oauth:work"
    )
    action_ids = {item["id"] for item in google_state.actions}

    assert google_state.metadata["runtime_ready"] is False
    assert "项目 ID" in google_state.metadata["runtime_unavailable_reason"]
    assert "test_profile" not in action_ids
    assert google_card.metadata["provider_health"]["code"] == "blocked"

    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))

    with pytest.raises(ValueError, match="支持运行时调用的认证"):
        service.set_active_provider({"provider_id": "google"})


def test_provider_health_summary_marks_runtime_blocked_and_hides_test_action(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    entry = normalized["api"]["provider_auth_center"]["providers"]["anthropic"]
    entry["selected_profile_id"] = "anthropic:claude_code_local:local"
    entry["auth_profiles"] = [
        {
            "id": "anthropic:claude_code_local:local",
            "provider_id": "anthropic",
            "method_id": "claude_code_local",
            "method_type": "local_import",
            "label": "Claude Local",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "claude_code_local",
                "source_type": "claude_code_local",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {
                "runtime_ready": False,
                "runtime_available": False,
                "runtime_unavailable_reason": "Claude 本机登录已经关联，但当前运行时仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。",
            },
        }
    ]
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(normalized, credential_store=store)
    claude_card = next(card for card in cards if card.provider.id == "anthropic")
    local_state = next(state for state in claude_card.auth_states if state.method_id == "claude_code_local")
    action_ids = {item["id"] for item in local_state.actions}

    assert "test_profile" not in action_ids
    assert local_state.metadata["runtime_ready"] is False
    assert (
        local_state.metadata["runtime_unavailable_reason"]
        == "Claude 本机登录已经关联，但当前运行时仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。"
    )
    assert claude_card.metadata["provider_health"]["code"] == "blocked"
    assert (
        claude_card.metadata["provider_health"]["message"]
        == "Claude 本机登录已经关联，但当前运行时仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。"
    )


def test_set_active_provider_rejects_provider_without_runtime_profile(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["yuanbao"]["selected_profile_id"] = "yuanbao:yuanbao_web_session:browser"
    normalized["api"]["provider_auth_center"]["providers"]["yuanbao"]["auth_profiles"] = [
        {
            "id": "yuanbao:yuanbao_web_session:browser",
            "provider_id": "yuanbao",
            "method_id": "yuanbao_web_session",
            "method_type": "web_session",
            "label": "浏览器 Session",
            "credential_ref": "provider-auth::yuanbao::yuanbao_web_session::browser",
            "credential_source": "imported_session",
            "binding": {
                "source": "imported_session",
                "source_type": "web_session",
                "credential_source": "imported_session",
                "sync_policy": "import_copy",
            },
            "metadata": {},
        }
    ]
    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))

    with pytest.raises(ValueError, match="支持运行时调用的认证"):
        service.set_active_provider({"provider_id": "yuanbao"})


def test_set_active_provider_skips_profile_marked_runtime_not_ready(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["anthropic"]["selected_profile_id"] = (
        "anthropic:claude_code_local:local"
    )
    normalized["api"]["provider_auth_center"]["providers"]["anthropic"]["auth_profiles"] = [
        {
            "id": "anthropic:claude_code_local:local",
            "provider_id": "anthropic",
            "method_id": "claude_code_local",
            "method_type": "local_import",
            "label": "Claude Local",
            "credential_ref": "",
            "credential_source": "local_config_file",
            "binding": {
                "source": "claude_code_local",
                "source_type": "claude_code_local",
                "credential_source": "local_config_file",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {
                "runtime_ready": False,
                "runtime_available": False,
            },
        }
    ]
    service = ModelAuthCenterService()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))

    with pytest.raises(ValueError, match="支持运行时调用的认证"):
        service.set_active_provider({"provider_id": "anthropic"})


def test_import_session_marks_runtime_unavailable_for_status_only_methods(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    service = ModelAuthCenterService()
    service._credential_store = store
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    saved = {}

    def _capture(cfg, **kwargs):
        snapshot = deepcopy(cfg)
        saved["config"] = snapshot
        return {"success": True, "overview": {"cards": []}, "message": kwargs.get("message", "")}

    monkeypatch.setattr(service, "_save_and_render", _capture)

    result = service.import_session(
        {
            "provider_id": "yuanbao",
            "method_id": "yuanbao_web_session",
            "label": "Yuanbao Browser Session",
            "session_payload": {"cookie": "masked"},
        }
    )

    entry = saved["config"]["api"]["provider_auth_center"]["providers"]["yuanbao"]
    profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "yuanbao_web_session")

    assert result["success"] is True
    assert profile["metadata"]["runtime_ready"] is False
    assert profile["metadata"]["runtime_available"] is False
    assert (
        profile["metadata"]["runtime_unavailable_reason"]
        == "网页登录会话已经导入，但这种认证方式暂时还不能直接用于运行时调用。"
    )


def test_logout_source_forces_local_auth_snapshot_refresh(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "creds.json"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    normalized["api"]["provider_auth_center"]["providers"]["google"]["selected_profile_id"] = "google:google_oauth:work"
    normalized["api"]["provider_auth_center"]["providers"]["google"]["auth_profiles"] = [
        {
            "id": "google:google_oauth:work",
            "provider_id": "google",
            "method_id": "google_oauth",
            "method_type": "oauth",
            "label": "Google OAuth",
            "credential_ref": "",
            "credential_source": "oauth_callback",
            "binding": {
                "source": "google_gemini_cli",
                "source_type": "google_gemini_cli",
                "credential_source": "oauth_callback",
                "sync_policy": "follow",
                "follow_local_auth": True,
            },
            "metadata": {"runtime_ready": False},
        }
    ]
    service = ModelAuthCenterService()
    service._credential_store = store
    calls = {"start": 0, "refresh": 0}

    class _DummySync:
        def start(self):
            calls["start"] += 1

        def force_refresh(self, *, reason: str = ""):
            calls["refresh"] += 1
            calls["reason"] = reason
            return {"success": True}

    service._sync_orchestrator = _DummySync()
    monkeypatch.setattr(service, "_load_config", lambda: deepcopy(normalized))
    monkeypatch.setattr(
        "backend.model_auth.services.center.logout_oauth_provider",
        lambda provider_key, settings=None: {"success": True, "message": f"logged out {provider_key}"},
    )
    monkeypatch.setattr(service, "_save_and_render", lambda cfg, **kwargs: {"success": True, "message": kwargs.get("message", "")})

    result = service.logout_source({"provider_id": "google", "profile_id": "google:google_oauth:work"})

    assert result["success"] is True
    assert calls["start"] == 1
    assert calls["refresh"] == 1
    assert calls["reason"] == "source_logout"


def test_build_provider_overview_cards_can_skip_redundant_normalization(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "credentials.sqlite3"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)

    def _unexpected_normalize(*args, **kwargs):
        raise AssertionError("should not renormalize an already-normalized config")

    monkeypatch.setattr("backend.model_auth.services.status.ensure_provider_auth_center_config", _unexpected_normalize)
    monkeypatch.setattr("backend.model_auth.services.status.get_legacy_status_map", lambda: {})

    cards = build_provider_overview_cards(
        normalized,
        credential_store=store,
        assume_normalized=True,
    )

    assert cards
    assert any(card.provider.id == "openai" for card in cards)


def test_model_auth_center_load_config_skips_redundant_normalization(monkeypatch, tmp_path):
    store = CredentialStore(str(tmp_path / "credentials.sqlite3"))
    normalized = ensure_provider_auth_center_config(_base_config(), credential_store=store)
    snapshot = SimpleNamespace(to_dict=lambda: deepcopy(normalized))
    service = ModelAuthCenterService()
    service._credential_store = store
    service._config_service = SimpleNamespace(
        get_snapshot=lambda: snapshot,
        save_effective_config=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not persist when config is already current")
        ),
    )

    def _unexpected_normalize(*args, **kwargs):
        raise AssertionError("should not renormalize an already-current config")

    monkeypatch.setattr("backend.model_auth.services.center.ensure_provider_auth_center_config", _unexpected_normalize)

    loaded = service._load_config()

    assert loaded["api"]["provider_auth_center"]["providers"]["openai"]["provider_id"] == "openai"
