from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx
from backend.core.provider_compat import ANTHROPIC_VERTEX_1M_BETA_HEADER

try:  # pragma: no cover - Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

try:  # pragma: no cover - Windows only
    import winreg  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - non-Windows fallback
    winreg = None

from .common import (
    decode_jwt_payload,
    generate_pkce_pair,
    normalize_text,
    open_browser_url,
    safe_read_json,
    safe_read_text_candidate,
    safe_write_json,
)
from .types import AuthSupportError

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_CLIENT_ID_ENV = "WECHAT_BOT_GEMINI_OAUTH_CLIENT_ID"
GOOGLE_OAUTH_CLIENT_SECRET_ENV = "WECHAT_BOT_GEMINI_OAUTH_CLIENT_SECRET"
GOOGLE_DEFAULT_LOCATION = "us-central1"
GOOGLE_REFRESH_SKEW_SEC = 60
GOOGLE_CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
GOOGLE_CODE_ASSIST_USER_AGENT = "google-api-nodejs-client/9.15.1"
GOOGLE_CODE_ASSIST_API_CLIENT = "gl-node/22.17.0"

OPENAI_CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
OPENAI_CODEX_AUTH_CLAIM_PATH = "https://api.openai.com/auth"

QWEN_AUTH_BASE_URL = "https://chat.qwen.ai"
QWEN_DEVICE_CODE_ENDPOINT = f"{QWEN_AUTH_BASE_URL}/api/v1/oauth2/device/code"
QWEN_TOKEN_ENDPOINT = f"{QWEN_AUTH_BASE_URL}/api/v1/oauth2/token"
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_SCOPE = "openid profile email model.completion"
QWEN_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

KIMI_DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
CLAUDE_BROWSER_LOGIN_URL = "https://claude.ai/"
KIMI_BROWSER_LOGIN_URL = "https://kimi.com/"
GENERIC_SESSION_COOKIE_HINTS = (
    "session",
    "sess",
    "sid",
    "token",
    "auth",
    "login",
    "passport",
    "uid",
    "user",
    "openid",
    "skey",
)

GENERIC_PRIVATE_STORAGE_HINTS = (
    "session",
    "auth",
    "token",
    "login",
    "cookie",
    "cookies",
    "storage",
    "indexeddb",
    "leveldb",
    "passport",
    "account",
    "profile",
)

KEYCHAIN_TARGET_PATTERN = re.compile(r"^\s*Target:\s*(.+?)\s*$", flags=re.IGNORECASE)
CLAUDE_API_KEY_HELPER_TTL_MS = 5 * 60 * 1000
CLAUDE_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-5"
CLAUDE_VERTEX_DEFAULT_LOCATION = "global"
CLAUDE_VERTEX_DEFAULT_MODEL = "claude-sonnet-4-6"
GCLOUD_ACCESS_TOKEN_TTL_MS = 5 * 60 * 1000


