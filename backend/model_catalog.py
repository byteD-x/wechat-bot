"""Centralized provider and model catalog for shared config consumers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from backend.shared_config import load_model_catalog


def _providers() -> list[Dict[str, Any]]:
    payload = load_model_catalog()
    providers = payload.get("providers") or []
    return [dict(item) for item in providers if isinstance(item, dict)]


def get_model_catalog() -> Dict[str, Any]:
    payload = load_model_catalog()
    return {
        "updated_at": payload.get("updated_at"),
        "providers": deepcopy(payload.get("providers") or []),
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
    return merged
