"""Centralized provider and model catalog for shared config consumers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from backend.shared_config import load_model_catalog

_EXTRA_PROVIDERS: list[Dict[str, Any]] = [
    {
        "id": "google",
        "label": "Google / Gemini CLI",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_url": "https://aistudio.google.com/apikey",
        "aliases": ["google", "gemini", "vertex"],
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
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
        },
        {
            "id": "coding_plan_api_key",
            "type": "api_key",
            "tier": "stable",
            "supports_local_reuse": False,
            "requires_browser_flow": False,
            "requires_fields": [],
            "requires_extra_fields": [],
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
        },
        {
            "id": "google_oauth",
            "type": "oauth",
            "provider_id": "google_gemini_cli",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
        },
        {
            "id": "gemini_cli_local",
            "type": "local_import",
            "provider_id": "google_gemini_cli",
            "tier": "experimental",
            "supports_local_reuse": True,
            "requires_browser_flow": True,
            "requires_fields": [],
            "requires_extra_fields": [],
        }
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


def _build_auth_methods(provider: Dict[str, Any]) -> list[Dict[str, Any]]:
    provider_id = str(provider.get("id") or "").strip().lower()
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


def _providers() -> list[Dict[str, Any]]:
    payload = load_model_catalog()
    providers = [dict(item) for item in payload.get("providers") or [] if isinstance(item, dict)]
    existing_ids = {str(item.get("id") or "").strip().lower() for item in providers}
    for extra in _EXTRA_PROVIDERS:
        extra_id = str(extra.get("id") or "").strip().lower()
        if extra_id not in existing_ids:
            providers.append(dict(extra))
    for provider in providers:
        provider.setdefault("auth_methods", _build_auth_methods(provider))
    return providers


def get_model_catalog() -> Dict[str, Any]:
    payload = load_model_catalog()
    return {
        "updated_at": payload.get("updated_at"),
        "providers": deepcopy(_providers()),
    }


def get_provider_by_id(provider_id: Optional[str]) -> Optional[Dict[str, Any]]:
    wanted = str(provider_id or "").strip().lower()
    if not wanted:
        return None
    for provider in _providers():
        if str(provider.get("id") or "").strip().lower() == wanted:
            return provider
    return None


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
        provider_id_value = str(provider.get("id") or "").strip().lower()
        provider_base_url = str(provider.get("base_url") or "").strip().lower()
        if lower_base_url and provider_base_url and lower_base_url.startswith(provider_base_url):
            return provider_id_value
        if provider_id_value == "google" and lower_base_url:
            if lower_base_url.startswith("https://aiplatform.googleapis.com/") or "aiplatform.googleapis.com" in lower_base_url:
                return provider_id_value

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
