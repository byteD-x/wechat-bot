"""Centralized provider and model catalog for shared config consumers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from backend.shared_config import get_model_catalog_path, load_model_catalog

_MODEL_CATALOG_CACHE_SIGNATURE: tuple[int, int] | None = None
_MODEL_CATALOG_CACHE_PAYLOAD: Dict[str, Any] | None = None
_PROVIDER_CACHE_SIGNATURE: tuple[int, int] | None = None
_PROVIDER_CACHE_UPDATED_AT: Any = None
_PROVIDER_CACHE: list[Dict[str, Any]] | None = None
_PROVIDER_BY_ID_CACHE: Dict[str, Dict[str, Any]] | None = None

_PROVIDER_ID_ALIASES = {
    "claude": "anthropic",
    "bailian": "qwen",
    "dashscope": "qwen",
    "moonshot": "kimi",
}

_EXTRA_PROVIDERS: list[Dict[str, Any]] = [
    {
        "id": "qwen",
        "label": "Qwen (閫氫箟鍗冮棶)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_url": "https://dashscope.console.aliyun.com/apiKey",
        "aliases": ["qwen", "閫氫箟", "鍗冮棶", "dashscope", "bailian", "鐧剧偧"],
        "default_model": "qwen3.5-plus",
        "models": [
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen3-max-2026-01-23",
            "qwen-plus-latest",
            "qwen-turbo-latest",
            "qwen3-coder-next",
            "qwen3-coder-plus",
            "qwen3-coder-flash",
            "MiniMax-M2.5",
            "glm-5",
            "glm-4.7",
            "kimi-k2.5",
        ],
    },
    {
        "id": "anthropic",
        "label": "Anthropic / Claude",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_url": "https://platform.claude.com/settings/keys",
        "aliases": ["anthropic", "claude"],
        "default_model": "claude-sonnet-4-0",
        "models": [
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-haiku-4-5",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-sonnet-4-0",
            "claude-opus-4-1",
            "claude-opus-4-0",
            "claude-3-7-sonnet-latest",
            "claude-3-5-haiku-latest",
        ],
    },
    {
        "id": "google",
        "label": "Google / Gemini CLI",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_url": "https://aistudio.google.com/apikey",
        "aliases": ["google", "gemini", "vertex"],
        "default_model": "gemini-2.5-flash",
        "models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
    },
    {
        "id": "yuanbao",
        "label": "Tencent Yuanbao",
        "base_url": "",
        "api_key_url": "https://yuanbao.tencent.com/",
        "aliases": ["yuanbao", "腾讯元宝"],
        "default_model": "yuanbao-web",
        "models": ["yuanbao-web"],
    },
    {
        "id": "kimi",
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_url": "https://platform.moonshot.cn/console/api-keys",
        "aliases": ["moonshot", "kimi"],
        "default_model": "kimi-k2-turbo-preview",
        "models": [
            "kimi-for-coding",
            "kimi-k2-turbo-preview",
            "kimi-k2-0905-preview",
            "kimi-k2-thinking-turbo",
            "kimi-thinking-preview",
            "kimi-latest",
        ],
    },
    {
        "id": "zhipu",
        "label": "Zhipu (鏅鸿氨)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "aliases": ["zhipu", "glm", "鏅鸿氨"],
        "default_model": "glm-5",
        "models": ["glm-5", "glm-4.7", "glm-4.6", "glm-4.5-air"],
    },
    {
        "id": "minimax",
        "label": "MiniMax",
        "base_url": "https://api.minimax.io/v1",
        "api_key_url": "https://platform.minimax.io/",
        "aliases": ["minimax", "minimaxi"],
        "default_model": "MiniMax-M2.5",
        "models": [
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.1",
            "MiniMax-M2.1-highspeed",
            "MiniMax-M2",
            "MiniMax-Text-01",
        ],
    },
]

_AUTH_METHODS_BY_PROVIDER: Dict[str, list[Dict[str, Any]]] = {
    "openai": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.openai.com/v1",
                "recommended_model": "gpt-5.4-mini",
            },
        },
        {
            "id": "codex_local",
            "type": "local_import",
            "provider_id": "openai_codex",
            "tier": "stable",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.openai.com/v1",
                "recommended_model": "gpt-5.4-mini",
            },
        },
    ],
    "qwen": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "recommended_model": "qwen3.5-plus",
                "key_env_hint": "DASHSCOPE_API_KEY",
            },
        },
        {
            "id": "qwen_oauth",
            "type": "oauth",
            "provider_id": "qwen_oauth",
            "tier": "stable",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "recommended_model": "qwen3-coder-plus",
            },
        },
        {
            "id": "qwen_local",
            "type": "local_import",
            "provider_id": "qwen_oauth",
            "tier": "stable",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "recommended_model": "qwen3-coder-plus",
            },
        },
        {
            "id": "coding_plan_api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://coding.dashscope.aliyuncs.com/v1",
                "recommended_model": "qwen3-coder-next",
                "key_env_hint": "BAILIAN_CODING_PLAN_API_KEY",
                "key_prefix_hint": "sk-sp-",
                "subscription": True,
            },
        },
    ],
    "google": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "recommended_model": "gemini-2.5-flash",
            },
        },
        {
            "id": "google_oauth",
            "type": "oauth",
            "provider_id": "google_gemini_cli",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": ["oauth_project_id"],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "recommended_model": "gemini-2.5-flash",
            },
        },
        {
            "id": "gemini_cli_local",
            "type": "local_import",
            "provider_id": "google_gemini_cli",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": ["oauth_project_id"],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "recommended_model": "gemini-2.5-flash",
            },
        }
    ],
    "anthropic": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.anthropic.com/v1",
                "recommended_model": "claude-sonnet-4-0",
            },
        },
        {
            "id": "claude_code_local",
            "type": "local_import",
            "provider_id": "claude_code_local",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.anthropic.com/v1",
                "recommended_model": "claude-sonnet-4-0",
            },
        },
        {
            "id": "claude_code_oauth",
            "type": "oauth",
            "provider_id": "claude_code_local",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.anthropic.com/v1",
                "recommended_model": "claude-sonnet-4-0",
            },
        },
        {
            "id": "claude_vertex_local",
            "type": "local_import",
            "provider_id": "claude_vertex_local",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": ["oauth_project_id", "oauth_location"],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://global-aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/anthropic/models",
                "recommended_model": "claude-sonnet-4-6",
            },
        },
    ],
    "kimi": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.moonshot.cn/v1",
                "recommended_model": "kimi-k2-turbo-preview",
            },
        },
        {
            "id": "kimi_code_oauth",
            "type": "oauth",
            "provider_id": "kimi_code_local",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.kimi.com/coding/v1",
                "recommended_model": "kimi-for-coding",
            },
        },
        {
            "id": "kimi_code_local",
            "type": "local_import",
            "provider_id": "kimi_code_local",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.kimi.com/coding/v1",
                "recommended_model": "kimi-for-coding",
            },
        },
        {
            "id": "coding_plan_api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.kimi.com/coding/v1",
                "recommended_model": "kimi-for-coding",
                "key_env_hint": "KIMI_API_KEY",
            },
        },
    ],
    "zhipu": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://open.bigmodel.cn/api/paas/v4",
                "recommended_model": "glm-5",
            },
        },
        {
            "id": "coding_plan_api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                "recommended_model": "glm-5",
                "subscription": True,
            },
        },
    ],
    "minimax": [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.minimax.io/v1",
                "recommended_model": "MiniMax-M2.5",
            },
        },
        {
            "id": "coding_plan_api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
            "metadata": {
                "recommended_base_url": "https://api.minimax.io/v1",
                "recommended_model": "MiniMax-M2.5",
                "regional_base_urls": [
                    "https://api.minimax.io/v1",
                    "https://api.minimaxi.com/v1",
                    "https://api.minimax.io/anthropic",
                    "https://api.minimaxi.com/anthropic",
                ],
                "key_env_hint": "MINIMAX_API_KEY",
                "subscription": True,
            },
        },
    ],
    "yuanbao": [
        {
            "id": "yuanbao_web_session",
            "type": "web_session",
            "provider_id": "tencent_yuanbao",
            "tier": "experimental",
            "supports_local_reuse": False,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
            "runtime_supported": False,
        }
    ],
}


def _canonicalize_provider_id(provider_id: Any) -> str:
    normalized = str(provider_id or "").strip().lower()
    if not normalized:
        return ""
    return _PROVIDER_ID_ALIASES.get(normalized, normalized)


def _normalize_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(provider or {})
    canonical_id = _canonicalize_provider_id(normalized.get("id"))
    if not canonical_id:
        return normalized
    raw_id = str(normalized.get("id") or "").strip().lower()
    aliases = [str(item).strip() for item in normalized.get("aliases") or [] if str(item).strip()]
    lowered_aliases = {item.lower() for item in aliases}
    if raw_id and raw_id != canonical_id and raw_id not in lowered_aliases:
        aliases.append(raw_id)
    normalized["id"] = canonical_id
    if aliases:
        normalized["aliases"] = aliases
    return normalized


def _build_auth_methods(provider: Dict[str, Any]) -> list[Dict[str, Any]]:
    provider_id = _canonicalize_provider_id(provider.get("id"))
    if provider_id in _AUTH_METHODS_BY_PROVIDER:
        return deepcopy(_AUTH_METHODS_BY_PROVIDER[provider_id])
    return [
        {
            "id": "api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
        }
    ]


def _merge_text_list(*groups: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            value = str(item or "").strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(value)
    return merged


def _merge_auth_methods(existing: Any, fallback: Any) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    index_by_id: dict[str, int] = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        method = deepcopy(item)
        method_id = str(method.get("id") or "").strip()
        if not method_id or method_id in index_by_id:
            continue
        index_by_id[method_id] = len(merged)
        merged.append(method)
    for item in fallback or []:
        if not isinstance(item, dict):
            continue
        method = deepcopy(item)
        method_id = str(method.get("id") or "").strip()
        if not method_id:
            continue
        if method_id not in index_by_id:
            index_by_id[method_id] = len(merged)
            merged.append(method)
            continue
        current = merged[index_by_id[method_id]]
        for key, value in method.items():
            current_value = current.get(key)
            if current_value in (None, ""):
                current[key] = deepcopy(value)
                continue
            if isinstance(current_value, list) and not current_value:
                current[key] = deepcopy(value)
    return merged


def _merge_provider(provider: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(provider)
    normalized_fallback = _normalize_provider(fallback)
    merged["id"] = _canonicalize_provider_id(merged.get("id") or normalized_fallback.get("id"))
    for field in ("label", "base_url", "api_key_url", "default_model"):
        if not str(merged.get(field) or "").strip() and str(normalized_fallback.get(field) or "").strip():
            merged[field] = normalized_fallback[field]
    if "allow_empty_key" not in merged and "allow_empty_key" in normalized_fallback:
        merged["allow_empty_key"] = bool(normalized_fallback.get("allow_empty_key"))
    aliases = _merge_text_list(merged.get("aliases"), normalized_fallback.get("aliases"))
    if aliases:
        merged["aliases"] = aliases
    models = _merge_text_list(merged.get("models"), normalized_fallback.get("models"))
    if models:
        merged["models"] = models
    fallback_auth_methods = normalized_fallback.get("auth_methods") or _build_auth_methods(normalized_fallback)
    merged["auth_methods"] = _merge_auth_methods(merged.get("auth_methods"), fallback_auth_methods)
    return merged


def get_model_catalog_signature() -> tuple[int, int] | None:
    try:
        stat = get_model_catalog_path().stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _catalog_payload() -> Dict[str, Any]:
    global _MODEL_CATALOG_CACHE_SIGNATURE, _MODEL_CATALOG_CACHE_PAYLOAD

    signature = get_model_catalog_signature()
    if _MODEL_CATALOG_CACHE_PAYLOAD is None or signature != _MODEL_CATALOG_CACHE_SIGNATURE:
        _MODEL_CATALOG_CACHE_PAYLOAD = load_model_catalog()
        _MODEL_CATALOG_CACHE_SIGNATURE = signature
    return _MODEL_CATALOG_CACHE_PAYLOAD or {}


def _build_provider_cache() -> tuple[list[Dict[str, Any]], Dict[str, Dict[str, Any]], Any]:
    payload = _catalog_payload()
    providers = [_normalize_provider(item) for item in payload.get("providers") or [] if isinstance(item, dict)]
    index_by_id = {
        _canonicalize_provider_id(item.get("id")): index
        for index, item in enumerate(providers)
        if _canonicalize_provider_id(item.get("id"))
    }
    for extra in _EXTRA_PROVIDERS:
        extra_id = _canonicalize_provider_id(extra.get("id"))
        normalized_extra = _normalize_provider(extra)
        if extra_id in index_by_id:
            providers[index_by_id[extra_id]] = _merge_provider(providers[index_by_id[extra_id]], normalized_extra)
            continue
        providers.append(_merge_provider(normalized_extra, normalized_extra))
        index_by_id[extra_id] = len(providers) - 1
    for index, provider in enumerate(providers):
        providers[index] = _merge_provider(provider, provider)
    providers_by_id = {
        _canonicalize_provider_id(provider.get("id")): provider
        for provider in providers
        if _canonicalize_provider_id(provider.get("id"))
    }
    return providers, providers_by_id, payload.get("updated_at")


def _providers() -> list[Dict[str, Any]]:
    global _PROVIDER_CACHE_SIGNATURE, _PROVIDER_CACHE_UPDATED_AT, _PROVIDER_CACHE, _PROVIDER_BY_ID_CACHE

    signature = get_model_catalog_signature()
    if _PROVIDER_CACHE is None or signature != _PROVIDER_CACHE_SIGNATURE:
        providers, providers_by_id, updated_at = _build_provider_cache()
        _PROVIDER_CACHE = providers
        _PROVIDER_BY_ID_CACHE = providers_by_id
        _PROVIDER_CACHE_UPDATED_AT = updated_at
        _PROVIDER_CACHE_SIGNATURE = signature
    return _PROVIDER_CACHE or []


def _providers_by_id() -> Dict[str, Dict[str, Any]]:
    _providers()
    return _PROVIDER_BY_ID_CACHE or {}


def _catalog_updated_at() -> Any:
    _providers()
    return _PROVIDER_CACHE_UPDATED_AT


def get_model_catalog() -> Dict[str, Any]:
    return {
        "updated_at": _catalog_updated_at(),
        "providers": deepcopy(_providers()),
    }


def get_provider_by_id(provider_id: Optional[str]) -> Optional[Dict[str, Any]]:
    wanted = _canonicalize_provider_id(provider_id)
    if not wanted:
        return None
    provider = _providers_by_id().get(wanted)
    if provider is None:
        return None
    return deepcopy(provider)


def infer_provider_id(
    *,
    provider_id: Optional[str] = None,
    preset_name: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    if provider_id:
        provider = get_provider_by_id(provider_id)
        if provider:
            return str(provider.get("id") or "")

    lower_name = str(preset_name or "").strip().lower()
    lower_base_url = str(base_url or "").strip().lower()
    lower_model = str(model or "").strip().lower()

    for provider in _providers():
        provider_id_value = _canonicalize_provider_id(provider.get("id"))
        provider_base_url = str(provider.get("base_url") or "").strip().lower()
        if lower_base_url and provider_base_url and lower_base_url.startswith(provider_base_url):
            return provider_id_value
        if provider_id_value == "qwen" and lower_base_url:
            if "dashscope.aliyuncs.com" in lower_base_url:
                return provider_id_value
        if provider_id_value == "anthropic" and lower_base_url:
            if "aiplatform.googleapis.com" in lower_base_url and (
                "/publishers/anthropic/" in lower_base_url or "claude" in lower_model or "claude" in lower_name
            ):
                return provider_id_value
        if provider_id_value == "google" and lower_base_url:
            if lower_base_url.startswith("https://aiplatform.googleapis.com/") or "aiplatform.googleapis.com" in lower_base_url:
                return provider_id_value
        if provider_id_value == "zhipu" and lower_base_url:
            if lower_base_url.startswith("https://open.bigmodel.cn/") or "open.bigmodel.cn" in lower_base_url:
                return provider_id_value
        if provider_id_value == "minimax" and lower_base_url:
            if (
                lower_base_url.startswith("https://api.minimax.io/")
                or "api.minimax.io" in lower_base_url
                or lower_base_url.startswith("https://api.minimaxi.com/")
                or "api.minimaxi.com" in lower_base_url
            ):
                return provider_id_value

    for provider in _providers():
        provider_id_value = _canonicalize_provider_id(provider.get("id"))

        aliases = [str(alias).strip().lower() for alias in provider.get("aliases") or [] if alias]
        if lower_name and any(alias in lower_name for alias in aliases):
            return provider_id_value
        if lower_model and any(alias in lower_model for alias in aliases):
            return provider_id_value

        models = {str(item).strip().lower() for item in provider.get("models") or [] if item}
        if lower_model and lower_model in models:
            return provider_id_value

    return None


def merge_provider_defaults(preset: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(preset or {})
    provider_id = infer_provider_id(
        provider_id=merged.get("provider_id"),
        preset_name=merged.get("name"),
        base_url=merged.get("base_url"),
        model=merged.get("model"),
    )
    if not provider_id:
        return merged

    provider = get_provider_by_id(provider_id)
    if not provider:
        return merged

    merged["provider_id"] = provider_id
    merged.setdefault("base_url", provider.get("base_url"))
    merged.setdefault("allow_empty_key", bool(provider.get("allow_empty_key", False)))
    merged.setdefault("model", provider.get("default_model"))
    merged.setdefault("auth_methods", deepcopy(provider.get("auth_methods") or _build_auth_methods(provider)))
    return merged
