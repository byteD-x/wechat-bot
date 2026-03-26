from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend.core.ai_client import AIClient
from backend.core.oauth_support import OAuthSupportError, resolve_oauth_settings

from ..domain.enums import AuthMethodType
from ..domain.models import HealthCheckResult
from ..providers.registry import get_method_auth_provider_id, get_provider_method
from ..storage.credential_store import CredentialStore, get_credential_store
from .migration import _resolve_method_runtime_defaults, hydrate_runtime_settings


def _now() -> int:
    return int(time.time())


def _map_health_error(message: str) -> str:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return "unknown_error"
    if "cryptunprotectdata" in lowered or "decrypt" in lowered or "凭据" in str(message or ""):
        return "credential_unreadable"
    if "refresh_token" in lowered or "expired" in lowered:
        return "expired"
    if "api key" in lowered or "unauthorized" in lowered or "401" in lowered or "403" in lowered:
        return "api_key_invalid"
    if "session" in lowered or "cookie" in lowered:
        return "session_unavailable"
    if "authorization" in lowered or "oauth" in lowered:
        return "browser_auth_failed"
    if "not found" in lowered or "missing" in lowered:
        return "not_detected"
    if "network" in lowered or "timed out" in lowered or "timeout" in lowered:
        return "network_error"
    return "connection_failed"


def _build_base_settings(entry: Dict[str, Any], profile: Dict[str, Any], method) -> Dict[str, Any]:
    metadata = dict(entry.get("metadata") or {})
    profile_meta = dict(profile.get("metadata") or {})
    runtime_defaults = _resolve_method_runtime_defaults(entry, method, profile_meta)
    return {
        "provider_id": str(entry.get("provider_id") or "").strip().lower(),
        "base_url": runtime_defaults["base_url"],
        "model": runtime_defaults["model"],
        "alias": str(entry.get("alias") or "").strip(),
        "timeout_sec": metadata.get("timeout_sec", 8),
        "max_retries": 0,
        "temperature": metadata.get("temperature", 0.6),
        "max_tokens": metadata.get("max_tokens", 256),
        "max_completion_tokens": metadata.get("max_completion_tokens"),
        "reasoning_effort": metadata.get("reasoning_effort"),
        "embedding_model": metadata.get("embedding_model"),
        "oauth_project_id": metadata.get("oauth_project_id"),
        "oauth_location": metadata.get("oauth_location"),
        "auth_mode": "api_key",
        "credential_ref": str(profile.get("credential_ref") or "").strip(),
    }


def _build_profile_secret_issue(
    method,
    profile: Dict[str, Any],
    store: CredentialStore,
) -> Optional[HealthCheckResult]:
    ref = str(profile.get("credential_ref") or "").strip()
    if not ref:
        return None
    lookup = store.lookup(ref)
    if lookup.readable:
        return None
    checked_at = _now()
    binding = dict(profile.get("binding") or {})
    sync_policy = str(binding.get("sync_policy") or "").strip().lower()
    if lookup.exists:
        if method.type is AuthMethodType.API_KEY:
            return HealthCheckResult(
                ok=False,
                state="invalid",
                checked_at=checked_at,
                message="已保存的 API Key 无法读取，请重新填写。",
                error_code="credential_unreadable",
                can_retry=False,
            )
        if method.type is AuthMethodType.WEB_SESSION:
            return HealthCheckResult(
                ok=False,
                state="invalid",
                checked_at=checked_at,
                message="已导入的会话无法读取，请重新导入或重新连接。",
                error_code="credential_unreadable",
                can_retry=False,
            )
        if sync_policy == "import_copy":
            return HealthCheckResult(
                ok=False,
                state="invalid",
                checked_at=checked_at,
                message="已导入的认证副本无法读取，请重新导入或切回同步模式。",
                error_code="credential_unreadable",
                can_retry=False,
            )
        return HealthCheckResult(
            ok=False,
            state="invalid",
            checked_at=checked_at,
            message="已保存的认证凭据无法读取，请重新连接或重新配置。",
            error_code="credential_unreadable",
            can_retry=False,
        )
    if method.type is AuthMethodType.API_KEY:
        return HealthCheckResult(
            ok=False,
            state="invalid",
            checked_at=checked_at,
            message="还没有可用的 API Key，请先完成配置。",
            error_code="api_key_missing",
            can_retry=False,
        )
    if method.type is AuthMethodType.WEB_SESSION:
        return HealthCheckResult(
            ok=False,
            state="invalid",
            checked_at=checked_at,
            message="还没有可用的会话，请重新导入或重新连接。",
            error_code="session_unavailable",
            can_retry=False,
        )
    return None


