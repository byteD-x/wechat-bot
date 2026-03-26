from __future__ import annotations

import base64
import json
import logging
import sqlite3
from types import SimpleNamespace

from backend.core.auth.providers import (
    ClaudeCodeLocalAuthProvider,
    DoubaoWebSessionProvider,
    GoogleGeminiCliAuthProvider,
    KimiCodeLocalAuthProvider,
    OpenAICodexAuthProvider,
    TencentYuanbaoExperimentalAuthProvider,
)


def _encode_jwt_payload(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_claude_code_local_provider_reads_local_session(monkeypatch, tmp_path):
    state_path = tmp_path / "claude.json"
    settings_path = tmp_path / "settings.json"
    credentials_path = tmp_path / ".credentials.json"
    managed_path = tmp_path / "managed-settings.json"
    state_path.write_text(
        json.dumps(
            {
                "auth": {
                    "session": {
                        "accessToken": "claude-local-token-1234567890",
                        "email": "dev@example.com",
                        "name": "Claude Dev",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings_path.write_text(
        json.dumps({"apiKeyHelper": "/usr/local/bin/claude-helper"}),
        encoding="utf-8",
    )
    credentials_path.write_text("{}", encoding="utf-8")
    managed_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_STATE_PATH", str(state_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH", str(managed_path))

    provider = ClaudeCodeLocalAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["auth_path"] == str(state_path.resolve())
    assert status["config_path"] == str(settings_path.resolve())
    assert status["credentials_path"] == str(credentials_path.resolve())
    assert status["api_key_helper"] == "/usr/local/bin/claude-helper"
    assert status["runtime_available"] is True
    assert status["account_label"] == "dev@example.com"
    assert status["account_email"] == "dev@example.com"
    assert str(managed_path.resolve()) in status["watch_paths"]


def test_claude_code_local_provider_resolves_runtime_from_api_key_helper(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    credentials_path = tmp_path / ".credentials.json"
    managed_path = tmp_path / "managed-settings.json"
    settings_path.write_text(
        json.dumps({"apiKeyHelper": "claude-helper --print-key"}),
        encoding="utf-8",
    )
    credentials_path.write_text("{}", encoding="utf-8")
    managed_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH", str(managed_path))
    monkeypatch.setattr(
        "backend.core.auth.providers.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="anthropic-local-token-1234567890\n", stderr=""),
    )

    provider = ClaudeCodeLocalAuthProvider()
    runtime = provider.resolve_runtime({})

    assert runtime.base_url == "https://api.anthropic.com/v1"
    assert runtime.auth_transport == "anthropic_native"
    assert callable(runtime.api_key)
    assert runtime.api_key() == "anthropic-local-token-1234567890"
    assert callable(runtime.extra_headers)
    assert runtime.extra_headers()["X-Api-Key"] == "anthropic-local-token-1234567890"
    assert runtime.extra_headers()["Authorization"] == "Bearer anthropic-local-token-1234567890"
    assert runtime.extra_headers()["anthropic-version"] == "2023-06-01"
    assert runtime.metadata["credential_strategy"] == "api_key_helper"
    assert runtime.metadata["source_auth_path"] == str(settings_path.resolve())


def test_claude_code_local_provider_resolves_runtime_from_credentials_api_key(monkeypatch, tmp_path):
    state_path = tmp_path / "claude.json"
    settings_path = tmp_path / "settings.json"
    credentials_path = tmp_path / ".credentials.json"
    managed_path = tmp_path / "managed-settings.json"
    state_path.write_text("{}", encoding="utf-8")
    settings_path.write_text("{}", encoding="utf-8")
    credentials_path.write_text(
        json.dumps({"anthropicApiKey": "anthropic-credential-token-1234567890"}),
        encoding="utf-8",
    )
    managed_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_STATE_PATH", str(state_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH", str(managed_path))

    provider = ClaudeCodeLocalAuthProvider()
    status = provider.status()
    runtime = provider.resolve_runtime({})

    assert status["configured"] is True
    assert status["runtime_available"] is True
    assert runtime.auth_transport == "anthropic_native"
    assert runtime.api_key == "anthropic-credential-token-1234567890"
    assert runtime.metadata["credential_strategy"] == "credential_file_api_key"
    assert runtime.metadata["source_auth_path"] == str(credentials_path.resolve())


def test_claude_code_local_provider_defaults_managed_settings_to_programdata(monkeypatch, tmp_path):
    program_data = tmp_path / "ProgramData"
    managed_path = program_data / "ClaudeCode" / "managed-settings.json"
    managed_path.parent.mkdir(parents=True)
    managed_path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("ProgramData", str(program_data))
    monkeypatch.setattr("backend.core.auth.providers.os.name", "nt")

    assert ClaudeCodeLocalAuthProvider.managed_settings_path() == managed_path.resolve()


def test_claude_code_local_provider_detects_system_keychain_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_STATE_PATH", str(tmp_path / "missing-state.json"))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_SETTINGS_PATH", str(tmp_path / "missing-settings.json"))
    monkeypatch.setenv("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH", str(tmp_path / "missing-managed.json"))
    monkeypatch.setattr(
        "backend.core.auth.providers._query_system_keychain_targets",
        lambda **kwargs: {
            "provider": "windows_credential_manager",
            "targets": ["LegacyGeneric:target=ClaudeCode/oauth"],
        },
    )

    provider = ClaudeCodeLocalAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is False
    assert status["keychain_provider"] == "windows_credential_manager"
    assert status["keychain_targets"] == ["LegacyGeneric:target=ClaudeCode/oauth"]
    assert status["keychain_locator"].startswith("keychain://windows_credential_manager/anthropic/")


def test_openai_codex_provider_reports_runtime_ready_with_oauth_tokens(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _encode_jwt_payload(
                        {
                            "https://api.openai.com/auth": {
                                "chatgpt_account_id": "acct_codex_123",
                            }
                        }
                    ),
                    "refresh_token": "refresh-codex-token",
                    "id_token": _encode_jwt_payload(
                        {
                            "email": "codex@example.com",
                            "name": "Codex User",
                        }
                    )
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_OPENAI_AUTH_PATH", str(auth_path))

    provider = OpenAICodexAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["runtime_available"] is True
    assert status["account_id"] == "acct_codex_123"
    assert status["account_label"] == "codex@example.com"
    assert status["account_email"] == "codex@example.com"
    assert str(auth_path.resolve()) in status["watch_paths"]


def test_openai_codex_provider_resolves_runtime_from_oauth_tokens(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _encode_jwt_payload(
                        {
                            "https://api.openai.com/auth": {
                                "chatgpt_account_id": "acct_codex_456",
                            }
                        }
                    ),
                    "refresh_token": "refresh-codex-token",
                    "id_token": _encode_jwt_payload({"email": "codex@example.com"}),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_OPENAI_AUTH_PATH", str(auth_path))

    provider = OpenAICodexAuthProvider()
    status = provider.status()
    runtime = provider.resolve_runtime({})

    assert status["configured"] is True
    assert status["runtime_available"] is True
    assert runtime.base_url == "https://chatgpt.com/backend-api"
    assert runtime.auth_transport == "openai_codex_responses"
    assert runtime.api_key() == _encode_jwt_payload(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_codex_456",
            }
        }
    )
    headers = runtime.extra_headers()
    assert headers["chatgpt-account-id"] == "acct_codex_456"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["originator"] == "wechat-chat"
    assert runtime.metadata["credential_strategy"] == "codex_oauth_access_token"
    assert runtime.metadata["source_auth_path"] == str(auth_path.resolve())


def test_google_gemini_cli_provider_runtime_ready_without_manual_project_field(monkeypatch, tmp_path):
    oauth_path = tmp_path / "oauth_creds.json"
    accounts_path = tmp_path / "google_accounts.json"
    oauth_path.write_text(
        json.dumps(
            {
                "access_token": "google-access-token-123",
                "refresh_token": "google-refresh-token-456",
                "project_id": "gemini-project-001",
                "expiry_date": 4102444800000,
                "id_token": _encode_jwt_payload({"email": "gemini@example.com", "name": "Gemini User"}),
            }
        ),
        encoding="utf-8",
    )
    accounts_path.write_text(
        json.dumps({"active": "gemini@example.com"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_GEMINI_OAUTH_PATH", str(oauth_path))
    monkeypatch.setenv("WECHAT_BOT_GEMINI_ACCOUNTS_PATH", str(accounts_path))

    provider = GoogleGeminiCliAuthProvider()
    status = provider.status()
    runtime = provider.resolve_runtime({})

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["runtime_available"] is True
    assert status["account_label"] == "gemini@example.com"
    assert status["account_email"] == "gemini@example.com"
    assert status["project_id"] == "gemini-project-001"
    assert runtime.base_url == "https://cloudcode-pa.googleapis.com"
    assert runtime.auth_transport == "google_code_assist"
    assert runtime.api_key() == "google-access-token-123"
    headers = runtime.extra_headers()
    assert headers["User-Agent"] == "google-api-nodejs-client/9.15.1"
    assert headers["X-Goog-Api-Client"] == "gl-node/22.17.0"
    assert headers["Accept"] == "text/event-stream"
    assert runtime.metadata["project_id"] == "gemini-project-001"


def test_kimi_code_local_provider_reads_share_dir_credentials(monkeypatch, tmp_path):
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
            ]
        ),
        encoding="utf-8",
    )
    credential_path = credentials_dir / "kimi.json"
    credential_path.write_text(
        json.dumps(
            {
                "access_token": "kimi-access-token-1234567890",
                "email": "moonshot@example.com",
                "name": "Moonshot Dev",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))

    provider = KimiCodeLocalAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["auth_path"] == str(credential_path.resolve())
    assert status["config_path"] == str((share_dir / "config.toml").resolve())
    assert "kimi-for-coding" in status["provider_names"]
    assert status["account_label"] == "moonshot@example.com"
    assert status["account_email"] == "moonshot@example.com"


def test_kimi_code_local_provider_resolves_runtime_from_config_api_key(monkeypatch, tmp_path):
    share_dir = tmp_path / ".kimi"
    credentials_dir = share_dir / "credentials"
    credentials_dir.mkdir(parents=True)
    config_path = share_dir / "config.toml"
    config_path.write_text(
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
    credential_path = credentials_dir / "kimi.json"
    credential_path.write_text(
        json.dumps({"access_token": "kimi-access-token-should-not-win"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))

    provider = KimiCodeLocalAuthProvider()
    status = provider.status()
    runtime = provider.resolve_runtime({})

    assert status["watch_paths"] == sorted(
        {
            str(config_path.resolve()),
            str(credentials_dir.resolve()),
            str(credential_path.resolve()),
        }
    )
    assert runtime.base_url == "https://api.kimi.com/coding/v1"
    assert runtime.metadata["provider_name"] == "kimi-for-coding"
    assert runtime.metadata["credential_strategy"] == "config_api_key"
    assert callable(runtime.api_key)
    assert runtime.api_key() == "ms-local-kimi-key-1234567890"


def test_kimi_code_local_provider_runtime_falls_back_to_oauth_credential_cache(monkeypatch, tmp_path):
    share_dir = tmp_path / ".kimi"
    credentials_dir = share_dir / "credentials"
    credentials_dir.mkdir(parents=True)
    config_path = share_dir / "config.toml"
    config_path.write_text(
        '\n'.join(
            [
                '[providers.kimi-for-coding]',
                'type = "kimi"',
                'base_url = "https://api.kimi.com/coding/v1"',
                'model = "kimi-k2-turbo-preview"',
            ]
        ),
        encoding="utf-8",
    )
    credential_path = credentials_dir / "kimi.json"
    credential_path.write_text(
        json.dumps({"access_token": "kimi-access-token-1234567890"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))

    provider = KimiCodeLocalAuthProvider()
    runtime = provider.resolve_runtime({})

    assert runtime.base_url == "https://api.kimi.com/coding/v1"
    assert runtime.metadata["credential_strategy"] == "oauth_credential_file"
    assert runtime.metadata["source_auth_path"] == str(credential_path.resolve())
    assert callable(runtime.api_key)
    assert runtime.api_key() == "kimi-access-token-1234567890"


def test_doubao_session_provider_detects_browser_cookie_db(monkeypatch, tmp_path):
    cookie_path = tmp_path / "Cookies"
    connection = sqlite3.connect(str(cookie_path))
    connection.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
    connection.execute(
        "INSERT INTO cookies (host_key, name) VALUES (?, ?)",
        (".doubao.com", "sessionid"),
    )
    connection.execute(
        "INSERT INTO cookies (host_key, name) VALUES (?, ?)",
        ("www.doubao.com", "passport_csrf_token"),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(
        "backend.core.auth.providers._iter_browser_cookie_dbs",
        lambda: [("Chrome", "Default", cookie_path)],
    )

    provider = DoubaoWebSessionProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["session_path"] == str(cookie_path)
    assert status["browser_name"] == "Chrome"
    assert status["browser_profile"] == "Default"
    assert status["cookie_count"] == 2
    assert status["auth_cookie_count"] >= 1


def test_yuanbao_session_provider_detects_browser_indexeddb_when_cookies_absent(monkeypatch, tmp_path):
    profile_dir = tmp_path / "Default"
    indexeddb_dir = profile_dir / "IndexedDB" / "https_yuanbao.tencent.com_0.indexeddb.leveldb"
    indexeddb_dir.mkdir(parents=True)
    (indexeddb_dir / "LOG").write_text("origin=https://yuanbao.tencent.com", encoding="utf-8")

    monkeypatch.setattr(
        "backend.core.auth.providers._iter_browser_profiles",
        lambda: [("Chrome", "Default", profile_dir)],
    )

    provider = TencentYuanbaoExperimentalAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is False
    assert status["indexeddb_path"] == str(indexeddb_dir.resolve())
    assert status["local_storage_kind"] == "browser_storage_probe"
    assert str(indexeddb_dir.resolve()) in status["watch_paths"]


def test_doubao_session_provider_detects_local_app_private_storage(monkeypatch, tmp_path):
    private_root = tmp_path / "ByteDance" / "Doubao" / "User Data" / "Default"
    indexeddb_dir = private_root / "IndexedDB" / "https_www.doubao.com_0.indexeddb.leveldb"
    local_storage_dir = private_root / "Local Storage" / "leveldb"
    indexeddb_dir.mkdir(parents=True)
    local_storage_dir.mkdir(parents=True)
    (indexeddb_dir / "LOG").write_text("origin=https://www.doubao.com", encoding="utf-8")
    (local_storage_dir / "LOG").write_text("doubao.com local storage", encoding="utf-8")
    monkeypatch.setenv("WECHAT_BOT_DOUBAO_PRIVATE_STORAGE_PATH", str(private_root.parent.parent))
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_cookie_dbs", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_profiles", lambda: [])

    provider = DoubaoWebSessionProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is False
    assert status["local_storage_kind"] == "local_app_private_storage"
    assert status["private_storage_path"] == str((private_root.parent.parent).resolve())
    assert status["indexeddb_path"] == str(indexeddb_dir.resolve())
    assert status["local_storage_path"] == str(local_storage_dir.resolve())
    assert str(indexeddb_dir.resolve()) in status["watch_paths"]


def test_yuanbao_session_provider_detects_private_auth_file_in_private_storage(monkeypatch, tmp_path):
    private_root = tmp_path / "Tencent" / "Yuanbao"
    session_path = private_root / "Storage" / "auth-session.json"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        json.dumps(
            {
                "user": {"name": "Yuanbao Dev", "email": "yuanbao@example.com"},
                "session": {"access_token": "yuanbao-session-token-1234567890"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_YUANBAO_PRIVATE_STORAGE_PATH", str(private_root))
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_cookie_dbs", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_profiles", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._iter_local_storage_roots", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._query_system_keychain_targets", lambda **kwargs: {})

    provider = TencentYuanbaoExperimentalAuthProvider()
    status = provider.status()

    assert status["detected"] is True
    assert status["configured"] is True
    assert status["local_storage_kind"] == "local_app_private_storage"
    assert status["private_auth_file_path"] == str(session_path.resolve())
    assert status["session_path"] == str(session_path.resolve())
    assert status["account_label"] == "yuanbao@example.com"
    assert status["account_email"] == "yuanbao@example.com"


def test_yuanbao_session_provider_skips_binary_noise_without_warning(monkeypatch, tmp_path, caplog):
    private_root = tmp_path / "Tencent" / "Yuanbao"
    noisy_dir = private_root / "Users" / "demo" / "media"
    noisy_dir.mkdir(parents=True)
    (private_root / "EBWebView" / "Default").mkdir(parents=True)
    (private_root / "EBWebView" / "Default" / "Vpn Tokens").write_bytes(b"\x8a\x00binary-token-store")
    (private_root / "EBWebView" / "Default" / "Vpn Tokens-journal").write_text("", encoding="utf-8")
    (private_root / "EBWebView" / "Default" / "Network").mkdir(parents=True)
    (private_root / "EBWebView" / "Default" / "Network" / "Trust Tokens").write_bytes(b"\x8a\x00trust-token-store")
    (private_root / "EBWebView" / "Default" / "Network" / "Trust Tokens-journal").write_text("", encoding="utf-8")
    (private_root / "QQNTOpenSDK" / "sdk_db").mkdir(parents=True)
    (private_root / "QQNTOpenSDK" / "sdk_db" / "login.db").write_bytes(b"\x90\x00sqlite")
    (private_root / "WeChat" / "ilink" / "wechat").mkdir(parents=True)
    (private_root / "WeChat" / "ilink" / "wechat" / "cloud_account.txt").write_text("not-json", encoding="utf-8")
    (noisy_dir / "auth_info_cache_v2.tk").write_bytes(b"\x80\x00token-cache")
    (noisy_dir / "auth_info_cache_v2.tv").write_bytes(b"\x80\x00token-cache")

    monkeypatch.setenv("WECHAT_BOT_YUANBAO_PRIVATE_STORAGE_PATH", str(private_root))
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_cookie_dbs", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._iter_browser_profiles", lambda: [])
    monkeypatch.setattr("backend.core.auth.providers._query_system_keychain_targets", lambda **kwargs: {})
    caplog.set_level(logging.WARNING)

    provider = TencentYuanbaoExperimentalAuthProvider()
    status = provider.status()

    assert status["detected"] is False
    assert status["configured"] is False
    assert not [
        record.message
        for record in caplog.records
        if "Failed to read auth state file" in record.message
        or "Failed to read auth state text file" in record.message
    ]
