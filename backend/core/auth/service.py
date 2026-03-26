from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .common import generate_flow_id, normalize_text
from .providers import BaseAuthProvider, ProviderRuntimeContext, build_auth_provider_registry
from .types import AuthSupportError, ResolvedAuthSettings

_AUTH_PROVIDERS: Dict[str, BaseAuthProvider] = build_auth_provider_registry()
_DEFAULT_AUTH_PROVIDER_BY_SERVICE = {
    "openai": "openai_codex",
    "qwen": "qwen_oauth",
    "google": "google_gemini_cli",
    "doubao": "doubao_session",
    "yuanbao": "tencent_yuanbao",
    "anthropic": "claude_code_local",
    "kimi": "kimi_code_local",
}
_SERVICE_ALIASES: Dict[str, tuple[str, ...]] = {
    "openai": ("openai", "gpt", "codex"),
    "qwen": ("qwen", "dashscope"),
    "google": ("google", "gemini", "vertex"),
    "doubao": ("doubao", "ark", "trae"),
    "anthropic": ("anthropic", "claude"),
    "kimi": ("kimi", "moonshot"),
    "yuanbao": ("yuanbao", "腾讯元宝"),
}


def normalize_auth_mode(value: Any) -> str:
    mode = normalize_text(value).lower()
    return "oauth" if mode == "oauth" else "api_key"


def get_supported_auth_provider_ids() -> list[str]:
    return sorted(_AUTH_PROVIDERS.keys())


def get_auth_provider(provider_key: str) -> Optional[BaseAuthProvider]:
    return _AUTH_PROVIDERS.get(normalize_text(provider_key))


def _infer_service_provider_id(payload: Dict[str, Any]) -> str:
    explicit = normalize_text(payload.get("provider_id")).lower()
    if explicit:
        return explicit

    lower_name = normalize_text(payload.get("name")).lower()
    lower_base_url = normalize_text(payload.get("base_url")).lower()
    lower_model = normalize_text(payload.get("model")).lower()
    haystacks = [lower_name, lower_base_url, lower_model]
    for provider_id, aliases in _SERVICE_ALIASES.items():
        if any(alias in value for alias in aliases for value in haystacks if value):
            return provider_id
    return ""


def infer_auth_provider_id(settings: Optional[Dict[str, Any]]) -> str:
    payload = settings if isinstance(settings, dict) else {}
    explicit = normalize_text(payload.get("oauth_provider"))
    if explicit in _AUTH_PROVIDERS:
        return explicit
    provider_id = _infer_service_provider_id(payload)
    return _DEFAULT_AUTH_PROVIDER_BY_SERVICE.get(provider_id, "")


@dataclass(slots=True)
class PendingAuthFlow:
    flow_id: str
    provider_id: str
    created_at: float
    settings: Dict[str, Any]
    state: Dict[str, Any]