async def run_profile_health_check(
    entry: Dict[str, Any],
    profile: Dict[str, Any],
    *,
    credential_store: Optional[CredentialStore] = None,
) -> HealthCheckResult:
    store = credential_store or get_credential_store()
    provider_id = str(entry.get("provider_id") or "").strip().lower()
    method = get_provider_method(provider_id, profile.get("method_id"))
    if method is None:
        return HealthCheckResult(
            ok=False,
            state="invalid",
            checked_at=_now(),
            message="未识别的认证方式。",
            error_code="unknown_method",
            can_retry=False,
        )
    if not method.runtime_supported:
        return HealthCheckResult(
            ok=False,
            state="unsupported",
            checked_at=_now(),
            message="这种认证方式暂时还不能直接用于运行时调用。",
            error_code="runtime_unsupported",
            can_retry=False,
        )

    settings = _build_base_settings(entry, profile, method)
    try:
        if method.type is AuthMethodType.API_KEY:
            secret_issue = _build_profile_secret_issue(method, profile, store)
            if secret_issue is not None:
                return secret_issue
            settings = hydrate_runtime_settings(settings, credential_store=store)
        else:
            secret_issue = _build_profile_secret_issue(method, profile, store)
            if secret_issue is not None:
                return secret_issue
            adapter_id = get_method_auth_provider_id(method)
            settings["auth_mode"] = "oauth"
            settings["oauth_provider"] = adapter_id
            settings["oauth_source"] = str((profile.get("binding") or {}).get("source") or method.id).strip()
            settings["oauth_binding"] = dict(profile.get("binding") or {})
            settings["oauth_experimental_ack"] = True
            settings = resolve_oauth_settings(settings).settings

        client = AIClient(
            base_url=str(settings.get("base_url") or "").strip(),
            api_key=settings.get("api_key"),
            extra_headers=settings.get("extra_headers"),
            auth_refresh_hook=settings.get("auth_refresh_hook"),
            auth_transport=str(settings.get("auth_transport") or "").strip() or None,
            transport_metadata=settings.get("resolved_auth_metadata"),
            model=str(settings.get("model") or "").strip(),
            timeout_sec=float(settings.get("timeout_sec") or 8.0),
            max_retries=0,
            context_rounds=1,
            history_max_chats=1,
            history_ttl_sec=1,
            max_tokens=int(settings.get("max_tokens") or 128),
            max_completion_tokens=settings.get("max_completion_tokens"),
            reasoning_effort=settings.get("reasoning_effort"),
            embedding_model=settings.get("embedding_model"),
            model_alias=settings.get("alias"),
        )
        try:
            ok, mode = await client.probe_fast()
        finally:
            await client.close()
        if ok:
            return HealthCheckResult(
                ok=True,
                state="healthy",
                checked_at=_now(),
                message=(
                    "连接测试成功，当前认证可以直接用于对话。"
                    if mode in {"completion", "messages", "responses", "code_assist"}
                    else "连接测试成功，服务可访问。"
                ),
                error_code="",
                can_retry=True,
            )
        return HealthCheckResult(
            ok=False,
            state="invalid",
            checked_at=_now(),
            message="连接测试失败，请检查认证状态或网络访问。",
            error_code="connection_failed",
            can_retry=True,
        )
    except Exception as exc:
        message = str(exc or "").strip()
        return HealthCheckResult(
            ok=False,
            state="error",
            checked_at=_now(),
            message=message or "连接测试失败。",
            error_code=_map_health_error(message),
            can_retry=True,
        )