@dataclass(slots=True)
class ProviderRuntimeContext:
    api_key: str | Callable[[], str]
    base_url: Optional[str] = None
    extra_headers: Dict[str, str] | Callable[[], Dict[str, str]] | None = None
    refresh_auth: Callable[[], None] | None = None
    auth_transport: str = "openai_compatible"
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAuthProvider:
    id = ""
    provider_id = ""
    label = ""
    auth_type = "oauth"
    tier = "stable"
    supports_local_reuse = True
    requires_browser_flow = True
    requires_extra_fields: tuple[str, ...] = ()
    runtime_supported = True
    cli_name = ""
    local_source_label = "local_auth"

    def capability(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "label": self.label,
            "type": self.auth_type,
            "tier": self.tier,
            "supports_local_reuse": self.supports_local_reuse,
            "requires_browser_flow": self.requires_browser_flow,
            "requires_extra_fields": list(self.requires_extra_fields),
            "runtime_supported": self.runtime_supported,
            "experimental": self.tier != "stable",
            "local_source_label": self.local_source_label,
        }

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise AuthSupportError(f"{self.label} 暂不支持在应用内直接发起网页登录。")

    def cancel_flow(
        self,
        flow_state: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {"success": True, "message": f"{self.label} 登录流程已取消。"}

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "completed": False,
            "message": f"{self.label} 登录流程仍在等待完成。",
        }

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        raise NotImplementedError

    def logout_source(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise AuthSupportError(f"{self.label} 暂不支持退出源登录。")

    def _resolve_cli(self) -> str:
        command = normalize_text(self.cli_name)
        if not command:
            raise AuthSupportError(f"{self.label} 没有提供可用的 CLI 登录入口。")
        resolved = shutil.which(command)
        if not resolved:
            raise AuthSupportError(f"未找到命令 {command}，无法继续 {self.label} 登录。")
        return resolved

    def _run_cli_command(self, args: list[str]) -> Dict[str, Any]:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=False,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            message = normalize_text(completed.stderr) or normalize_text(completed.stdout)
            raise AuthSupportError(message or f"{self.label} 命令执行失败。")
        return {
            "success": True,
            "message": normalize_text(completed.stdout) or f"{self.label} 命令已执行完成。",
        }


class _ClaudeApiKeyHelperRuntime:
    def __init__(self, command: str) -> None:
        self._command = str(command or "").strip()
        self._lock = threading.Lock()
        self._cached_value = ""
        self._cached_at = 0.0

    @staticmethod
    def _ttl_ms() -> int:
        raw = normalize_text(os.environ.get("CLAUDE_CODE_API_KEY_HELPER_TTL_MS"))
        try:
            ttl_ms = int(raw)
        except (TypeError, ValueError):
            ttl_ms = CLAUDE_API_KEY_HELPER_TTL_MS
        return max(0, ttl_ms)

    def force_refresh(self) -> None:
        with self._lock:
            self._cached_value = ""
            self._cached_at = 0.0

    def _invoke_helper(self) -> str:
        try:
            helper_args = shlex.split(self._command, posix=(os.name != "nt"))
        except ValueError as exc:
            raise AuthSupportError(f"Claude apiKeyHelper 命令解析失败: {exc}") from exc
        if not helper_args:
            raise AuthSupportError("Claude apiKeyHelper 命令为空，无法执行。")
        completed = subprocess.run(
            helper_args,
            shell=False,
            capture_output=True,
            text=False,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            message = normalize_text(completed.stderr) or normalize_text(completed.stdout)
            raise AuthSupportError(message or "Claude apiKeyHelper 命令执行失败。")
        auth_value = normalize_text(completed.stdout)
        if not auth_value:
            raise AuthSupportError("Claude apiKeyHelper 没有返回可同步的凭据。")
        return auth_value

    def get_auth_value(self) -> str:
        ttl_ms = self._ttl_ms()
        with self._lock:
            age_ms = (time.time() - self._cached_at) * 1000 if self._cached_at else None
            if self._cached_value and age_ms is not None and age_ms < ttl_ms:
                return self._cached_value
            self._cached_value = self._invoke_helper()
            self._cached_at = time.time()
            return self._cached_value

    def build_headers(self) -> Dict[str, str]:
        auth_value = self.get_auth_value()
        return {
            "X-Api-Key": auth_value,
            "Authorization": f"Bearer {auth_value}",
            "anthropic-version": "2023-06-01",
        }


class _GCloudAccessTokenRuntime:
    def __init__(self, command: str) -> None:
        self._command = str(command or "").strip()
        self._lock = threading.Lock()
        self._cached_value = ""
        self._cached_at = 0.0

    @staticmethod
    def _ttl_ms() -> int:
        raw = normalize_text(os.environ.get("WECHAT_BOT_GCLOUD_ACCESS_TOKEN_TTL_MS"))
        try:
            ttl_ms = int(raw)
        except (TypeError, ValueError):
            ttl_ms = GCLOUD_ACCESS_TOKEN_TTL_MS
        return max(0, ttl_ms)

    def force_refresh(self) -> None:
        with self._lock:
            self._cached_value = ""
            self._cached_at = 0.0

    def _print_access_token(self) -> str:
        commands = (
            [self._command, "auth", "application-default", "print-access-token"],
            [self._command, "auth", "print-access-token"],
        )
        last_error = ""
        for args in commands:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=False,
                timeout=30,
                check=False,
            )
            if completed.returncode == 0:
                token = normalize_text(completed.stdout)
                if token:
                    return token
                last_error = "gcloud did not return a usable access token."
                continue
            last_error = normalize_text(completed.stderr) or normalize_text(completed.stdout)
        raise AuthSupportError(last_error or "Unable to obtain a Vertex AI access token from gcloud.")

    def get_access_token(self) -> str:
        with self._lock:
            ttl_ms = self._ttl_ms()
            now_ms = time.time() * 1000
            if ttl_ms > 0 and self._cached_value and (now_ms - self._cached_at) < ttl_ms:
                return self._cached_value
            self._cached_value = self._print_access_token()
            self._cached_at = now_ms
            return self._cached_value


def _safe_read_text(path: Path) -> str:
    return safe_read_text_candidate(path, log_label="auth state text file")


def _safe_read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    if tomllib is not None:
        try:
            with path.open("rb") as handle:
                payload = tomllib.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("Failed to parse TOML auth state file %s: %s", path, exc)
            return {}
    return {}


def _collect_scalar_entries(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            entries.extend(_collect_scalar_entries(value, next_prefix))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            next_prefix = f"{prefix}[{index}]"
            entries.extend(_collect_scalar_entries(value, next_prefix))
    else:
        normalized = normalize_text(payload)
        if normalized:
            entries.append((prefix, normalized))
    return entries


def _first_entry_value(entries: list[tuple[str, str]], *hints: str) -> str:
    lowered_hints = tuple(str(item or "").strip().lower() for item in hints if str(item or "").strip())
    for key, value in entries:
        lowered_key = key.lower()
        if any(hint in lowered_key for hint in lowered_hints):
            return value
    return ""


def _iter_browser_cookie_dbs() -> list[tuple[str, str, Path]]:
    resolved: list[tuple[str, str, Path]] = []
    for browser_name, profile_name, profile_dir in _iter_browser_profiles():
        for relative in ("Network/Cookies", "Cookies"):
            path = profile_dir / relative
            if path.exists():
                resolved.append((browser_name, profile_name, path))
    return resolved


def _iter_browser_profiles() -> list[tuple[str, str, Path]]:
    local_app_data_value = normalize_text(os.environ.get("LOCALAPPDATA"))
    app_data_value = normalize_text(os.environ.get("APPDATA"))
    local_app_data = Path(local_app_data_value) if local_app_data_value else None
    app_data = Path(app_data_value) if app_data_value else None
    candidates: list[tuple[str, Path]] = []
    if local_app_data is not None:
        candidates.extend(
            [
                ("Chrome", local_app_data / "Google" / "Chrome" / "User Data"),
                ("Edge", local_app_data / "Microsoft" / "Edge" / "User Data"),
                ("Brave", local_app_data / "BraveSoftware" / "Brave-Browser" / "User Data"),
            ]
        )
    if app_data is not None:
        candidates.append(("Opera", app_data / "Opera Software" / "Opera Stable"))
    if os.name != "nt":
        home = Path.home()
        candidates.extend(
            [
                ("Chrome", home / ".config" / "google-chrome"),
                ("Chromium", home / ".config" / "chromium"),
                ("Edge", home / ".config" / "microsoft-edge"),
                ("Brave", home / ".config" / "BraveSoftware" / "Brave-Browser"),
            ]
        )

    resolved: list[tuple[str, str, Path]] = []
    for browser_name, root in candidates:
        if not root.exists():
            continue
        if browser_name == "Opera":
            resolved.append((browser_name, "Opera Stable", root))
            continue

        profile_dirs = []
        for pattern in ("Default", "Profile *"):
            profile_dirs.extend(root.glob(pattern))
        seen_profiles: set[str] = set()
        for profile_dir in profile_dirs:
            if not profile_dir.is_dir():
                continue
            profile_name = profile_dir.name
            if profile_name in seen_profiles:
                continue
            seen_profiles.add(profile_name)
            resolved.append((browser_name, profile_name, profile_dir))
    return resolved


def _query_browser_cookie_db(
    path: Path,
    *,
    domains: tuple[str, ...],
    auth_cookie_hints: tuple[str, ...] = (),
) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    lowered_domains = tuple(f"%{str(domain or '').lstrip('.').lower()}" for domain in domains if str(domain or "").strip())
    if not lowered_domains:
        return {}
    query = " OR ".join("LOWER(host_key) LIKE ?" for _ in lowered_domains)
    cleanup_path: Path | None = None
    connection = None
    try:
        try:
            connection = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as handle:
                cleanup_path = Path(handle.name)
            shutil.copyfile(path, cleanup_path)
            connection = sqlite3.connect(str(cleanup_path), check_same_thread=False)
        cursor = connection.execute(
            f"SELECT host_key, name FROM cookies WHERE {query} LIMIT 200",
            lowered_domains,
        )
        rows = cursor.fetchall()
    except Exception as exc:
        logger.debug("Failed to inspect browser cookie DB %s: %s", path, exc)
        rows = []
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if cleanup_path is not None:
            try:
                cleanup_path.unlink(missing_ok=True)
            except Exception:
                pass
    if not rows:
        return {}
    cookie_names = [normalize_text(row[1]).lower() for row in rows if isinstance(row, tuple) and len(row) >= 2]
    hints = tuple(item.lower() for item in auth_cookie_hints if str(item or "").strip()) or GENERIC_SESSION_COOKIE_HINTS
    auth_cookie_count = sum(1 for name in cookie_names if any(hint in name for hint in hints))
    return {
        "cookie_count": len(rows),
        "auth_cookie_count": auth_cookie_count,
        "cookie_names": cookie_names,
    }


def _domain_variants(domains: tuple[str, ...]) -> tuple[str, ...]:
    variants: set[str] = set()
    for raw_domain in domains:
        domain = str(raw_domain or "").strip().lower().lstrip(".")
        if not domain:
            continue
        variants.add(domain)
        variants.add(domain.replace(".", "_"))
        variants.add(domain.replace(".", "-"))
        variants.add(domain.replace(".", "%2e"))
        variants.add(domain.replace(".", ""))
        if domain.startswith("www."):
            trimmed = domain[4:]
            variants.add(trimmed)
            variants.add(trimmed.replace(".", "_"))
            variants.add(trimmed.replace(".", "-"))
    return tuple(sorted(variants))


def _storage_name_matches_domain(name: str, domains: tuple[str, ...]) -> bool:
    lowered = normalize_text(name).lower()
    if not lowered:
        return False
    return any(variant in lowered for variant in _domain_variants(domains))


def _file_contains_domain_hint(path: Path, domains: tuple[str, ...], *, max_bytes: int = 131072) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            content = handle.read(max_bytes).lower()
    except Exception:
        return False
    return any(variant.encode("utf-8", errors="ignore") in content for variant in _domain_variants(domains))


def _find_browser_indexeddb_path(profile_dir: Path, domains: tuple[str, ...]) -> Path | None:
    root = profile_dir / "IndexedDB"
    if not root.exists() or not root.is_dir():
        return None
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if _storage_name_matches_domain(entry.name, domains):
            return entry
    return None


def _find_browser_local_storage_path(profile_dir: Path, domains: tuple[str, ...]) -> Path | None:
    root = profile_dir / "Local Storage"
    if root.exists() and root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if _storage_name_matches_domain(entry.name, domains):
                return entry
        leveldb_dir = root / "leveldb"
        if leveldb_dir.exists() and leveldb_dir.is_dir():
            for entry in sorted(leveldb_dir.iterdir(), key=lambda item: item.name.lower()):
                if _storage_name_matches_domain(entry.name, domains):
                    return entry
            for entry in sorted(leveldb_dir.iterdir(), key=lambda item: item.name.lower()):
                if not entry.is_file():
                    continue
                if entry.name in {"LOG", "LOG.old"} or entry.name.startswith("MANIFEST") or entry.suffix.lower() in {
                    ".ldb",
                    ".log",
                }:
                    if _file_contains_domain_hint(entry, domains):
                        return leveldb_dir
    return None


def _iter_local_storage_roots() -> list[Path]:
    roots: list[Path] = []
    env_names = ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA")
    for env_name in env_names:
        raw_value = normalize_text(os.environ.get(env_name))
        if not raw_value:
            continue
        path = Path(raw_value).expanduser()
        if path.exists() and path not in roots:
            roots.append(path)
    if os.name != "nt":
        for candidate in (Path.home() / ".config", Path.home() / ".local" / "share"):
            if candidate.exists() and candidate not in roots:
                roots.append(candidate)
    return roots


def _iter_named_storage_candidates(root: Path, name_hints: tuple[str, ...], *, max_depth: int = 2) -> list[Path]:
    normalized_hints = tuple(
        str(item or "").strip().lower()
        for item in name_hints
        if str(item or "").strip()
    )
    if not normalized_hints or not root.exists() or not root.is_dir():
        return []
    matched: list[Path] = []
    seen: set[str] = set()
    frontier = [root]
    for _depth in range(max(0, int(max_depth)) + 1):
        next_frontier: list[Path] = []
        for current in frontier:
            try:
                entries = sorted(
                    [entry for entry in current.iterdir() if entry.is_dir()],
                    key=lambda item: item.name.lower(),
                )
            except Exception:
                continue
            for entry in entries:
                lowered_name = entry.name.lower()
                if not any(hint in lowered_name for hint in normalized_hints):
                    continue
                resolved_key = str(entry.resolve()).lower()
                if resolved_key in seen:
                    continue
                seen.add(resolved_key)
                matched.append(entry)
                next_frontier.append(entry)
        frontier = next_frontier
        if not frontier:
            break
    return matched


def _iter_profile_like_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path | None) -> None:
        if path is None or not path.exists():
            return
        resolved = str(path.resolve()).lower()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(path)

    _add(root)
    for relative in (
        "Default",
        "Profile 1",
        "User Data",
        "User Data/Default",
        "UserData",
        "UserData/Default",
        "Storage",
        "Partitions",
    ):
        _add(root / relative)
    try:
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            lowered_name = child.name.lower()
            if any(token in lowered_name for token in ("default", "profile", "storage", "userdata", "user data")):
                _add(child)
    except Exception:
        pass
    return candidates


def _iter_candidate_auth_files(
    root: Path,
    *,
    name_hints: tuple[str, ...],
    domains: tuple[str, ...],
    max_depth: int = 3,
) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    normalized_name_hints = tuple(
        str(item or "").strip().lower()
        for item in (name_hints + GENERIC_PRIVATE_STORAGE_HINTS)
        if str(item or "").strip()
    )
    domain_hints = _domain_variants(domains)
    allowed_suffixes = {".json", ".toml", ".txt", ".conf", ".config", ".dat", ".db", ".sqlite"}
    matched: list[Path] = []
    seen: set[str] = set()
    frontier = [root]
    for _depth in range(max(0, int(max_depth)) + 1):
        next_frontier: list[Path] = []
        for current in frontier:
            try:
                entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
            except Exception:
                continue
            for entry in entries:
                if entry.is_dir():
                    next_frontier.append(entry)
                    continue
                if not entry.is_file():
                    continue
                lowered_name = entry.name.lower()
                suffix = entry.suffix.lower()
                if suffix not in allowed_suffixes and not any(token in lowered_name for token in ("session", "token", "auth")):
                    continue
                if not (
                    any(hint in lowered_name for hint in normalized_name_hints)
                    or any(hint in lowered_name for hint in domain_hints)
                    or _file_contains_domain_hint(entry, domains, max_bytes=32768)
                ):
                    continue
                resolved = str(entry.resolve()).lower()
                if resolved in seen:
                    continue
                seen.add(resolved)
                matched.append(entry)
        frontier = next_frontier
        if not frontier:
            break
    return matched


def _extract_keychain_targets(raw_text: str) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for line in str(raw_text or "").splitlines():
        match = KEYCHAIN_TARGET_PATTERN.search(line)
        if not match:
            continue
        target = normalize_text(match.group(1))
        if not target:
            continue
        lowered = target.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(target)
    return targets


def _query_system_keychain_targets(
    *,
    env_names: tuple[str, ...] = (),
    name_hints: tuple[str, ...] = (),
) -> Dict[str, Any]:
    env_targets: list[str] = []
    for env_name in env_names:
        raw_value = normalize_text(os.environ.get(env_name))
        if not raw_value:
            continue
        env_targets.extend(
            item.strip()
            for item in raw_value.split(",")
            if item.strip()
        )
    if env_targets:
        return {
            "provider": "env_override",
            "targets": sorted(dict.fromkeys(env_targets)),
        }
    if os.name != "nt":
        return {}
    try:
        completed = subprocess.run(
            ["cmdkey", "/list"],
            capture_output=True,
            text=False,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        logger.debug("Failed to inspect Windows Credential Manager: %s", exc)
        return {}
    if completed.returncode != 0:
        logger.debug(
            "cmdkey /list failed with code %s: %s",
            completed.returncode,
            normalize_text(completed.stderr) or normalize_text(completed.stdout),
        )
        return {}
    all_targets = _extract_keychain_targets(normalize_text(completed.stdout))
    if not all_targets:
        return {}
    normalized_hints = tuple(
        str(item or "").strip().lower()
        for item in name_hints
        if str(item or "").strip()
    )
    if normalized_hints:
        matched = [
            target
            for target in all_targets
            if any(hint in target.lower() for hint in normalized_hints)
        ]
    else:
        matched = all_targets
    if not matched:
        return {}
    return {
        "provider": "windows_credential_manager",
        "targets": matched,
    }


def _build_keychain_locator(provider_id: str, keychain_provider: str, targets: list[str]) -> str:
    if not targets:
        return ""
    provider = normalize_text(keychain_provider or "keychain").lower() or "keychain"
    wanted_provider = normalize_text(provider_id).lower() or "provider"
    first_target = re.sub(r"[^a-z0-9._-]+", "-", targets[0].strip().lower()).strip("-")
    return f"keychain://{provider}/{wanted_provider}/{first_target or 'credential'}"


def _collect_profile_storage_artifacts(
    root: Path,
    *,
    domains: tuple[str, ...],
    auth_cookie_hints: tuple[str, ...],
) -> Dict[str, Any]:
    cookie_path: Path | None = None
    for relative in ("Network/Cookies", "Cookies"):
        candidate = root / relative
        if candidate.exists() and candidate.is_file():
            cookie_path = candidate
            break
    cookie_details = (
        _query_browser_cookie_db(cookie_path, domains=domains, auth_cookie_hints=auth_cookie_hints)
        if cookie_path
        else {}
    )
    indexeddb_path = _find_browser_indexeddb_path(root, domains)
    local_storage_path = _find_browser_local_storage_path(root, domains)
    watch_paths: list[str] = []
    for candidate in (cookie_path, indexeddb_path, local_storage_path):
        if candidate is not None:
            normalized = str(candidate.resolve())
            if normalized not in watch_paths:
                watch_paths.append(normalized)
    if not watch_paths:
        return {}
    return {
        "session_path": watch_paths[0],
        "cookie_path": str(cookie_path.resolve()) if cookie_path is not None else "",
        "indexeddb_path": str(indexeddb_path.resolve()) if indexeddb_path is not None else "",
        "local_storage_path": str(local_storage_path.resolve()) if local_storage_path is not None else "",
        "watch_paths": watch_paths,
        "cookie_count": int(cookie_details.get("cookie_count") or 0),
        "auth_cookie_count": int(cookie_details.get("auth_cookie_count") or 0),
    }


def _score_storage_artifacts(payload: Dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if bool(payload.get("auth_cookie_count")) else 0,
        int(payload.get("cookie_count") or 0),
        1 if bool(payload.get("indexeddb_path")) else 0,
        1 if bool(payload.get("local_storage_path")) else 0,
    )


def _extract_private_session_file(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = safe_read_json(path)
    if payload:
        entries = _collect_scalar_entries(payload)
        account_email = _first_entry_value(entries, "email")
        account_label = _first_entry_value(entries, "name", "nickname", "displayname", "user")
        token_count = sum(
            1
            for key, value in entries
            if any(hint in key.lower() for hint in ("session", "token", "auth", "refresh", "access"))
            and len(value) >= 16
        )
        return {
            "configured": bool(token_count),
            "account_email": account_email,
            "account_label": account_label,
        }
    raw_text = _safe_read_text(path)
    if not raw_text:
        return {}
    token_like = (
        re.search(
            r"(session|token|auth|cookie|access|refresh)[^\r\n:=]{0,32}[:=][^\r\n]{8,}",
            raw_text,
            flags=re.IGNORECASE,
        ) is not None
        or re.search(r"[A-Za-z0-9_-]{3,}\s*=\s*[^;\s]{16,}", raw_text) is not None
    )
    if not token_like:
        return {}
    return {
        "configured": False,
        "account_email": "",
        "account_label": path.stem,
    }


def _build_system_keychain_status(
    *,
    provider_id: str,
    label: str,
    env_names: tuple[str, ...] = (),
    name_hints: tuple[str, ...] = (),
) -> Dict[str, Any]:
    result = _query_system_keychain_targets(env_names=env_names, name_hints=name_hints)
    targets = [str(item).strip() for item in (result.get("targets") or []) if str(item).strip()]
    if not targets:
        return {}
    keychain_provider = normalize_text(result.get("provider")) or "system_keychain"
    return {
        "source_kind": "system_keychain",
        "keychain_provider": keychain_provider,
        "keychain_targets": targets,
        "keychain_locator": _build_keychain_locator(provider_id, keychain_provider, targets),
        "detected": True,
        "configured": False,
        "account_label": label,
        "account_email": "",
        "message": f"已在 {keychain_provider.replace('_', ' ')} 中检测到与该服务方相关的凭据。",
    }


def _extract_claude_session_metadata(payload: Dict[str, Any]) -> Dict[str, str]:
    entries = _collect_scalar_entries(payload)
    session_candidates = [
        value
        for key, value in entries
        if any(hint in key.lower() for hint in ("oauth", "session", "token", "access", "refresh"))
        and len(value) >= 16
    ]
    account_email = _first_entry_value(entries, "email")
    account_label = _first_entry_value(entries, "displayname", "name", "organization", "workspace")
    return {
        "has_session": "1" if bool(session_candidates) else "",
        "account_email": account_email,
        "account_label": account_label,
    }


def _extract_kimi_credential_metadata(payload: Dict[str, Any]) -> Dict[str, str]:
    entries = _collect_scalar_entries(payload)
    account_email = _first_entry_value(entries, "email")
    account_label = _first_entry_value(entries, "display_name", "displayname", "name", "nickname")
    token_value = _first_entry_value(entries, "access_token", "refresh_token", "id_token", "token")
    expires_at = _first_entry_value(entries, "expires_at", "expiry", "expires")
    return {
        "account_email": account_email,
        "account_label": account_label,
        "token_value": token_value,
        "expires_at": expires_at,
    }


def _looks_like_placeholder_secret(value: Any) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return True
    upper = normalized.upper()
    return upper.startswith("YOUR_") or normalized in {"<api-key>", "<token>", "<secret>"}


def _parse_simple_toml_sections(text: str) -> Dict[str, Dict[str, str]]:
    sections: Dict[str, Dict[str, str]] = {}
    current_section = ""
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        section_match = re.match(r"^\[([^\]]+)\]\s*$", line)
        if section_match:
            current_section = str(section_match.group(1) or "").strip()
            if current_section:
                sections.setdefault(current_section, {})
            continue
        if not current_section:
            continue
        value_match = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"\s*$', line)
        if value_match:
            sections.setdefault(current_section, {})[str(value_match.group(1) or "").strip()] = str(
                value_match.group(2) or ""
            ).strip()
    return sections


def _read_kimi_runtime_config(path: Path) -> Dict[str, str]:
    payload = _safe_read_toml(path)
    top_level_default_model = ""
    providers: Dict[str, Dict[str, str]] = {}
    models: Dict[str, Dict[str, str]] = {}
    if payload:
        top_level_default_model = normalize_text(
            payload.get("default_model") or payload.get("model") or payload.get("defaultModel")
        )
        raw_providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
        for name, raw_provider in raw_providers.items():
            if not isinstance(raw_provider, dict):
                continue
            normalized_name = normalize_text(name)
            if not normalized_name:
                continue
            providers[normalized_name] = {
                "type": normalize_text(raw_provider.get("type")),
                "base_url": normalize_text(raw_provider.get("base_url")),
                "api_key": normalize_text(raw_provider.get("api_key")),
                "model": normalize_text(raw_provider.get("model")),
            }
        raw_models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
        for name, raw_model in raw_models.items():
            if not isinstance(raw_model, dict):
                continue
            normalized_name = normalize_text(name)
            if not normalized_name:
                continue
            models[normalized_name] = {
                "provider": normalize_text(raw_model.get("provider")),
                "model": normalize_text(raw_model.get("model")),
            }
    else:
        text = _safe_read_text(path)
        if not text:
            return {}
        top_level_default_model_match = re.search(
            r'^\s*(?:default_model|model)\s*=\s*"([^"]+)"\s*$',
            text,
            flags=re.MULTILINE,
        )
        top_level_default_model = (
            normalize_text(top_level_default_model_match.group(1)) if top_level_default_model_match else ""
        )
        sections = _parse_simple_toml_sections(text)
        for section_name, values in sections.items():
            if section_name.startswith("providers."):
                provider_name = normalize_text(section_name.split(".", 1)[1])
                if not provider_name:
                    continue
                providers[provider_name] = {
                    "type": normalize_text(values.get("type")),
                    "base_url": normalize_text(values.get("base_url")),
                    "api_key": normalize_text(values.get("api_key")),
                    "model": normalize_text(values.get("model")),
                }
            elif section_name.startswith("models."):
                model_name = normalize_text(section_name.split(".", 1)[1])
                if not model_name:
                    continue
                models[model_name] = {
                    "provider": normalize_text(values.get("provider")),
                    "model": normalize_text(values.get("model")),
                }

    preferred_provider_names: list[str] = []
    if top_level_default_model:
        preferred_model = models.get(top_level_default_model) or {}
        preferred_provider = normalize_text(preferred_model.get("provider"))
        if preferred_provider:
            preferred_provider_names.append(preferred_provider)
    if "kimi-for-coding" in providers:
        preferred_provider_names.append("kimi-for-coding")
    preferred_provider_names.extend(
        provider_name
        for provider_name, provider_cfg in providers.items()
        if normalize_text(provider_cfg.get("type")) == "kimi"
    )

    seen: set[str] = set()
    for provider_name in preferred_provider_names:
        normalized_name = normalize_text(provider_name)
        if not normalized_name or normalized_name in seen:
            continue
        seen.add(normalized_name)
        provider_cfg = providers.get(normalized_name) or {}
        if normalize_text(provider_cfg.get("type")) != "kimi":
            continue
        model_name = normalize_text(provider_cfg.get("model"))
        if top_level_default_model:
            preferred_model = models.get(top_level_default_model) or {}
            if normalize_text(preferred_model.get("provider")) == normalized_name:
                model_name = normalize_text(preferred_model.get("model")) or model_name or top_level_default_model
        api_key = normalize_text(provider_cfg.get("api_key"))
        base_url = normalize_text(provider_cfg.get("base_url")) or KIMI_DEFAULT_BASE_URL
        if api_key and not _looks_like_placeholder_secret(api_key):
            return {
                "provider_name": normalized_name,
                "api_key": api_key,
                "base_url": base_url,
                "model": model_name,
            }
        if base_url or model_name:
            return {
                "provider_name": normalized_name,
                "api_key": "",
                "base_url": base_url,
                "model": model_name,
            }
    return {}


def _summarize_kimi_config(path: Path) -> Dict[str, str]:
    payload = _safe_read_toml(path)
    if payload:
        providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
        provider_names = ", ".join(sorted(str(name) for name in providers.keys())) if providers else ""
        model = normalize_text(payload.get("model"))
        return {
            "provider_names": provider_names,
            "model": model,
        }
    text = _safe_read_text(path)
    if not text:
        return {}
    provider_names = sorted(set(re.findall(r"^\s*\[providers\.([^\]]+)\]\s*$", text, flags=re.MULTILINE)))
    model_match = re.search(r'^\s*model\s*=\s*"([^"]+)"\s*$', text, flags=re.MULTILINE)
    return {
        "provider_names": ", ".join(provider_names),
        "model": model_match.group(1) if model_match else "",
    }


class OpenAICodexAuthProvider(BaseAuthProvider):
    id = "openai_codex"
    provider_id = "openai"
    label = "OpenAI Codex / ChatGPT 登录"
    cli_name = "codex"
    local_source_label = "codex_auth_json"

    @staticmethod
    def auth_path() -> Path:
        env_override = normalize_text(os.environ.get("WECHAT_BOT_OPENAI_AUTH_PATH"))
        if env_override:
            return Path(env_override).expanduser().resolve()
        codex_home = normalize_text(os.environ.get("CODEX_HOME"))
        if codex_home:
            return Path(codex_home).expanduser().resolve() / "auth.json"
        return Path.home() / ".codex" / "auth.json"

    def _load_auth(self) -> Dict[str, Any]:
        return safe_read_json(self.auth_path())

    @staticmethod
    def _extract_account_id(access_token: str) -> str:
        claims = decode_jwt_payload(normalize_text(access_token))
        auth_claims = claims.get(OPENAI_CODEX_AUTH_CLAIM_PATH) if isinstance(claims, dict) else {}
        if isinstance(auth_claims, dict):
            return normalize_text(auth_claims.get("chatgpt_account_id"))
        return ""

    def _read_state(self) -> Dict[str, Any]:
        payload = self._load_auth()
        tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
        id_claims = decode_jwt_payload(normalize_text(tokens.get("id_token")))
        access_token = normalize_text(tokens.get("access_token"))
        refresh_token = normalize_text(tokens.get("refresh_token"))
        openai_api_key = normalize_text(payload.get("OPENAI_API_KEY"))
        account_id = self._extract_account_id(access_token)
        return {
            "payload": payload,
            "tokens": tokens,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "openai_api_key": openai_api_key,
            "account_id": account_id,
            "email": normalize_text(id_claims.get("email")),
            "name": normalize_text(id_claims.get("name")),
        }

    def _refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        response = httpx.post(
            OPENAI_CODEX_TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OPENAI_CODEX_OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthSupportError("Codex OAuth 刷新返回了无效响应。")
        access_token = normalize_text(payload.get("access_token"))
        next_refresh_token = normalize_text(payload.get("refresh_token"))
        if not access_token:
            raise AuthSupportError("Codex OAuth 刷新后没有返回 access_token。")
        account_id = self._extract_account_id(access_token)
        if not account_id:
            raise AuthSupportError("Codex OAuth 刷新后无法解析账号信息。")
        return {
            "access_token": access_token,
            "refresh_token": next_refresh_token or refresh_token,
            "account_id": account_id,
        }

    def _get_runtime_access_token(self, *, force_refresh: bool = False) -> str:
        state = self._read_state()
        if state["access_token"] and not force_refresh:
            return state["access_token"]
        refresh_token = state["refresh_token"]
        if not refresh_token:
            raise AuthSupportError("当前缺少可同步的 Codex refresh_token，请重新完成登录。")
        refreshed = self._refresh_access_token(refresh_token)
        payload = dict(state["payload"])
        tokens = dict(state["tokens"])
        tokens["access_token"] = refreshed["access_token"]
        tokens["refresh_token"] = refreshed["refresh_token"]
        payload["tokens"] = tokens
        payload["last_refresh"] = int(time.time())
        safe_write_json(self.auth_path(), payload)
        return refreshed["access_token"]

    def _force_runtime_refresh(self) -> None:
        self._get_runtime_access_token(force_refresh=True)

    def _build_runtime_headers(self) -> Dict[str, str]:
        state = self._read_state()
        token = state["access_token"] or self._get_runtime_access_token()
        account_id = state["account_id"] or self._extract_account_id(token)
        if not account_id:
            raise AuthSupportError("当前 Codex 登录态缺少账号标识，请重新登录。")
        return {
            "chatgpt-account-id": account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "wechat-chat",
            "accept": "text/event-stream",
        }

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = self._read_state()
        detected = bool(state["payload"])
        configured = bool(state["access_token"] or state["refresh_token"] or state["openai_api_key"])
        runtime_unavailable_reason = ""
        if detected and not configured:
            runtime_unavailable_reason = (
                "已检测到本机 Codex / ChatGPT 登录，但当前没有可用的访问凭据。"
            )
        return {
            **self.capability(),
            "cli_name": self.cli_name,
            "cli_available": bool(shutil.which(self.cli_name)),
            "auth_path": str(self.auth_path()),
            "detected": detected,
            "configured": configured,
            "runtime_available": configured,
            "runtime_unavailable_reason": runtime_unavailable_reason,
            "account_label": state["email"] or state["name"] or "本机 ChatGPT 登录",
            "account_email": state["email"],
            "account_id": state["account_id"],
            "watch_paths": [str(self.auth_path().resolve())],
            "message": (
                "已检测到可同步的 Codex / ChatGPT 登录，可直接用于对话。"
                if configured
                else (
                    "已检测到本机 Codex / ChatGPT 登录，但暂时还不能直接用于 API 请求。"
                    if detected
                    else "还没有检测到可同步的 Codex / ChatGPT 登录。"
                )
            ),
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        subprocess.Popen(
            [command, "login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "DETACHED_PROCESS", 0))
            | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            start_new_session=True,
        )
        return {
            "success": True,
            "completed": False,
            "message": "已启动 Codex 浏览器登录。请先在浏览器完成授权，再回来刷新状态。",
        }

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        return ProviderRuntimeContext(
            api_key=self._get_runtime_access_token,
            base_url=OPENAI_CODEX_BASE_URL,
            extra_headers=self._build_runtime_headers,
            refresh_auth=self._force_runtime_refresh,
            auth_transport="openai_codex_responses",
            metadata={
                "source_auth_path": str(self.auth_path().resolve()),
                "credential_strategy": "codex_oauth_access_token",
            },
        )

    def logout_source(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        return self._run_cli_command([command, "logout"])


class GoogleGeminiCliAuthProvider(BaseAuthProvider):
    id = "google_gemini_cli"
    provider_id = "google"
    label = "Google Gemini CLI"
    cli_name = "gemini"
    tier = "experimental"
    requires_extra_fields = ("oauth_project_id",)
    local_source_label = "gemini_cli_oauth"

    def __init__(self) -> None:
        self._refresh_lock = threading.Lock()

    @staticmethod
    def oauth_creds_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_GEMINI_OAUTH_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".gemini" / "oauth_creds.json"

    @staticmethod
    def google_accounts_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_GEMINI_ACCOUNTS_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".gemini" / "google_accounts.json"

    def _load_creds(self) -> Dict[str, Any]:
        return safe_read_json(self.oauth_creds_path())

    def _load_accounts(self) -> Dict[str, Any]:
        return safe_read_json(self.google_accounts_path())

    @staticmethod
    def _resolve_google_oauth_client_config(creds: Optional[Dict[str, Any]] = None) -> tuple[str, str]:
        creds = creds if isinstance(creds, dict) else {}
        nested_config = {}
        for key in ("installed", "web", "client", "oauth_client"):
            value = creds.get(key)
            if isinstance(value, dict):
                nested_config = value
                break
        client_id = normalize_text(
            os.environ.get(GOOGLE_OAUTH_CLIENT_ID_ENV)
            or creds.get("client_id")
            or nested_config.get("client_id")
        )
        client_secret = normalize_text(
            os.environ.get(GOOGLE_OAUTH_CLIENT_SECRET_ENV)
            or creds.get("client_secret")
            or nested_config.get("client_secret")
        )
        return client_id, client_secret

    @staticmethod
    def _parse_expiry_ms(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _read_state(self) -> Dict[str, Any]:
        creds = self._load_creds()
        accounts = self._load_accounts()
        id_claims = decode_jwt_payload(normalize_text(creds.get("id_token")))
        active_email = normalize_text(accounts.get("active")) or normalize_text(id_claims.get("email"))
        expiry_ms = self._parse_expiry_ms(creds.get("expiry_date"))
        remaining_sec = None
        if expiry_ms is not None:
            remaining_sec = int((expiry_ms / 1000) - time.time())
        return {
            "creds": creds,
            "accounts": accounts,
            "email": active_email,
            "display_name": normalize_text(id_claims.get("name")),
            "expiry_ms": expiry_ms,
            "remaining_sec": remaining_sec,
            "has_access_token": bool(normalize_text(creds.get("access_token"))),
            "has_refresh_token": bool(normalize_text(creds.get("refresh_token"))),
            "project_id": normalize_text(
                creds.get("project_id")
                or creds.get("cloudaicompanion_project")
                or accounts.get("project_id")
            ),
        }

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = self._read_state()
        remaining_sec = state["remaining_sec"]
        if remaining_sec is None:
            expiry_label = "未记录 Access Token 过期时间。"
        elif remaining_sec >= 0:
            expiry_label = f"Access Token 预计还有约 {max(0, remaining_sec // 60)} 分钟过期。"
        else:
            expiry_label = "Access Token 已过期，会在需要时自动刷新。"
        configured = bool(state["has_access_token"] or state["has_refresh_token"])
        return {
            **self.capability(),
            "cli_name": self.cli_name,
            "cli_available": bool(shutil.which(self.cli_name)),
            "oauth_creds_path": str(self.oauth_creds_path()),
            "google_accounts_path": str(self.google_accounts_path()),
            "detected": bool(state["creds"]),
            "configured": configured,
            "runtime_available": configured,
            "account_label": state["email"] or state["display_name"] or "本机 Google 账号",
            "account_email": state["email"] or "",
            "refresh_ready": bool(state["has_refresh_token"]),
            "project_id": state["project_id"],
            "message": (
                f"已检测到可同步的 Gemini CLI 登录，可直接用于对话。{expiry_label}"
                if configured
                else "还没有检测到可同步的 Gemini CLI 登录。"
            ),
            "risk_notice": (
                "Gemini CLI 登录同步仍属于实验能力。启用前建议先确认官方文档里的账号与授权限制。"
            ),
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        subprocess.Popen(
            [command, "auth", "login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "DETACHED_PROCESS", 0))
            | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            start_new_session=True,
        )
        return {
            "success": True,
            "completed": False,
            "message": "已启动 Gemini CLI 登录。请先在浏览器完成登录，再回来刷新状态。",
        }

    def _refresh_access_token(self, refresh_token: str, creds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        client_id, client_secret = self._resolve_google_oauth_client_config(creds)
        if not client_id or not client_secret:
            raise AuthSupportError(
                "Gemini CLI 登录缺少可用的 Google OAuth client 配置，无法自动刷新 Access Token。"
                f" 请重新执行 gemini auth login，或通过环境变量 {GOOGLE_OAUTH_CLIENT_ID_ENV} /"
                f" {GOOGLE_OAUTH_CLIENT_SECRET_ENV} 提供运行时配置。"
            )
        response = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthSupportError("Google OAuth 刷新返回了无效响应。")
        if payload.get("error"):
            detail = normalize_text(payload.get("error_description")) or normalize_text(payload.get("error"))
            raise AuthSupportError(detail or "Google OAuth 刷新失败。")
        access_token = normalize_text(payload.get("access_token"))
        if not access_token:
            raise AuthSupportError("Google OAuth 刷新后没有返回 Access Token。")
        return payload

    def _get_fresh_access_token(self, *, force_refresh: bool = False) -> str:
        with self._refresh_lock:
            state = self._read_state()
            creds = dict(state["creds"])
            access_token = normalize_text(creds.get("access_token"))
            refresh_token = normalize_text(creds.get("refresh_token"))
            remaining_sec = state["remaining_sec"]
            if access_token and not force_refresh and remaining_sec is not None and remaining_sec > GOOGLE_REFRESH_SKEW_SEC:
                return access_token
            if access_token and not force_refresh and remaining_sec is None:
                return access_token
            if not refresh_token:
                raise AuthSupportError("Gemini CLI 登录缺少 refresh_token，无法自动刷新。")

            refreshed = self._refresh_access_token(refresh_token, creds)
            creds["access_token"] = normalize_text(refreshed.get("access_token"))
            creds["token_type"] = normalize_text(refreshed.get("token_type")) or normalize_text(
                creds.get("token_type")
            ) or "Bearer"
            creds["scope"] = normalize_text(refreshed.get("scope")) or normalize_text(creds.get("scope"))
            if refreshed.get("id_token"):
                creds["id_token"] = refreshed.get("id_token")
            try:
                expires_in_sec = max(0, int(refreshed.get("expires_in") or 0))
            except (TypeError, ValueError):
                expires_in_sec = 0
            if expires_in_sec:
                creds["expiry_date"] = int((time.time() + expires_in_sec) * 1000)
            safe_write_json(self.oauth_creds_path(), creds)
            return normalize_text(creds.get("access_token"))

    def _force_runtime_refresh(self) -> None:
        self._get_fresh_access_token(force_refresh=True)

    @staticmethod
    def _env_google_project_id() -> str:
        return normalize_text(
            os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
            or os.environ.get("GCLOUD_PROJECT")
        )

    @staticmethod
    def _code_assist_request_headers(access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": GOOGLE_CODE_ASSIST_USER_AGENT,
            "X-Goog-Api-Client": GOOGLE_CODE_ASSIST_API_CLIENT,
        }

    def _poll_code_assist_operation(self, operation_name: str, headers: Dict[str, str]) -> Dict[str, Any]:
        attempt = 0
        while True:
            if attempt > 0:
                time.sleep(5.0)
            response = httpx.get(
                f"{GOOGLE_CODE_ASSIST_ENDPOINT}/v1internal/{operation_name}",
                headers=headers,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise AuthSupportError("Google Code Assist 返回了无效的轮询响应。")
            if payload.get("done"):
                return payload
            attempt += 1

    def _discover_project_id(self, access_token: str) -> str:
        env_project_id = self._env_google_project_id()
        headers = self._code_assist_request_headers(access_token)
        metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        }
        if env_project_id:
            metadata["duetProject"] = env_project_id
        load_payload: Dict[str, Any] = {"metadata": metadata}
        if env_project_id:
            load_payload["cloudaicompanionProject"] = env_project_id
        response = httpx.post(
            f"{GOOGLE_CODE_ASSIST_ENDPOINT}/v1internal:loadCodeAssist",
            headers=headers,
            json=load_payload,
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthSupportError("Google Code Assist 返回了无效的项目状态。")
        existing_project = normalize_text(payload.get("cloudaicompanionProject"))
        if existing_project:
            return existing_project
        if payload.get("currentTier"):
            if env_project_id:
                return env_project_id
            raise AuthSupportError(
                "当前 Google 账号需要绑定 Google Cloud Project，且服务端没有返回可复用项目。"
            )

        allowed_tiers = payload.get("allowedTiers") if isinstance(payload.get("allowedTiers"), list) else []
        default_tier = next(
            (item for item in allowed_tiers if isinstance(item, dict) and item.get("isDefault")),
            allowed_tiers[0] if allowed_tiers else {"id": "legacy-tier"},
        )
        tier_id = normalize_text(default_tier.get("id")) or "legacy-tier"
        if tier_id != "free-tier" and not env_project_id:
            raise AuthSupportError(
                "当前 Google 账号需要先设置 GOOGLE_CLOUD_PROJECT，登录后才能直接用于对话。"
            )

        onboard_payload: Dict[str, Any] = {
            "tierId": tier_id,
            "metadata": metadata,
        }
        if tier_id != "free-tier" and env_project_id:
            onboard_payload["cloudaicompanionProject"] = env_project_id

        onboard = httpx.post(
            f"{GOOGLE_CODE_ASSIST_ENDPOINT}/v1internal:onboardUser",
            headers=headers,
            json=onboard_payload,
            timeout=20.0,
        )
        onboard.raise_for_status()
        operation = onboard.json()
        if not isinstance(operation, dict):
            raise AuthSupportError("Google Code Assist 返回了无效的开通响应。")
        if not operation.get("done") and normalize_text(operation.get("name")):
            operation = self._poll_code_assist_operation(normalize_text(operation.get("name")), headers)

        response_payload = operation.get("response") if isinstance(operation.get("response"), dict) else {}
        project_payload = (
            response_payload.get("cloudaicompanionProject")
            if isinstance(response_payload.get("cloudaicompanionProject"), dict)
            else {}
        )
        project_id = normalize_text(project_payload.get("id")) or env_project_id
        if not project_id:
            raise AuthSupportError("Google Code Assist 没有返回可用的项目标识。")
        creds = dict(self._load_creds())
        creds["project_id"] = project_id
        safe_write_json(self.oauth_creds_path(), creds)
        return project_id

    def _resolve_project_id(self, settings: Dict[str, Any]) -> str:
        project_id = normalize_text(settings.get("oauth_project_id"))
        if project_id:
            return project_id
        state = self._read_state()
        if state["project_id"]:
            return state["project_id"]
        access_token = self._get_fresh_access_token()
        return self._discover_project_id(access_token)

    @staticmethod
    def _build_runtime_headers() -> Dict[str, str]:
        return {
            "User-Agent": GOOGLE_CODE_ASSIST_USER_AGENT,
            "X-Goog-Api-Client": GOOGLE_CODE_ASSIST_API_CLIENT,
            "Accept": "text/event-stream",
        }

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        project_id = self._resolve_project_id(settings)
        return ProviderRuntimeContext(
            api_key=self._get_fresh_access_token,
            base_url=GOOGLE_CODE_ASSIST_ENDPOINT,
            extra_headers=self._build_runtime_headers,
            refresh_auth=self._force_runtime_refresh,
            auth_transport="google_code_assist",
            metadata={"project_id": project_id},
        )

    def logout_source(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        return self._run_cli_command([command, "auth", "logout"])


class QwenOAuthProvider(BaseAuthProvider):
    id = "qwen_oauth"
    provider_id = "qwen"
    label = "Qwen OAuth 登录"
    local_source_label = "qwen_oauth_creds"

    @staticmethod
    def oauth_creds_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_QWEN_OAUTH_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".qwen" / "oauth_creds.json"

    def _load_creds(self) -> Dict[str, Any]:
        return safe_read_json(self.oauth_creds_path())

    @staticmethod
    def _parse_expiry_ts(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        raw = str(value).strip()
        try:
            if len(raw) >= 13:
                return int(raw) / 1000.0
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _read_state(self) -> Dict[str, Any]:
        creds = self._load_creds()
        id_claims = decode_jwt_payload(normalize_text(creds.get("id_token")))
        access_token = normalize_text(creds.get("access_token"))
        refresh_token = normalize_text(creds.get("refresh_token"))
        expiry_ts = (
            self._parse_expiry_ts(creds.get("expires_at"))
            or self._parse_expiry_ts(creds.get("expiry_date"))
            or self._parse_expiry_ts(creds.get("expires_at_ms"))
        )
        remaining_sec = None
        if expiry_ts is not None:
            remaining_sec = int(expiry_ts - time.time())
        return {
            "creds": creds,
            "display_name": normalize_text(id_claims.get("name")) or normalize_text(creds.get("name")),
            "email": normalize_text(id_claims.get("email")) or normalize_text(creds.get("email")),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expiry_ts": expiry_ts,
            "remaining_sec": remaining_sec,
            "resource_url": normalize_text(creds.get("resource_url")),
        }

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = self._read_state()
        remaining_sec = state["remaining_sec"]
        if remaining_sec is None:
            expiry_label = "未记录 Token 过期时间。"
        elif remaining_sec >= 0:
            expiry_label = f"Access Token 预计还有约 {max(0, remaining_sec // 60)} 分钟过期。"
        else:
            expiry_label = "Access Token 已过期，会在需要时自动刷新。"
        configured = bool(state["access_token"] or state["refresh_token"])
        return {
            **self.capability(),
            "oauth_creds_path": str(self.oauth_creds_path()),
            "detected": bool(state["creds"]),
            "configured": configured,
            "account_label": state["email"] or state["display_name"] or "本机 Qwen 登录",
            "account_email": state["email"] or "",
            "resource_url": state["resource_url"],
            "message": (
                f"已检测到可同步的 Qwen OAuth 登录。{expiry_label}"
                if configured
                else "还没有检测到可同步的 Qwen OAuth 登录。"
            ),
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        code_verifier, code_challenge = generate_pkce_pair()
        response = httpx.post(
            QWEN_DEVICE_CODE_ENDPOINT,
            data={
                "client_id": QWEN_OAUTH_CLIENT_ID,
                "scope": QWEN_OAUTH_SCOPE,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthSupportError("Qwen OAuth 设备码接口返回了无效响应。")
        device_code = normalize_text(payload.get("device_code"))
        verification_uri = normalize_text(payload.get("verification_uri_complete")) or normalize_text(
            payload.get("verification_uri")
        )
        if not device_code or not verification_uri:
            raise AuthSupportError("Qwen OAuth 设备码响应缺少必要字段。")
        open_browser_url(verification_uri)
        interval = 5
        try:
            interval = max(2, int(payload.get("interval") or 5))
        except (TypeError, ValueError):
            interval = 5
        return {
            "success": True,
            "completed": False,
            "message": "已打开 Qwen 授权页。请先完成登录授权，再回来继续。",
            "verification_uri": verification_uri,
            "user_code": normalize_text(payload.get("user_code")),
            "recommended_poll_interval_sec": interval,
            "flow_state": {
                "device_code": device_code,
                "code_verifier": code_verifier,
                "interval": interval,
                "started_at": time.time(),
                "verification_uri": verification_uri,
            },
        }

    def cancel_flow(
        self,
        flow_state: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {"success": True, "message": "已取消等待中的 Qwen OAuth 授权流程。"}

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = dict(flow_state or {})
        device_code = normalize_text(state.get("device_code"))
        code_verifier = normalize_text(state.get("code_verifier"))
        if not device_code:
            raise AuthSupportError("Qwen OAuth 授权流程缺少 device_code。")
        response = httpx.post(
            QWEN_TOKEN_ENDPOINT,
            data={
                "client_id": QWEN_OAUTH_CLIENT_ID,
                "grant_type": QWEN_DEVICE_GRANT_TYPE,
                "device_code": device_code,
                "code_verifier": code_verifier,
            },
            timeout=15.0,
        )
        body = response.json()
        if not isinstance(body, dict):
            raise AuthSupportError("Qwen OAuth Token 接口返回了无效响应。")
        error_code = normalize_text(body.get("error"))
        if response.status_code >= 400 or error_code:
            if error_code in {"authorization_pending", "slow_down"}:
                interval = state.get("interval")
                try:
                    interval = max(2, int(body.get("interval") or interval or 5))
                except (TypeError, ValueError):
                    interval = 5
                state["interval"] = interval
                return {
                    "success": True,
                    "completed": False,
                    "pending": True,
                    "flow_state": state,
                    "recommended_poll_interval_sec": interval,
                    "message": "Qwen 授权仍在等待完成。请先在浏览器完成登录，再回来继续。",
                }
            detail = normalize_text(body.get("error_description")) or error_code
            raise AuthSupportError(detail or "Qwen OAuth Token 交换失败。")
        access_token = normalize_text(body.get("access_token"))
        refresh_token = normalize_text(body.get("refresh_token"))
        if not access_token:
            raise AuthSupportError("Qwen OAuth Token 交换后没有返回 Access Token。")
        expires_in = 0
        try:
            expires_in = max(0, int(body.get("expires_in") or 0))
        except (TypeError, ValueError):
            expires_in = 0
        payload_to_save = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": normalize_text(body.get("id_token")),
            "scope": normalize_text(body.get("scope")) or QWEN_OAUTH_SCOPE,
            "token_type": normalize_text(body.get("token_type")) or "Bearer",
            "resource_url": normalize_text(body.get("resource_url")),
            "expires_at": int(time.time() + expires_in) if expires_in else None,
            "updated_at": int(time.time()),
        }
        safe_write_json(
            self.oauth_creds_path(),
            {key: value for key, value in payload_to_save.items() if value not in (None, "")},
        )
        return {
            "success": True,
            "completed": True,
            "message": "Qwen OAuth 登录已完成，本地授权信息也已更新。",
        }

    def _refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        response = httpx.post(
            QWEN_TOKEN_ENDPOINT,
            data={
                "client_id": QWEN_OAUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthSupportError("Qwen OAuth 刷新返回了无效响应。")
        if payload.get("error"):
            detail = normalize_text(payload.get("error_description")) or normalize_text(payload.get("error"))
            raise AuthSupportError(detail or "Qwen OAuth 刷新失败。")
        access_token = normalize_text(payload.get("access_token"))
        if not access_token:
            raise AuthSupportError("Qwen OAuth 刷新后没有返回 Access Token。")
        return payload

    def _get_fresh_access_token(self) -> str:
        state = self._read_state()
        creds = dict(state["creds"])
        access_token = normalize_text(creds.get("access_token"))
        refresh_token = normalize_text(creds.get("refresh_token"))
        remaining_sec = state["remaining_sec"]
        if access_token and remaining_sec is not None and remaining_sec > 60:
            return access_token
        if access_token and remaining_sec is None:
            return access_token
        if not refresh_token:
            raise AuthSupportError("Qwen OAuth 登录缺少 refresh_token，无法自动刷新。")
        refreshed = self._refresh_access_token(refresh_token)
        creds["access_token"] = normalize_text(refreshed.get("access_token"))
        creds["refresh_token"] = normalize_text(refreshed.get("refresh_token")) or refresh_token
        creds["id_token"] = normalize_text(refreshed.get("id_token")) or normalize_text(creds.get("id_token"))
        creds["resource_url"] = normalize_text(refreshed.get("resource_url")) or normalize_text(
            creds.get("resource_url")
        )
        creds["scope"] = normalize_text(refreshed.get("scope")) or normalize_text(creds.get("scope"))
        creds["token_type"] = normalize_text(refreshed.get("token_type")) or normalize_text(
            creds.get("token_type")
        ) or "Bearer"
        try:
            expires_in_sec = max(0, int(refreshed.get("expires_in") or 0))
        except (TypeError, ValueError):
            expires_in_sec = 0
        if expires_in_sec:
            creds["expires_at"] = int(time.time() + expires_in_sec)
        safe_write_json(self.oauth_creds_path(), {k: v for k, v in creds.items() if v not in (None, "")})
        return normalize_text(creds.get("access_token"))

    @staticmethod
    def _build_headers() -> Dict[str, str]:
        return {"X-DashScope-AuthType": "qwen-oauth"}

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        return ProviderRuntimeContext(
            api_key=self._get_fresh_access_token,
            base_url=normalize_text(settings.get("base_url")) or QWEN_DEFAULT_BASE_URL,
            extra_headers=self._build_headers,
            auth_transport="qwen_dashscope_oauth",
        )

    def logout_source(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        creds_path = self.oauth_creds_path()
        if creds_path.exists():
            creds_path.unlink()
        return {"success": True, "message": "本机 Qwen OAuth 凭据已移除。"}


class ClaudeCodeLocalAuthProvider(BaseAuthProvider):
    id = "claude_code_local"
    provider_id = "anthropic"
    label = "Claude Code 本机登录"
    auth_type = "local_import"
    tier = "experimental"
    runtime_supported = True
    cli_name = "claude"
    local_source_label = "claude_code_local"
    keychain_env_vars = ("WECHAT_BOT_CLAUDE_KEYCHAIN_TARGETS",)
    keychain_target_hints = ("claude", "anthropic")

    @staticmethod
    def state_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_CLAUDE_STATE_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".claude.json"

    @staticmethod
    def settings_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_CLAUDE_SETTINGS_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".claude" / "settings.json"

    @staticmethod
    def credentials_path() -> Path:
        config_dir = normalize_text(os.environ.get("CLAUDE_CONFIG_DIR"))
        if config_dir:
            return Path(config_dir).expanduser().resolve() / ".credentials.json"
        override = normalize_text(os.environ.get("WECHAT_BOT_CLAUDE_CREDENTIALS_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".claude" / ".credentials.json"

    @staticmethod
    def managed_settings_path() -> Path:
        override = normalize_text(os.environ.get("WECHAT_BOT_CLAUDE_MANAGED_SETTINGS_PATH"))
        if override:
            return Path(override).expanduser().resolve()
        if os.name == "nt":
            program_data = normalize_text(os.environ.get("ProgramData")) or "C:/ProgramData"
            managed_path = Path(program_data) / "ClaudeCode" / "managed-settings.json"
            if managed_path.exists():
                return managed_path.resolve()
            program_files = normalize_text(os.environ.get("ProgramFiles")) or "C:/Program Files"
            legacy_path = Path(program_files) / "ClaudeCode" / "managed-settings.json"
            if legacy_path.exists():
                return legacy_path.resolve()
            return managed_path
        if os.name == "posix" and "darwin" in str(os.uname()).lower():  # pragma: no cover - non-Windows path
            return Path("/Library/Application Support/ClaudeCode/managed-settings.json")
        return Path("/etc/claude-code/managed-settings.json")

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state_payload = safe_read_json(self.state_path())
        settings_payload = safe_read_json(self.settings_path())
        credentials_payload = safe_read_json(self.credentials_path())
        managed_payload = safe_read_json(self.managed_settings_path())
        keychain_status = _build_system_keychain_status(
            provider_id=self.provider_id,
            label="Claude Code 钥匙串凭据",
            env_names=self.keychain_env_vars,
            name_hints=self.keychain_target_hints,
        )
        metadata = _extract_claude_session_metadata(state_payload)
        helper_command = normalize_text(settings_payload.get("apiKeyHelper")) or normalize_text(
            managed_payload.get("apiKeyHelper")
        )
        credential_entries = _collect_scalar_entries(credentials_payload)
        credential_api_key = _first_entry_value(
            credential_entries,
            "anthropic_api_key",
            "api_key",
            "apikey",
        )
        if _looks_like_placeholder_secret(credential_api_key):
            credential_api_key = ""
        account_email = normalize_text(metadata.get("account_email"))
        account_label = normalize_text(metadata.get("account_label"))
        runtime_available = bool(helper_command or credential_api_key)
        configured = bool(metadata.get("has_session") or helper_command or credential_api_key)
        detected = bool(state_payload or settings_payload or credentials_payload or managed_payload or keychain_status)
        if helper_command and not account_label:
            account_label = "Claude Code API Helper"
        elif credential_api_key and not account_label:
            account_label = "Claude Code API 凭据缓存"
        if keychain_status and not account_label:
            account_label = normalize_text(keychain_status.get("account_label")) or account_label
        detail = (
            "已检测到可同步的 Claude Code 本机登录源。"
            if configured
            else "还没有检测到可同步的 Claude Code 本机登录源。"
        )
        if helper_command:
            detail = f"{detail} 已发现 apiKeyHelper 配置。"
        elif credential_api_key:
            detail = f"{detail} 已发现可同步的 Claude API 凭据缓存。"
        elif metadata.get("has_session"):
            detail = (
                f"{detail} 已检测到 Claude 订阅登录态，但当前运行时仍需要 apiKeyHelper 或本机 Claude API 凭据。"
            )
        runtime_unavailable_reason = ""
        if configured and not runtime_available:
            runtime_unavailable_reason = (
                "当前只检测到了 Claude 订阅登录态。运行时调用仍需要 apiKeyHelper 或可同步的 Claude API 凭据缓存。"
            )
        if keychain_status:
            detail = f"{detail} 同时检测到了 Claude 相关的系统钥匙串目标。"
        watch_paths = [
            str(path)
            for path in (
                self.state_path(),
                self.settings_path(),
                self.credentials_path(),
                self.managed_settings_path(),
            )
            if path.exists()
        ]
        return {
            **self.capability(),
            "cli_name": self.cli_name,
            "cli_available": bool(shutil.which(self.cli_name)),
            "auth_path": str(self.state_path()),
            "config_path": str(self.settings_path()),
            "credentials_path": str(self.credentials_path()),
            "managed_settings_path": str(self.managed_settings_path()),
            "watch_paths": watch_paths,
            "detected": detected,
            "configured": configured,
            "runtime_available": runtime_available,
            "runtime_unavailable_reason": runtime_unavailable_reason,
            "account_label": account_email or account_label or "Claude Code 本机登录",
            "account_email": account_email,
            "api_key_helper": helper_command,
            "keychain_provider": str(keychain_status.get("keychain_provider") or "").strip(),
            "keychain_targets": list(keychain_status.get("keychain_targets") or []),
            "keychain_locator": str(keychain_status.get("keychain_locator") or "").strip(),
            "message": detail,
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        open_browser_url(CLAUDE_BROWSER_LOGIN_URL)
        return {
            "success": True,
            "completed": False,
            "message": (
                "已打开 Claude 登录页。请先在 Claude Code 完成登录，等本机凭据更新后再回来继续。"
            ),
        }

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status = self.status(settings)
        if status.get("configured") or status.get("detected"):
            return {
                "success": True,
                "completed": True,
                "message": "Claude Code 本机登录现在已经可用了。",
            }
        return {
            "success": True,
            "completed": False,
            "message": "还没有检测到 Claude Code 本机登录。请先完成登录，再回来重试。",
        }

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        settings_payload = safe_read_json(self.settings_path())
        managed_payload = safe_read_json(self.managed_settings_path())
        credentials_payload = safe_read_json(self.credentials_path())
        helper_command = normalize_text(settings_payload.get("apiKeyHelper")) or normalize_text(
            managed_payload.get("apiKeyHelper")
        )
        if helper_command:
            helper_runtime = _ClaudeApiKeyHelperRuntime(helper_command)
            return ProviderRuntimeContext(
                api_key=helper_runtime.get_auth_value,
                extra_headers=helper_runtime.build_headers,
                refresh_auth=helper_runtime.force_refresh,
                base_url=normalize_text(settings.get("base_url")) or CLAUDE_DEFAULT_BASE_URL,
                auth_transport="anthropic_native",
                metadata={
                    "credential_strategy": "api_key_helper",
                    "source_auth_path": (
                        str(self.settings_path())
                        if normalize_text(settings_payload.get("apiKeyHelper"))
                        else str(self.managed_settings_path())
                    ),
                    "credentials_path": str(self.credentials_path()),
                    "model_hint": normalize_text(settings.get("model")) or CLAUDE_DEFAULT_MODEL,
                },
            )
        entries = _collect_scalar_entries(credentials_payload)
        credential_api_key = _first_entry_value(
            entries,
            "anthropic_api_key",
            "api_key",
            "apikey",
        )
        if credential_api_key and not _looks_like_placeholder_secret(credential_api_key):
            return ProviderRuntimeContext(
                api_key=credential_api_key,
                base_url=normalize_text(settings.get("base_url")) or CLAUDE_DEFAULT_BASE_URL,
                auth_transport="anthropic_native",
                metadata={
                    "credential_strategy": "credential_file_api_key",
                    "source_auth_path": str(self.credentials_path()),
                    "model_hint": normalize_text(settings.get("model")) or CLAUDE_DEFAULT_MODEL,
                },
            )
        raise AuthSupportError(
            "已经检测到 Claude Code 本机登录，但当前运行时仍需要 `apiKeyHelper` 或 ~/.claude/.credentials.json "
            "里的可同步 Claude API 凭据。仅订阅态 OAuth 目前只用于状态跟随与同步，暂不会直接投射到 Anthropic API 运行时。"
        )


class ClaudeVertexLocalAuthProvider(BaseAuthProvider):
    id = "claude_vertex_local"
    provider_id = "anthropic"
    label = "Claude Vertex AI 本机认证"
    auth_type = "local_import"
    tier = "experimental"
    runtime_supported = True
    cli_name = "gcloud"
    local_source_label = "claude_vertex_local"
    requires_extra_fields = ("oauth_project_id", "oauth_location")

    @staticmethod
    def gcloud_config_dir() -> Path:
        override = normalize_text(os.environ.get("CLOUDSDK_CONFIG"))
        if override:
            return Path(override).expanduser().resolve()
        if os.name == "nt":
            appdata = normalize_text(os.environ.get("APPDATA"))
            if appdata:
                return Path(appdata).expanduser().resolve() / "gcloud"
            return Path.home() / "AppData" / "Roaming" / "gcloud"
        return Path.home() / ".config" / "gcloud"

    @classmethod
    def application_default_credentials_path(cls) -> Path:
        override = normalize_text(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        if override:
            return Path(override).expanduser().resolve()
        return cls.gcloud_config_dir() / "application_default_credentials.json"

    @classmethod
    def config_default_path(cls) -> Path:
        return cls.gcloud_config_dir() / "configurations" / "config_default"

    @classmethod
    def active_config_path(cls) -> Path:
        return cls.gcloud_config_dir() / "active_config"

    def _load_adc_payload(self) -> Dict[str, Any]:
        return safe_read_json(self.application_default_credentials_path())

    @staticmethod
    def _normalize_gcloud_value(value: Any) -> str:
        normalized = normalize_text(value)
        if normalized.lower() in {"(unset)", "unset", "none"}:
            return ""
        return normalized

    def _run_gcloud_value(self, *args: str) -> str:
        command = shutil.which(self.cli_name)
        if not command:
            return ""
        completed = subprocess.run(
            [command, *args],
            capture_output=True,
            text=False,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            return ""
        for line in normalize_text(completed.stdout).splitlines():
            candidate = self._normalize_gcloud_value(line)
            if candidate:
                return candidate
        return ""

    @staticmethod
    def _resolve_location_from_environment() -> str:
        return normalize_text(
            os.environ.get("CLOUD_ML_REGION")
            or os.environ.get("GOOGLE_CLOUD_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_REGION")
        )

    @staticmethod
    def _resolve_project_id_from_environment() -> str:
        return normalize_text(
            os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
            or os.environ.get("GCLOUD_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
        )

    def _resolve_status_project_id(self, settings: Optional[Dict[str, Any]] = None) -> str:
        payload = settings if isinstance(settings, dict) else {}
        direct = normalize_text(payload.get("oauth_project_id"))
        if direct:
            return direct
        env_project = self._resolve_project_id_from_environment()
        if env_project:
            return env_project
        adc_payload = self._load_adc_payload()
        for key in ("project_id", "quota_project_id"):
            candidate = normalize_text(adc_payload.get(key))
            if candidate:
                return candidate
        return self._run_gcloud_value("config", "get-value", "project", "--quiet")

    def _resolve_status_location(self, settings: Optional[Dict[str, Any]] = None) -> str:
        payload = settings if isinstance(settings, dict) else {}
        return (
            normalize_text(payload.get("oauth_location"))
            or self._resolve_location_from_environment()
            or CLAUDE_VERTEX_DEFAULT_LOCATION
        )

    @staticmethod
    def _extract_adc_account_label(adc_payload: Dict[str, Any]) -> tuple[str, str]:
        service_account_email = normalize_text(adc_payload.get("client_email"))
        if service_account_email:
            return service_account_email, service_account_email
        quota_project = normalize_text(adc_payload.get("quota_project_id"))
        if quota_project:
            return f"GCloud ADC ({quota_project})", ""
        return "", ""

    @staticmethod
    def _has_adc_credentials(adc_payload: Dict[str, Any]) -> bool:
        return bool(
            normalize_text(adc_payload.get("refresh_token"))
            or normalize_text(adc_payload.get("client_email"))
            or normalize_text(adc_payload.get("type"))
        )

    @staticmethod
    def _build_vertex_base_url(project_id: str, location: str) -> str:
        normalized_project = normalize_text(project_id)
        normalized_location = normalize_text(location) or CLAUDE_VERTEX_DEFAULT_LOCATION
        if not normalized_project:
            raise AuthSupportError("Claude Vertex AI 运行时缺少可用的项目 ID。")
        return (
            f"https://{normalized_location}-aiplatform.googleapis.com/v1/projects/"
            f"{normalized_project}/locations/{normalized_location}/publishers/anthropic/models"
        )

    @staticmethod
    def _build_runtime_headers(project_id: str, model: str) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        normalized_project = normalize_text(project_id)
        if normalized_project:
            headers["X-Goog-User-Project"] = normalized_project
        if normalize_text(model).lower().endswith("[1m]"):
            headers["anthropic-beta"] = ANTHROPIC_VERTEX_1M_BETA_HEADER
        return headers

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        adc_path = self.application_default_credentials_path()
        adc_payload = self._load_adc_payload()
        cli_available = bool(shutil.which(self.cli_name))
        configured = self._has_adc_credentials(adc_payload)
        detected = bool(configured or adc_path.exists())
        project_id = self._resolve_status_project_id(settings)
        location = self._resolve_status_location(settings)
        account_label, account_email = self._extract_adc_account_label(adc_payload)
        if cli_available and not account_email:
            account_email = self._run_gcloud_value("config", "get-value", "account", "--quiet")
        if account_email and not account_label:
            account_label = account_email
        runtime_available = bool(configured and cli_available and project_id)
        runtime_unavailable_reason = ""
        if configured and not cli_available:
            runtime_unavailable_reason = "已检测到 Google Cloud 凭据，但当前机器缺少 gcloud，无法直接用于 Vertex AI 对话。"
        elif configured and not project_id:
            runtime_unavailable_reason = "已检测到 Google Cloud 凭据，但还缺少可用的 Vertex 项目 ID。"
        watch_paths = [
            str(path)
            for path in (
                adc_path,
                self.config_default_path(),
                self.active_config_path(),
            )
            if path.exists()
        ]
        message = (
            f"已检测到可同步的 Vertex AI 本机认证，可直接用于 Claude 对话。项目 {project_id or '未设置'}，区域 {location}。"
            if runtime_available
            else "还没有检测到可直接用于 Claude on Vertex AI 的本机 Google Cloud 凭据。"
        )
        return {
            **self.capability(),
            "cli_name": self.cli_name,
            "cli_available": cli_available,
            "auth_path": str(adc_path),
            "config_path": str(self.config_default_path()),
            "watch_paths": watch_paths,
            "detected": detected,
            "configured": configured,
            "runtime_available": runtime_available,
            "runtime_unavailable_reason": runtime_unavailable_reason,
            "account_label": account_label or "Google Cloud ADC",
            "account_email": account_email,
            "project_id": project_id,
            "location": location,
            "message": message,
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        subprocess.Popen(
            [command, "auth", "application-default", "login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "DETACHED_PROCESS", 0))
            | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            start_new_session=True,
        )
        return {
            "success": True,
            "completed": False,
            "message": "已启动 gcloud 浏览器登录。请先完成 Google Cloud 授权，再回来刷新本机状态。",
        }

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status = self.status(settings)
        if status.get("configured") or status.get("detected"):
            return {
                "success": True,
                "completed": True,
                "message": "Claude Vertex AI 本机认证现在已经可用了。",
            }
        return {
            "success": True,
            "completed": False,
            "message": "还没有检测到可用的 Vertex AI 本机认证。请先完成 gcloud 登录，再回来重试。",
        }

    def _resolve_project_id(self, settings: Dict[str, Any]) -> str:
        project_id = self._resolve_status_project_id(settings)
        if project_id:
            return project_id
        raise AuthSupportError(
            "Claude Vertex AI 缺少项目 ID。请填写 oauth_project_id，或先配置 ANTHROPIC_VERTEX_PROJECT_ID / "
            "GOOGLE_CLOUD_PROJECT / GCLOUD_PROJECT。"
        )

    def _resolve_location(self, settings: Dict[str, Any]) -> str:
        return self._resolve_status_location(settings)

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        command = self._resolve_cli()
        project_id = self._resolve_project_id(settings)
        location = self._resolve_location(settings)
        runtime = _GCloudAccessTokenRuntime(command)
        model = normalize_text(settings.get("model")) or CLAUDE_VERTEX_DEFAULT_MODEL
        return ProviderRuntimeContext(
            api_key=runtime.get_access_token,
            base_url=self._build_vertex_base_url(project_id, location),
            extra_headers=lambda: self._build_runtime_headers(project_id, model),
            refresh_auth=runtime.force_refresh,
            auth_transport="anthropic_vertex",
            metadata={
                "project_id": project_id,
                "location": location,
                "source_auth_path": str(self.application_default_credentials_path()),
                "credential_strategy": "gcloud_application_default",
                "model_hint": model,
            },
        )

    def logout_source(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        command = self._resolve_cli()
        return self._run_cli_command([command, "auth", "application-default", "revoke", "--quiet"])


class KimiCodeLocalAuthProvider(BaseAuthProvider):
    id = "kimi_code_local"
    provider_id = "kimi"
    label = "Kimi Code 本机登录"
    auth_type = "oauth"
    tier = "experimental"
    runtime_supported = True
    cli_name = "kimi"
    local_source_label = "kimi_code_credentials"
    keychain_env_vars = ("WECHAT_BOT_KIMI_KEYCHAIN_TARGETS",)
    keychain_target_hints = ("kimi", "moonshot")

    @staticmethod
    def share_dir() -> Path:
        override = normalize_text(os.environ.get("KIMI_SHARE_DIR"))
        if override:
            return Path(override).expanduser().resolve()
        env_override = normalize_text(os.environ.get("WECHAT_BOT_KIMI_SHARE_DIR"))
        if env_override:
            return Path(env_override).expanduser().resolve()
        return Path.home() / ".kimi"

    def config_path(self) -> Path:
        return self.share_dir() / "config.toml"

    def credentials_dir(self) -> Path:
        return self.share_dir() / "credentials"

    def _credential_files(self) -> list[Path]:
        directory = self.credentials_dir()
        if not directory.exists() or not directory.is_dir():
            return []
        return sorted(
            [path for path in directory.glob("*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        )

    def _load_best_credential(self) -> tuple[Path | None, Dict[str, Any], Dict[str, str]]:
        for path in self._credential_files():
            payload = safe_read_json(path)
            if not payload:
                continue
            metadata = _extract_kimi_credential_metadata(payload)
            if metadata.get("token_value"):
                return path, payload, metadata
        return None, {}, {}

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        keychain_status = _build_system_keychain_status(
            provider_id=self.provider_id,
            label="Kimi Code 钥匙串凭据",
            env_names=self.keychain_env_vars,
            name_hints=self.keychain_target_hints,
        )
        config_summary = _summarize_kimi_config(self.config_path())
        runtime_config = _read_kimi_runtime_config(self.config_path())
        config_api_key = normalize_text(runtime_config.get("api_key"))
        config_api_key_available = bool(config_api_key and not _looks_like_placeholder_secret(config_api_key))
        credential_path, _, credential_metadata = self._load_best_credential()
        account_email = normalize_text(credential_metadata.get("account_email"))
        account_label = normalize_text(credential_metadata.get("account_label"))
        detected = bool(credential_path or self.config_path().exists() or keychain_status)
        configured = bool(credential_path or config_api_key_available)
        runtime_available = configured
        provider_names = normalize_text(config_summary.get("provider_names"))
        model_name = normalize_text(config_summary.get("model"))
        watch_paths = [str(self.config_path())]
        credentials_dir = self.credentials_dir()
        if credentials_dir.exists():
            watch_paths.append(str(credentials_dir.resolve()))
        if credential_path is not None:
            watch_paths.append(str(credential_path.resolve()))
        if keychain_status and not account_label:
            account_label = normalize_text(keychain_status.get("account_label")) or account_label
        if config_api_key_available and not account_label:
            account_label = "Kimi Code API Key"
        message = (
            "已检测到可同步的 Kimi Code 本机登录源。"
            if configured
            else "还没有检测到可同步的 Kimi Code 本机登录源。"
        )
        if config_api_key_available:
            message = f"{message} 宸插彂鐜?config.toml 涓殑 Kimi Code API Key锛屽彲鐩存帴鐢ㄤ簬瀵硅瘽銆?"
        if provider_names:
            message = f"{message} 当前配置的 Provider：{provider_names}。"
        if model_name:
            message = f"{message} 当前模型提示：{model_name}。"
        if keychain_status:
            message = f"{message} 同时检测到了 Kimi 相关的系统钥匙串目标。"
        return {
            **self.capability(),
            "cli_name": self.cli_name,
            "cli_available": bool(shutil.which(self.cli_name)),
            "auth_path": str(credential_path) if credential_path else "",
            "config_path": str(self.config_path()),
            "detected": detected,
            "configured": configured,
            "runtime_available": runtime_available,
            "runtime_unavailable_reason": "",
            "account_label": account_email or account_label or "Kimi Code 本机登录",
            "account_email": account_email,
            "provider_names": provider_names,
            "model_name": model_name,
            "watch_paths": sorted(set(path for path in watch_paths if path)),
            "keychain_provider": str(keychain_status.get("keychain_provider") or "").strip(),
            "keychain_targets": list(keychain_status.get("keychain_targets") or []),
            "keychain_locator": str(keychain_status.get("keychain_locator") or "").strip(),
            "message": message,
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        open_browser_url(KIMI_BROWSER_LOGIN_URL)
        return {
            "success": True,
            "completed": False,
            "message": (
                "已打开 Kimi 登录页。请先在 Kimi Code CLI 完成 `/login`，等本机凭据出现后再回来继续。"
            ),
        }

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status = self.status(settings)
        if status.get("configured") or status.get("detected"):
            return {
                "success": True,
                "completed": True,
                "message": "Kimi Code 本机登录现在已经可用了。",
            }
        return {
            "success": True,
            "completed": False,
            "message": "还没有检测到 Kimi Code 本机登录。请先完成 `/login`，再回来重试。",
        }

    def _resolve_runtime_source(self) -> Dict[str, str]:
        config_state = _read_kimi_runtime_config(self.config_path())
        api_key = normalize_text(config_state.get("api_key"))
        if api_key and not _looks_like_placeholder_secret(api_key):
            return {
                "provider_name": normalize_text(config_state.get("provider_name")),
                "api_key": api_key,
                "base_url": normalize_text(config_state.get("base_url")) or KIMI_DEFAULT_BASE_URL,
                "model": normalize_text(config_state.get("model")),
                "credential_strategy": "config_api_key",
            }
        credential_path, credential_payload, _ = self._load_best_credential()
        access_token = normalize_text(credential_payload.get("access_token"))
        if access_token and not _looks_like_placeholder_secret(access_token):
            return {
                "provider_name": normalize_text(config_state.get("provider_name")),
                "api_key": access_token,
                "base_url": normalize_text(config_state.get("base_url")) or KIMI_DEFAULT_BASE_URL,
                "model": normalize_text(config_state.get("model")),
                "credential_strategy": "oauth_credential_file",
                "auth_path": str(credential_path.resolve()) if credential_path is not None else "",
            }
        raise AuthSupportError(
            "Kimi Code 本机登录暂时还不能直接用于运行时调用。请先完成 `/login`，确保 ~/.kimi/config.toml "
            "或 OAuth 凭据缓存里已经出现可同步凭据。"
        )

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        runtime_settings = self._resolve_runtime_source()

        def _read_latest_runtime_api_key() -> str:
            return self._resolve_runtime_source()["api_key"]

        return ProviderRuntimeContext(
            api_key=_read_latest_runtime_api_key,
            base_url=normalize_text(settings.get("base_url"))
            or normalize_text(runtime_settings.get("base_url"))
            or KIMI_DEFAULT_BASE_URL,
            auth_transport="openai_compatible",
            metadata={
                "provider_name": normalize_text(runtime_settings.get("provider_name")),
                "model_hint": normalize_text(runtime_settings.get("model")),
                "credential_strategy": normalize_text(runtime_settings.get("credential_strategy")),
                "source_auth_path": normalize_text(runtime_settings.get("auth_path")),
            },
        )


class ConsumerWebSessionAuthProvider(BaseAuthProvider):
    auth_type = "web_session"
    tier = "experimental"
    runtime_supported = False
    requires_browser_flow = True
    supports_local_reuse = True
    browser_entry_url = ""
    browser_domains: tuple[str, ...] = ()
    auth_cookie_hints: tuple[str, ...] = ()
    session_env_var = ""
    private_storage_env_vars: tuple[str, ...] = ()
    private_storage_name_hints: tuple[str, ...] = ()
    private_storage_label = ""
    keychain_env_vars: tuple[str, ...] = ()
    keychain_target_hints: tuple[str, ...] = ()

    def session_export_path(self) -> Path | None:
        override = normalize_text(os.environ.get(self.session_env_var))
        if not override:
            return None
        return Path(override).expanduser().resolve()

    def _session_export_status(self) -> Dict[str, Any]:
        path = self.session_export_path()
        if path is None:
            return {}
        raw_text = _safe_read_text(path)
        if not raw_text:
            return {}
        payload = safe_read_json(path)
        account_label = ""
        account_email = ""
        if payload:
            entries = _collect_scalar_entries(payload)
            account_email = _first_entry_value(entries, "email")
            account_label = _first_entry_value(entries, "name", "nickname", "displayname", "user")
        return {
            "source_kind": "session_export",
            "session_path": str(path),
            "detected": True,
            "configured": True,
            "account_label": account_label,
            "account_email": account_email,
            "message": "已检测到可同步的导出会话文件。",
        }

    def _browser_cookie_status(self) -> Dict[str, Any]:
        best: Dict[str, Any] = {}
        for browser_name, profile_name, path in _iter_browser_cookie_dbs():
            result = _query_browser_cookie_db(
                path,
                domains=self.browser_domains,
                auth_cookie_hints=self.auth_cookie_hints,
            )
            if not result:
                continue
            candidate = {
                "source_kind": "browser_cookie_db",
                "session_path": str(path),
                "browser_name": browser_name,
                "browser_profile": profile_name,
                "detected": True,
                "configured": bool(result.get("auth_cookie_count") or int(result.get("cookie_count") or 0) >= 3),
                "cookie_count": int(result.get("cookie_count") or 0),
                "auth_cookie_count": int(result.get("auth_cookie_count") or 0),
                "account_label": f"{browser_name} {profile_name} 浏览器会话",
                "account_email": "",
                "watch_paths": [str(path)],
            }
            if not best or (
                candidate["auth_cookie_count"],
                candidate["cookie_count"],
            ) > (
                int(best.get("auth_cookie_count") or 0),
                int(best.get("cookie_count") or 0),
            ):
                best = candidate
        if not best:
            return {}
        best["message"] = (
            f"已在 {best['browser_name']} {best['browser_profile']} 中检测到 {best['cookie_count']} 个相关浏览器 Cookie。"
        )
        if best["auth_cookie_count"]:
            best["message"] += " 其中包含认证特征较强的 Cookie，通常可以直接进入跟随模式。"
        else:
            best["message"] += " 暂未确认明显的认证 Cookie 名称，因此这里只作为保守检测提示。"
        return best

    def _browser_storage_status(self) -> Dict[str, Any]:
        best: Dict[str, Any] = {}
        for browser_name, profile_name, profile_dir in _iter_browser_profiles():
            indexeddb_path = _find_browser_indexeddb_path(profile_dir, self.browser_domains)
            local_storage_path = _find_browser_local_storage_path(profile_dir, self.browser_domains)
            if indexeddb_path is None and local_storage_path is None:
                continue
            watch_paths = [
                str(path.resolve())
                for path in (indexeddb_path, local_storage_path)
                if path is not None
            ]
            candidate = {
                "source_kind": "browser_storage_probe",
                "session_path": watch_paths[0] if watch_paths else "",
                "browser_name": browser_name,
                "browser_profile": profile_name,
                "detected": True,
                "configured": False,
                "indexeddb_path": str(indexeddb_path.resolve()) if indexeddb_path is not None else "",
                "local_storage_path": str(local_storage_path.resolve()) if local_storage_path is not None else "",
                "watch_paths": watch_paths,
                "account_label": f"{browser_name} {profile_name} 浏览器存储",
                "account_email": "",
            }
            score = (
                1 if candidate["indexeddb_path"] else 0,
                1 if candidate["local_storage_path"] else 0,
            )
            best_score = (
                1 if best.get("indexeddb_path") else 0,
                1 if best.get("local_storage_path") else 0,
            )
            if not best or score > best_score:
                best = candidate
        if not best:
            return {}
        storage_parts = []
        if best.get("indexeddb_path"):
            storage_parts.append("IndexedDB")
        if best.get("local_storage_path"):
            storage_parts.append("Local Storage")
        best["message"] = (
            f"已在 {best['browser_name']} {best['browser_profile']} 中检测到这家服务方相关的 {' 和 '.join(storage_parts)}。"
            " 由于还没有确认认证 Cookie，这里先作为保守的跟随提示。"
        )
        return best

    def _iter_private_storage_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        def _append(path: Path | None) -> None:
            if path is None or not path.exists():
                return
            resolved = str(path.resolve()).lower()
            if resolved in seen:
                return
            seen.add(resolved)
            candidates.append(path)

        for env_name in self.private_storage_env_vars:
            override = normalize_text(os.environ.get(env_name))
            if not override:
                continue
            _append(Path(override).expanduser())

        for root in _iter_local_storage_roots():
            for candidate in _iter_named_storage_candidates(root, self.private_storage_name_hints):
                _append(candidate)
        return candidates

    def _private_storage_status(self) -> Dict[str, Any]:
        best: Dict[str, Any] = {}
        for candidate in self._iter_private_storage_candidates():
            resolved_candidate = candidate.resolve()
            if resolved_candidate.is_file():
                extracted = _extract_private_session_file(resolved_candidate)
                if not extracted:
                    continue
                session_path = str(resolved_candidate)
                current = {
                    "source_kind": "local_app_private_storage",
                    "private_storage_path": session_path,
                    "session_path": session_path,
                    "detected": True,
                    "configured": bool(extracted.get("configured")),
                    "account_label": str(extracted.get("account_label") or "").strip()
                    or self.private_storage_label
                    or f"{self.provider_id} 本地应用存储",
                    "account_email": str(extracted.get("account_email") or "").strip(),
                    "watch_paths": [session_path],
                    "message": "已检测到可同步的本地应用会话文件。",
                }
                if not best or _score_storage_artifacts(current) > _score_storage_artifacts(best):
                    best = current
                continue

            profile_best: Dict[str, Any] = {}
            for profile_dir in _iter_profile_like_dirs(resolved_candidate):
                artifacts = _collect_profile_storage_artifacts(
                    profile_dir,
                    domains=self.browser_domains,
                    auth_cookie_hints=self.auth_cookie_hints,
                )
                if not artifacts:
                    continue
                current = {
                    "source_kind": "local_app_private_storage",
                    "private_storage_path": str(resolved_candidate),
                    "session_path": str(artifacts.get("session_path") or resolved_candidate),
                    "detected": True,
                    "configured": bool(
                        artifacts.get("auth_cookie_count") or int(artifacts.get("cookie_count") or 0) >= 3
                    ),
                    "account_label": self.private_storage_label or f"{self.provider_id} 本地应用存储",
                    "account_email": "",
                    "cookie_count": int(artifacts.get("cookie_count") or 0),
                    "auth_cookie_count": int(artifacts.get("auth_cookie_count") or 0),
                    "cookie_path": str(artifacts.get("cookie_path") or "").strip(),
                    "indexeddb_path": str(artifacts.get("indexeddb_path") or "").strip(),
                    "local_storage_path": str(artifacts.get("local_storage_path") or "").strip(),
                    "watch_paths": list(artifacts.get("watch_paths") or []),
                }
                if not profile_best or _score_storage_artifacts(current) > _score_storage_artifacts(profile_best):
                    profile_best = current
            if not profile_best:
                file_best: Dict[str, Any] = {}
                for auth_file in _iter_candidate_auth_files(
                    resolved_candidate,
                    name_hints=self.private_storage_name_hints,
                    domains=self.browser_domains,
                ):
                    extracted = _extract_private_session_file(auth_file)
                    if not extracted:
                        continue
                    current = {
                        "source_kind": "local_app_private_storage",
                        "private_storage_path": str(resolved_candidate),
                        "session_path": str(auth_file.resolve()),
                        "detected": True,
                        "configured": bool(extracted.get("configured")),
                        "account_label": str(extracted.get("account_label") or "").strip()
                        or self.private_storage_label
                        or f"{self.provider_id} 本地应用存储",
                        "account_email": str(extracted.get("account_email") or "").strip(),
                        "watch_paths": [str(auth_file.resolve())],
                        "private_auth_file_path": str(auth_file.resolve()),
                    }
                    if not file_best or _score_storage_artifacts(current) > _score_storage_artifacts(file_best):
                        file_best = current
                if file_best:
                    file_best["message"] = "已在本地应用私有存储中检测到与这家服务方相关的会话材料。"
                    profile_best = file_best
            if not profile_best:
                continue
            storage_parts = []
            if profile_best.get("cookie_path"):
                storage_parts.append("Cookies")
            if profile_best.get("indexeddb_path"):
                storage_parts.append("IndexedDB")
            if profile_best.get("local_storage_path"):
                storage_parts.append("Local Storage")
            if storage_parts:
                profile_best["message"] = (
                    f"已在本地应用存储中检测到这家服务方相关的 {' 和 '.join(storage_parts)}。"
                )
            if not best or _score_storage_artifacts(profile_best) > _score_storage_artifacts(best):
                best = profile_best
        return best

    def _keychain_status(self) -> Dict[str, Any]:
        return _build_system_keychain_status(
            provider_id=self.provider_id,
            label=f"{self.label} 钥匙串凭据",
            env_names=self.keychain_env_vars,
            name_hints=self.keychain_target_hints,
        )

    def status(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session_export = self._session_export_status()
        browser_status = self._browser_cookie_status()
        browser_storage = self._browser_storage_status()
        private_storage = self._private_storage_status()
        keychain_status = self._keychain_status()
        selected = dict(session_export or browser_status or browser_storage or private_storage or keychain_status or {})
        if browser_storage:
            for key in ("indexeddb_path", "local_storage_path"):
                value = normalize_text(browser_storage.get(key))
                if value and not normalize_text(selected.get(key)):
                    selected[key] = value
        if private_storage:
            for key in ("private_storage_path", "indexeddb_path", "local_storage_path", "cookie_path", "private_auth_file_path"):
                value = normalize_text(private_storage.get(key))
                if value and not normalize_text(selected.get(key)):
                    selected[key] = value
        if keychain_status:
            for key in ("keychain_provider", "keychain_locator"):
                value = normalize_text(keychain_status.get(key))
                if value and not normalize_text(selected.get(key)):
                    selected[key] = value
            if keychain_status.get("keychain_targets") and not selected.get("keychain_targets"):
                selected["keychain_targets"] = list(keychain_status.get("keychain_targets") or [])
        detected = bool(selected.get("detected"))
        configured = bool(selected.get("configured"))
        watch_paths: list[str] = []
        for candidate in (session_export, browser_status, browser_storage, private_storage, keychain_status):
            if not candidate:
                continue
            for path in candidate.get("watch_paths") or []:
                normalized = normalize_text(path)
                if normalized and normalized not in watch_paths:
                    watch_paths.append(normalized)
        if not watch_paths:
            for key in ("session_path", "indexeddb_path", "local_storage_path", "private_storage_path"):
                normalized = normalize_text(selected.get(key))
                if normalized and normalized not in watch_paths:
                    watch_paths.append(normalized)
        message = normalize_text(selected.get("message")) or (
            "已检测到可同步的本机浏览器会话。"
            if detected
            else "还没有检测到可同步的本机浏览器会话。"
        )
        return {
            **self.capability(),
            "detected": detected,
            "configured": configured,
            "session_path": normalize_text(selected.get("session_path")),
            "account_label": normalize_text(selected.get("account_email"))
            or normalize_text(selected.get("account_label"))
            or "浏览器会话",
            "account_email": normalize_text(selected.get("account_email")),
            "browser_name": normalize_text(selected.get("browser_name")),
            "browser_profile": normalize_text(selected.get("browser_profile")),
            "cookie_count": int(selected.get("cookie_count") or 0),
            "auth_cookie_count": int(selected.get("auth_cookie_count") or 0),
            "cookie_path": normalize_text(selected.get("cookie_path")),
            "indexeddb_path": normalize_text(selected.get("indexeddb_path")),
            "local_storage_path": normalize_text(selected.get("local_storage_path")),
            "private_storage_path": normalize_text(selected.get("private_storage_path")),
            "private_auth_file_path": normalize_text(selected.get("private_auth_file_path")),
            "keychain_provider": normalize_text(selected.get("keychain_provider")),
            "keychain_targets": list(selected.get("keychain_targets") or []),
            "keychain_locator": normalize_text(selected.get("keychain_locator")),
            "watch_paths": watch_paths,
            "local_storage_kind": normalize_text(selected.get("source_kind")) or "browser_session",
            "message": message,
        }

    def start_browser_flow(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        open_browser_url(self.browser_entry_url)
        return {
            "success": True,
            "completed": False,
            "message": "已打开服务方登录页。请先完成登录，再回来继续扫描本机会话。",
        }

    def submit_callback(
        self,
        flow_state: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status = self.status(settings)
        if status.get("configured") or status.get("detected"):
            return {
                "success": True,
                "completed": True,
                "message": "现在已经可以跟随这份本机浏览器会话了。",
            }
        return {
            "success": True,
            "completed": False,
            "message": "暂时还没有看到可同步的本机浏览器会话。请先完成登录，再回来重试。",
        }

    def resolve_runtime(self, settings: Dict[str, Any]) -> ProviderRuntimeContext:
        raise AuthSupportError(
            f"{self.label} 的本机会话跟随目前只用于状态展示，暂不支持直接用于运行时调用。"
        )


class DoubaoWebSessionProvider(ConsumerWebSessionAuthProvider):
    id = "doubao_session"
    provider_id = "doubao"
    label = "Doubao / TRAE 浏览器会话"
    local_source_label = "browser_session"
    browser_entry_url = "https://www.doubao.com/"
    browser_domains = ("doubao.com", "trae.ai")
    session_env_var = "WECHAT_BOT_DOUBAO_SESSION_PATH"
    private_storage_env_vars = (
        "WECHAT_BOT_DOUBAO_PRIVATE_STORAGE_PATH",
        "WECHAT_BOT_TRAE_PRIVATE_STORAGE_PATH",
    )
    private_storage_name_hints = ("doubao", "trae", "bytedance", "volcengine")
    private_storage_label = "Doubao 本地应用存储"
    keychain_env_vars = ("WECHAT_BOT_DOUBAO_KEYCHAIN_TARGETS", "WECHAT_BOT_TRAE_KEYCHAIN_TARGETS")
    keychain_target_hints = ("doubao", "trae", "bytedance", "volcengine")


class TencentYuanbaoExperimentalAuthProvider(ConsumerWebSessionAuthProvider):
    id = "tencent_yuanbao"
    provider_id = "yuanbao"
    label = "腾讯元宝"
    local_source_label = "browser_session"
    browser_entry_url = "https://yuanbao.tencent.com/"
    browser_domains = ("yuanbao.tencent.com",)
    session_env_var = "WECHAT_BOT_YUANBAO_SESSION_PATH"
    private_storage_env_vars = ("WECHAT_BOT_YUANBAO_PRIVATE_STORAGE_PATH",)
    private_storage_name_hints = ("yuanbao",)
    private_storage_label = "元宝本地应用存储"
    keychain_env_vars = ("WECHAT_BOT_YUANBAO_KEYCHAIN_TARGETS",)
    keychain_target_hints = ("yuanbao",)


def build_auth_provider_registry() -> Dict[str, BaseAuthProvider]:
    return {
        "openai_codex": OpenAICodexAuthProvider(),
        "google_gemini_cli": GoogleGeminiCliAuthProvider(),
        "qwen_oauth": QwenOAuthProvider(),
        "claude_code_local": ClaudeCodeLocalAuthProvider(),
        "claude_vertex_local": ClaudeVertexLocalAuthProvider(),
        "kimi_code_local": KimiCodeLocalAuthProvider(),
        "doubao_session": DoubaoWebSessionProvider(),
        "tencent_yuanbao": TencentYuanbaoExperimentalAuthProvider(),
    }