class AuthFlowRunner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._flows: Dict[str, PendingAuthFlow] = {}

    def start(self, provider: BaseAuthProvider, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = provider.start_browser_flow(settings)
        flow_state = dict(payload.pop("flow_state", {}) or {})
        flow_id = generate_flow_id(provider.id)
        record = PendingAuthFlow(
            flow_id=flow_id,
            provider_id=provider.id,
            created_at=time.time(),
            settings=dict(settings or {}),
            state=flow_state,
        )
        with self._lock:
            self._flows[flow_id] = record
        payload["flow_id"] = flow_id
        payload["provider_id"] = provider.id
        payload["created_at"] = int(record.created_at)
        return payload

    def cancel(self, provider: BaseAuthProvider, flow_id: str) -> Dict[str, Any]:
        flow = self._pop(flow_id)
        if flow is None:
            return {"success": True, "message": "Authorization flow already expired."}
        payload = provider.cancel_flow(flow.state, settings=flow.settings)
        payload["flow_id"] = flow.flow_id
        payload["provider_id"] = provider.id
        return payload

    def submit(
        self,
        provider: BaseAuthProvider,
        flow_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        flow = self._get(flow_id)
        if flow is None:
            raise AuthSupportError("Authorization flow expired or does not exist.")
        result = provider.submit_callback(flow.state, payload=payload, settings=flow.settings)
        next_state = dict(result.pop("flow_state", {}) or {})
        completed = bool(result.get("completed"))
        with self._lock:
            current = self._flows.get(flow_id)
            if current is None:
                pass
            elif completed:
                self._flows.pop(flow_id, None)
            else:
                current.state = next_state or current.state
        result["flow_id"] = flow_id
        result["provider_id"] = provider.id
        return result

    def _get(self, flow_id: str) -> Optional[PendingAuthFlow]:
        wanted = normalize_text(flow_id)
        with self._lock:
            return self._flows.get(wanted)

    def _pop(self, flow_id: str) -> Optional[PendingAuthFlow]:
        wanted = normalize_text(flow_id)
        with self._lock:
            return self._flows.pop(wanted, None)


_FLOW_RUNNER = AuthFlowRunner()


def _is_import_copy_binding(payload: Dict[str, Any]) -> bool:
    binding = payload.get("oauth_binding") if isinstance(payload.get("oauth_binding"), dict) else {}
    return normalize_text(binding.get("sync_policy")).lower() == "import_copy"


def _load_runtime_snapshot(ref: Any) -> Dict[str, Any]:
    wanted = normalize_text(ref)
    if not wanted:
        return {}
    from backend.model_auth.storage.credential_store import get_credential_store

    record = get_credential_store().get(wanted)
    payload = dict(record.payload or {}) if record else {}
    if normalize_text(payload.get("kind")) != "runtime_context_snapshot":
        return {}
    return payload


def _merge_runtime_snapshot(normalized: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    resolved = dict(normalized)
    api_key = snapshot.get("api_key")
    if api_key not in (None, ""):
        resolved["api_key"] = api_key
    base_url = normalize_text(snapshot.get("base_url"))
    if base_url:
        resolved["base_url"] = base_url
    extra_headers = snapshot.get("extra_headers")
    if isinstance(extra_headers, dict) and extra_headers:
        resolved["extra_headers"] = dict(extra_headers)
    auth_transport = normalize_text(snapshot.get("auth_transport"))
    if auth_transport:
        resolved["auth_transport"] = auth_transport
    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict) and metadata:
        resolved["resolved_auth_metadata"] = dict(metadata)
    resolved["imported_runtime_snapshot"] = True
    return resolved


def get_auth_provider_statuses() -> Dict[str, Any]:
    providers: Dict[str, Any] = {}
    for provider_id, provider in _AUTH_PROVIDERS.items():
        try:
            providers[provider_id] = provider.status()
        except Exception as exc:
            providers[provider_id] = {
                **provider.capability(),
                "configured": False,
                "detected": False,
                "message": f"Failed to read local authorization source: {exc}",
                "error": str(exc),
            }
    return {
        "success": True,
        "providers": providers,
        "supported_provider_ids": get_supported_auth_provider_ids(),
        "refreshed_at": int(time.time()),
    }


def _list_missing_required_fields(
    provider: Optional[BaseAuthProvider],
    settings: Dict[str, Any],
) -> list[str]:
    if provider is None:
        return []
    missing: list[str] = []
    for field_name in provider.requires_extra_fields:
        if not normalize_text(settings.get(field_name)):
            missing.append(field_name)
    return missing


def get_preset_auth_summary(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = dict(settings or {})
    auth_mode = normalize_auth_mode(payload.get("auth_mode"))
    provider_id = infer_auth_provider_id(payload)
    provider = get_auth_provider(provider_id)
    provider_status = provider.status(payload) if provider else None
    oauth_source = normalize_text(payload.get("oauth_source"))
    oauth_binding = payload.get("oauth_binding") if isinstance(payload.get("oauth_binding"), dict) else {}
    imported_runtime_snapshot = _load_runtime_snapshot(payload.get("credential_ref")) if _is_import_copy_binding(payload) else {}
    imported_copy_ready = bool(imported_runtime_snapshot)
    oauth_bound = bool(oauth_source or oauth_binding or imported_copy_ready)
    allow_empty_key = bool(payload.get("allow_empty_key", False))
    api_key = normalize_text(payload.get("api_key"))
    api_key_configured = bool(api_key and not api_key.startswith("YOUR_"))
    api_key_ready = bool(allow_empty_key or api_key_configured)
    oauth_missing_fields = _list_missing_required_fields(provider, payload)
    oauth_detected_local = bool(provider_status and provider_status.get("detected"))
    oauth_ready = bool(
        imported_copy_ready
        or (
            provider_status
            and provider_status.get("configured")
            and oauth_bound
            and not oauth_missing_fields
        )
    )
    oauth_experimental_ack = bool(payload.get("oauth_experimental_ack"))
    oauth_requires_ack = bool(provider and provider.tier != "stable")
    if oauth_requires_ack and not oauth_experimental_ack:
        oauth_ready = False if auth_mode == "oauth" else oauth_ready
    auth_ready = oauth_ready if auth_mode == "oauth" else api_key_ready
    is_active = bool(payload.get("_is_active"))

    if is_active:
        card_state = "active"
        card_rank = 0
    elif auth_ready:
        card_state = "oauth_ready" if auth_mode == "oauth" else "api_key_ready"
        card_rank = 1
    elif oauth_detected_local:
        card_state = "detected_local"
        card_rank = 2
    elif provider and provider.tier != "stable":
        card_state = "experimental"
        card_rank = 4
    elif auth_mode == "oauth":
        card_state = "waiting_auth"
        card_rank = 3
    else:
        card_state = "unconfigured"
        card_rank = 5

    if card_rank <= 2:
        card_group = "featured"
    else:
        card_group = "secondary"

    if auth_mode == "oauth":
        if oauth_ready:
            auth_status_summary = "已就绪，可直接使用导入的认证副本" if imported_copy_ready else "OAuth 已就绪"
        elif oauth_missing_fields:
            auth_status_summary = f"缺少字段：{', '.join(oauth_missing_fields)}"
        elif oauth_requires_ack and not oauth_experimental_ack:
            auth_status_summary = "等待确认实验性能力提示"
        elif oauth_detected_local and not oauth_bound:
            auth_status_summary = "已检测到本机授权，但尚未完成绑定"
        elif oauth_detected_local:
            auth_status_summary = "已检测到本机授权来源"
        else:
            auth_status_summary = "需要先完成 OAuth 授权"
    else:
        auth_status_summary = "API Key 已就绪" if api_key_ready else "需要填写 API Key"

    return {
        "auth_mode": auth_mode,
        "oauth_provider": provider_id,
        "oauth_supported": provider is not None or imported_copy_ready,
        "oauth_source": oauth_source,
        "oauth_bound": oauth_bound,
        "oauth_status": provider_status,
        "oauth_missing_fields": oauth_missing_fields,
        "oauth_detected_local": oauth_detected_local,
        "imported_copy_ready": imported_copy_ready,
        "oauth_experimental": bool(provider and provider.tier != "stable"),
        "oauth_requires_ack": oauth_requires_ack,
        "oauth_experimental_ack": oauth_experimental_ack,
        "api_key_ready": api_key_ready,
        "oauth_ready": oauth_ready,
        "auth_ready": auth_ready,
        "auth_status_summary": auth_status_summary,
        "card_state": card_state,
        "card_rank": card_rank,
        "card_group": card_group,
    }


def _merge_runtime_context(
    normalized: Dict[str, Any],
    provider: BaseAuthProvider,
    context: ProviderRuntimeContext,
) -> Dict[str, Any]:
    resolved = dict(normalized)
    resolved["oauth_provider"] = provider.id
    resolved["api_key"] = context.api_key
    resolved["auth_transport"] = context.auth_transport
    if context.base_url:
        resolved["base_url"] = context.base_url
    if context.extra_headers:
        resolved["extra_headers"] = context.extra_headers
    if context.refresh_auth:
        resolved["auth_refresh_hook"] = context.refresh_auth
    if context.metadata:
        resolved["resolved_auth_metadata"] = dict(context.metadata)
    return resolved


def resolve_auth_settings(settings: Dict[str, Any]) -> ResolvedAuthSettings:
    normalized = dict(settings or {})
    normalized["auth_mode"] = normalize_auth_mode(normalized.get("auth_mode"))
    summary = get_preset_auth_summary(normalized)
    if normalized["auth_mode"] != "oauth":
        return ResolvedAuthSettings(settings=normalized, summary=summary)

    if summary.get("imported_copy_ready"):
        snapshot = _load_runtime_snapshot(normalized.get("credential_ref"))
        if not snapshot:
            raise AuthSupportError("Imported auth copy is missing a reusable runtime snapshot.")
        return ResolvedAuthSettings(
            settings=_merge_runtime_snapshot(normalized, snapshot),
            summary=summary,
        )

    provider_id = summary.get("oauth_provider") or ""
    provider = get_auth_provider(str(provider_id))
    if provider is None:
        raise AuthSupportError("This preset does not have a supported OAuth provider.")
    if summary.get("oauth_requires_ack") and not summary.get("oauth_experimental_ack"):
        raise AuthSupportError("This OAuth provider is experimental. Please acknowledge the risk before enabling it.")
    if not summary.get("oauth_bound"):
        raise AuthSupportError("This preset has not been bound to an OAuth authorization source yet.")
    missing_fields = list(summary.get("oauth_missing_fields") or [])
    if missing_fields:
        raise AuthSupportError(f"Missing required OAuth fields: {', '.join(missing_fields)}")
    context = provider.resolve_runtime(normalized)
    return ResolvedAuthSettings(
        settings=_merge_runtime_context(normalized, provider, context),
        summary=summary,
    )


def launch_auth_flow(provider_key: str, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    provider = get_auth_provider(provider_key)
    if provider is None:
        raise AuthSupportError("Unsupported OAuth provider.")
    return _FLOW_RUNNER.start(provider, settings=settings)


def cancel_auth_flow(provider_key: str, flow_id: str) -> Dict[str, Any]:
    provider = get_auth_provider(provider_key)
    if provider is None:
        raise AuthSupportError("Unsupported OAuth provider.")
    return _FLOW_RUNNER.cancel(provider, flow_id)


def submit_auth_callback(
    provider_key: str,
    flow_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    provider = get_auth_provider(provider_key)
    if provider is None:
        raise AuthSupportError("Unsupported OAuth provider.")
    return _FLOW_RUNNER.submit(provider, flow_id, payload=payload)


def logout_auth_provider(provider_key: str, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    provider = get_auth_provider(provider_key)
    if provider is None:
        raise AuthSupportError("Unsupported OAuth provider.")
    return provider.logout_source(settings=settings)
