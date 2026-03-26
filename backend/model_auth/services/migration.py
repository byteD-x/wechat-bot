from __future__ import annotations

import re
import time
from copy import deepcopy
from typing import Any, Dict, Iterable, Optional

from backend.model_catalog import infer_provider_id, merge_provider_defaults
from backend.utils.config import is_placeholder_key

from ..domain.enums import AuthMethodType, CredentialSource, SyncPolicy
from ..providers.registry import (
    get_method_auth_provider_id,
    get_provider_definition,
    get_provider_method,
    list_provider_definitions,
)
from ..storage.credential_store import CredentialStore, get_credential_store

CENTER_VERSION = 1
_PROFILE_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: Any, *, fallback: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = _PROFILE_SLUG_RE.sub("-", lowered).strip("-")
    return lowered or fallback


def _now() -> int:
    return int(time.time())


def _default_provider_entry(provider_id: str) -> Dict[str, Any]:
    definition = get_provider_definition(provider_id)
    label = definition.label if definition else provider_id
    return {
        "provider_id": provider_id,
        "legacy_preset_name": label,
        "alias": "",
        "default_model": definition.default_model if definition else "",
        "default_base_url": definition.default_base_url if definition else "",
        "selected_profile_id": "",
        "auth_profiles": [],
        "metadata": {
            "project_to_runtime": False,
            "created_at": _now(),
            "selection_mode": "auto",
        },
    }


def _normalize_selection_mode(value: Any) -> str:
    return "manual" if str(value or "").strip().lower() == "manual" else "auto"


def _profile_method_priority(method: Any) -> int:
    if method is None:
        return 99
    if not bool(getattr(method, "runtime_supported", False)):
        return 80
    if method.type in {AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH}:
        return 0
    if method.type is AuthMethodType.API_KEY:
        return 10
    if method.type is AuthMethodType.WEB_SESSION:
        return 20
    return 50


def _profile_runtime_priority(profile: Dict[str, Any]) -> int:
    metadata = dict(profile.get("metadata") or {})
    if metadata.get("runtime_ready") is False or metadata.get("runtime_available") is False:
        return 1
    return 0


def _profile_sort_key(
    entry: Dict[str, Any],
    profile: Dict[str, Any],
    *,
    selected_id: str,
    prefer_selected: bool,
) -> tuple[Any, ...]:
    profile_id = str(profile.get("id") or "").strip()
    method = get_provider_method(str(entry.get("provider_id") or "").strip().lower(), profile.get("method_id"))
    return (
        0 if prefer_selected and profile_id == selected_id else 1,
        _profile_runtime_priority(profile),
        _profile_method_priority(method),
        str(profile.get("label") or ""),
        profile_id,
    )


def _pick_preferred_profile(entry: Dict[str, Any], *, prefer_selected: bool) -> Optional[Dict[str, Any]]:
    profiles = [item for item in entry.get("auth_profiles") or [] if isinstance(item, dict)]
    if not profiles:
        return None
    selected_id = str(entry.get("selected_profile_id") or "").strip()
    ordered = sorted(
        profiles,
        key=lambda item: _profile_sort_key(
            entry,
            item,
            selected_id=selected_id,
            prefer_selected=prefer_selected,
        ),
    )
    return dict(ordered[0]) if ordered else None


def _reconcile_selected_profile(entry: Dict[str, Any]) -> None:
    entry.setdefault("metadata", {})
    entry["metadata"]["selection_mode"] = _normalize_selection_mode(entry["metadata"].get("selection_mode"))
    selected_id = str(entry.get("selected_profile_id") or "").strip()
    profiles = [item for item in entry.get("auth_profiles") or [] if isinstance(item, dict)]
    existing_ids = {str(item.get("id") or "").strip() for item in profiles}
    if entry["metadata"]["selection_mode"] == "manual" and selected_id in existing_ids:
        return
    preferred = _pick_preferred_profile(entry, prefer_selected=False)
    entry["selected_profile_id"] = str((preferred or {}).get("id") or "").strip()
    entry["metadata"]["selection_mode"] = "auto"


def _normalize_binding(binding: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(binding or {})
    source = str(payload.get("source") or payload.get("oauth_source") or "").strip()
    source_type = str(payload.get("source_type") or payload.get("oauth_provider") or "").strip()
    sync_policy = str(payload.get("sync_policy") or "").strip().lower()
    if sync_policy not in {"manual", "import_copy", "follow"}:
        sync_policy = "follow" if payload.get("follow_local_auth") else "manual"
    credential_source = str(payload.get("credential_source") or "").strip().lower()
    if credential_source not in {
        "manual_input",
        "oauth_callback",
        "local_cli",
        "local_app",
        "local_extension",
        "local_config_file",
        "system_keychain",
        "browser_session",
        "imported_session",
    }:
        credential_source = "manual_input"
    return {
        "source": source,
        "source_type": source_type,
        "credential_source": credential_source,
        "sync_policy": sync_policy,
        "follow_local_auth": bool(payload.get("follow_local_auth")),
        "locator_path": str(payload.get("locator_path") or "").strip(),
        "account_label": str(payload.get("account_label") or "").strip(),
        "account_id": str(payload.get("account_id") or "").strip(),
        "metadata": dict(payload.get("metadata") or {}),
    }


def _normalize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(profile or {})
    normalized["id"] = str(normalized.get("id") or "").strip()
    normalized["provider_id"] = str(normalized.get("provider_id") or "").strip().lower()
    normalized["method_id"] = str(normalized.get("method_id") or "").strip().lower()
    method_type = str(normalized.get("method_type") or AuthMethodType.API_KEY.value).strip().lower()
    if method_type not in {item.value for item in AuthMethodType}:
        method_type = AuthMethodType.API_KEY.value
    normalized["method_type"] = method_type
    normalized["label"] = str(normalized.get("label") or normalized["method_id"] or normalized["provider_id"]).strip()
    normalized["credential_ref"] = str(normalized.get("credential_ref") or "").strip()
    normalized["credential_source"] = str(normalized.get("credential_source") or "").strip()
    normalized["binding"] = _normalize_binding(normalized.get("binding"))
    normalized["metadata"] = dict(normalized.get("metadata") or {})
    return normalized


def _provider_map(center_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = center_payload.get("providers")
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = ((item.get("provider_id"), item) for item in raw if isinstance(item, dict))
    else:
        items = ()
    providers: Dict[str, Dict[str, Any]] = {}
    for provider_id, value in items:
        key = str(provider_id or "").strip().lower()
        if not key or not isinstance(value, dict):
            continue
        entry = _default_provider_entry(key)
        entry.update({k: deepcopy(v) for k, v in value.items() if k != "auth_profiles"})
        entry["provider_id"] = key
        entry["auth_profiles"] = [
            _normalize_profile(item)
            for item in value.get("auth_profiles") or []
            if isinstance(item, dict)
        ]
        entry["metadata"] = dict(entry.get("metadata") or {})
        entry["metadata"].setdefault("project_to_runtime", bool(entry["auth_profiles"]))
        entry["metadata"]["selection_mode"] = _normalize_selection_mode(entry["metadata"].get("selection_mode"))
        _reconcile_selected_profile(entry)
        providers[key] = entry
    for definition in list_provider_definitions():
        providers.setdefault(definition.id, _default_provider_entry(definition.id))
    return providers


def _resolve_oauth_method_id(provider_id: str, oauth_provider: Any) -> str:
    definition = get_provider_definition(provider_id)
    if definition is None:
        return ""
    auth_provider_id = str(oauth_provider or "").strip()
    for method in definition.auth_methods:
        if auth_provider_id and get_method_auth_provider_id(method) == auth_provider_id:
            return method.id
    for method in definition.auth_methods:
        if method.type in {AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH}:
            return method.id
    return ""


def _resolve_api_key_method_id(provider_id: str, candidate: Dict[str, Any]) -> str:
    definition = get_provider_definition(provider_id)
    if definition is None:
        return "api_key"
    base_url = str(candidate.get("base_url") or "").strip().lower()
    raw_key = str(candidate.get("api_key") or "").strip().lower()
    for method in definition.auth_methods:
        if method.type is not AuthMethodType.API_KEY:
            continue
        recommended_base_url = str(method.metadata.get("recommended_base_url") or "").strip().lower()
        key_prefix_hint = str(method.metadata.get("key_prefix_hint") or "").strip().lower()
        if recommended_base_url and base_url and base_url.startswith(recommended_base_url):
            return method.id
        if key_prefix_hint and raw_key.startswith(key_prefix_hint):
            return method.id
    for method in definition.auth_methods:
        if method.type is AuthMethodType.API_KEY:
            return method.id
    return "api_key"


def _credential_source_for_method(method_type: str) -> str:
    if method_type == AuthMethodType.API_KEY.value:
        return CredentialSource.MANUAL_INPUT.value
    if method_type == AuthMethodType.WEB_SESSION.value:
        return CredentialSource.IMPORTED_SESSION.value
    return CredentialSource.LOCAL_CONFIG_FILE.value


def _resolve_method_runtime_defaults(
    entry: Dict[str, Any],
    method,
    profile_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    metadata = dict(profile_metadata or {})
    method_metadata = dict(getattr(method, "metadata", {}) or {})
    return {
        "base_url": str(
            metadata.get("base_url")
            or method_metadata.get("recommended_base_url")
            or entry.get("default_base_url")
            or ""
        ).strip(),
        "model": str(
            metadata.get("model")
            or method_metadata.get("recommended_model")
            or entry.get("default_model")
            or ""
        ).strip(),
    }


def _upsert_profile(
    entry: Dict[str, Any],
    profile: Dict[str, Any],
    *,
    select: bool = False,
    selection_mode: Optional[str] = None,
) -> None:
    profile_id = str(profile.get("id") or "").strip()
    if not profile_id:
        raise ValueError("profile id is required")
    profiles = [item for item in entry.get("auth_profiles") or [] if isinstance(item, dict)]
    next_profiles = [item for item in profiles if str(item.get("id") or "").strip() != profile_id]
    next_profiles.append(_normalize_profile(profile))
    entry["auth_profiles"] = next_profiles
    entry.setdefault("metadata", {})
    entry["metadata"]["project_to_runtime"] = True
    if select:
        entry["selected_profile_id"] = profile_id
        entry["metadata"]["selection_mode"] = _normalize_selection_mode(selection_mode or "manual")
        return
    if not str(entry.get("selected_profile_id") or "").strip():
        entry["selected_profile_id"] = profile_id
    _reconcile_selected_profile(entry)


def _store_api_key_secret(
    provider_id: str,
    method_id: str,
    label: str,
    api_key: str,
    credential_store: CredentialStore,
) -> str:
    ref = f"provider-auth::{provider_id}::{method_id}::{_slugify(label, fallback='default')}"
    credential_store.set(
        ref,
        provider_id=provider_id,
        method_type=AuthMethodType.API_KEY.value,
        payload={"api_key": api_key},
    )
    return ref


def _ingest_legacy_candidate(
    candidate: Dict[str, Any],
    providers: Dict[str, Dict[str, Any]],
    *,
    credential_store: CredentialStore,
    is_active: bool,
) -> None:
    normalized = merge_provider_defaults(dict(candidate or {}))
    provider_id = str(
        normalized.get("provider_id")
        or infer_provider_id(
            provider_id=normalized.get("provider_id"),
            preset_name=normalized.get("name"),
            base_url=normalized.get("base_url"),
            model=normalized.get("model"),
        )
        or ""
    ).strip().lower()
    if not provider_id:
        return
    entry = providers.setdefault(provider_id, _default_provider_entry(provider_id))
    entry["legacy_preset_name"] = str(normalized.get("name") or entry.get("legacy_preset_name") or provider_id).strip()
    entry["alias"] = str(normalized.get("alias") or entry.get("alias") or "").strip()
    entry["default_model"] = str(normalized.get("model") or entry.get("default_model") or "").strip()
    entry["default_base_url"] = str(normalized.get("base_url") or entry.get("default_base_url") or "").strip()
    entry.setdefault("metadata", {})
    for field_name in (
        "timeout_sec",
        "max_retries",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "reasoning_effort",
        "embedding_model",
        "oauth_project_id",
        "oauth_location",
        "allow_empty_key",
    ):
        if normalized.get(field_name) not in (None, ""):
            entry["metadata"][field_name] = deepcopy(normalized.get(field_name))
    label_basis = str(normalized.get("name") or provider_id).strip()
    raw_key = str(normalized.get("api_key") or "").strip()
    if raw_key and not is_placeholder_key(raw_key):
        method_id = _resolve_api_key_method_id(provider_id, normalized)
        method = get_provider_method(provider_id, method_id)
        ref = _store_api_key_secret(provider_id, method_id, label_basis, raw_key, credential_store)
        _upsert_profile(
            entry,
            {
                "id": f"{provider_id}:{method_id}:{_slugify(label_basis, fallback='default')}",
                "provider_id": provider_id,
                "method_id": method_id,
                "method_type": AuthMethodType.API_KEY.value,
                "label": f"{entry['legacy_preset_name']} {method.label if method else 'API Key'}",
                "credential_ref": ref,
                "credential_source": CredentialSource.MANUAL_INPUT.value,
                "binding": {
                    "source": "manual_input",
                    "source_type": "api_key",
                    "credential_source": CredentialSource.MANUAL_INPUT.value,
                    "sync_policy": SyncPolicy.MANUAL.value,
                },
                "metadata": {
                    **dict(entry["metadata"]),
                    "base_url": str(
                        normalized.get("base_url")
                        or (method.metadata.get("recommended_base_url") if method else "")
                        or entry.get("default_base_url")
                        or ""
                    ).strip(),
                    "model": str(
                        normalized.get("model")
                        or (method.metadata.get("recommended_model") if method else "")
                        or entry.get("default_model")
                        or ""
                    ).strip(),
                },
            },
            select=is_active or str(normalized.get("auth_mode") or "").strip().lower() != "oauth",
            selection_mode="auto",
        )
    if str(normalized.get("auth_mode") or "").strip().lower() == "oauth":
        method_id = _resolve_oauth_method_id(provider_id, normalized.get("oauth_provider"))
        if method_id:
            method = get_provider_method(provider_id, method_id)
            follow_local_auth = bool(method and method.type is AuthMethodType.LOCAL_IMPORT)
            runtime_defaults = _resolve_method_runtime_defaults(entry, method, normalized)
            _upsert_profile(
                entry,
                {
                    "id": f"{provider_id}:{method_id}:{_slugify(label_basis, fallback='oauth')}",
                    "provider_id": provider_id,
                    "method_id": method_id,
                    "method_type": method.type.value if method else AuthMethodType.OAUTH.value,
                    "label": f"{entry['legacy_preset_name']} {method.label if method else 'OAuth'}",
                    "credential_ref": "",
                    "credential_source": _credential_source_for_method(method.type.value if method else "oauth"),
                    "binding": {
                        "source": str(normalized.get("oauth_source") or method_id).strip(),
                        "source_type": str(normalized.get("oauth_provider") or "").strip(),
                        "credential_source": _credential_source_for_method(method.type.value if method else "oauth"),
                        "sync_policy": SyncPolicy.FOLLOW.value if method and method.supports_follow_mode else SyncPolicy.IMPORT_COPY.value,
                        "follow_local_auth": follow_local_auth,
                        "metadata": dict(normalized.get("oauth_binding") or {}),
                    },
                    "metadata": {
                        **dict(entry["metadata"]),
                        "base_url": runtime_defaults["base_url"],
                        "model": runtime_defaults["model"],
                    },
                },
                select=is_active,
                selection_mode="auto",
            )


def _select_runtime_profile(entry: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]] | tuple[None, None]:
    for profile, context in _iter_runtime_profiles(entry):
        return profile, context
    return None, None


def _iter_runtime_profiles(entry: Dict[str, Any]) -> Iterable[tuple[Dict[str, Any], Dict[str, Any]]]:
    provider_id = str(entry.get("provider_id") or "").strip().lower()
    profiles = [item for item in entry.get("auth_profiles") or [] if isinstance(item, dict)]
    selected_id = str(entry.get("selected_profile_id") or "").strip()
    selection_mode = _normalize_selection_mode((entry.get("metadata") or {}).get("selection_mode"))
    ordered = sorted(
        profiles,
        key=lambda item: _profile_sort_key(
            entry,
            item,
            selected_id=selected_id,
            prefer_selected=selection_mode == "manual",
        ),
    )
    for profile in ordered:
        method = get_provider_method(provider_id, profile.get("method_id"))
        if method is None or not method.runtime_supported:
            continue
        profile_metadata = dict(profile.get("metadata") or {})
        if profile_metadata.get("runtime_ready") is False:
            continue
        yield profile, {
            "provider": get_provider_definition(provider_id),
            "method": method,
        }


def _build_runtime_preset(
    entry: Dict[str, Any],
    profile: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    provider_id = str(entry.get("provider_id") or "").strip().lower()
    method = context["method"]
    metadata = dict(entry.get("metadata") or {})
    binding = dict(profile.get("binding") or {})
    runtime_defaults = _resolve_method_runtime_defaults(entry, method, profile.get("metadata"))
    return {
        "name": str(entry.get("legacy_preset_name") or provider_id).strip() or provider_id,
        "provider_id": provider_id,
        "alias": str(entry.get("alias") or "").strip(),
        "base_url": runtime_defaults["base_url"],
        "api_key": "",
        "credential_ref": str(profile.get("credential_ref") or "").strip(),
        "auth_mode": "api_key" if method.type is AuthMethodType.API_KEY else "oauth",
        "oauth_provider": get_method_auth_provider_id(method),
        "oauth_source": str(binding.get("source") or method.id).strip(),
        "oauth_binding": binding,
        "oauth_experimental_ack": bool(method.experimental),
        "oauth_project_id": metadata.get("oauth_project_id"),
        "oauth_location": metadata.get("oauth_location"),
        "model": runtime_defaults["model"],
        "timeout_sec": metadata.get("timeout_sec", 10),
        "max_retries": metadata.get("max_retries", 2),
        "temperature": metadata.get("temperature", 0.6),
        "max_tokens": metadata.get("max_tokens", 512),
        "max_completion_tokens": metadata.get("max_completion_tokens"),
        "reasoning_effort": metadata.get("reasoning_effort"),
        "embedding_model": metadata.get("embedding_model"),
        "allow_empty_key": bool(metadata.get("allow_empty_key", False)),
        "provider_auth_profile_id": str(profile.get("id") or "").strip(),
    }


def project_provider_auth_center(api_cfg: Dict[str, Any]) -> Dict[str, Any]:
    projected = dict(api_cfg or {})
    center = projected.get("provider_auth_center") if isinstance(projected.get("provider_auth_center"), dict) else {}
    providers = _provider_map(center or {})
    managed = {provider_id for provider_id, entry in providers.items() if entry.get("metadata", {}).get("project_to_runtime")}
    kept_presets = []
    for preset in projected.get("presets") or []:
        if not isinstance(preset, dict):
            continue
        provider_id = str(preset.get("provider_id") or "").strip().lower()
        if provider_id and provider_id in managed:
            continue
        kept_presets.append(dict(preset))
    for provider_id in sorted(managed):
        entry = providers.get(provider_id) or {}
        profile, context = _select_runtime_profile(entry)
        if not profile or not context:
            continue
        kept_presets.append(_build_runtime_preset(entry, profile, context))
    projected["presets"] = kept_presets
    return projected


def hydrate_runtime_settings(settings: Dict[str, Any], *, credential_store: Optional[CredentialStore] = None) -> Dict[str, Any]:
    hydrated = dict(settings or {})
    if str(hydrated.get("auth_mode") or "").strip().lower() != "api_key":
        return hydrated
    if str(hydrated.get("api_key") or "").strip():
        return hydrated
    ref = str(hydrated.get("credential_ref") or "").strip()
    if not ref:
        return hydrated
    store = credential_store or get_credential_store()
    record = store.get(ref)
    payload = dict(record.payload or {}) if record else {}
    hydrated["api_key"] = str(payload.get("api_key") or "").strip()
    return hydrated


def ensure_provider_auth_center_config(
    config: Dict[str, Any],
    *,
    credential_store: Optional[CredentialStore] = None,
) -> Dict[str, Any]:
    normalized = deepcopy(config if isinstance(config, dict) else {})
    api_cfg = dict(normalized.get("api") or {})
    center = api_cfg.get("provider_auth_center") if isinstance(api_cfg.get("provider_auth_center"), dict) else {}
    providers = _provider_map(center or {})
    store = credential_store or get_credential_store()
    active_preset = str(api_cfg.get("active_preset") or "").strip()
    presets = [dict(item) for item in api_cfg.get("presets") or [] if isinstance(item, dict)]
    if not presets:
        root_candidate = {
            "name": active_preset or "root_config",
            "provider_id": api_cfg.get("provider_id"),
            "alias": api_cfg.get("alias"),
            "base_url": api_cfg.get("base_url"),
            "api_key": api_cfg.get("api_key"),
            "auth_mode": api_cfg.get("auth_mode"),
            "oauth_provider": api_cfg.get("oauth_provider"),
            "oauth_source": api_cfg.get("oauth_source"),
            "oauth_binding": api_cfg.get("oauth_binding"),
            "oauth_project_id": api_cfg.get("oauth_project_id"),
            "oauth_location": api_cfg.get("oauth_location"),
            "model": api_cfg.get("model"),
            "timeout_sec": api_cfg.get("timeout_sec"),
            "max_retries": api_cfg.get("max_retries"),
            "temperature": api_cfg.get("temperature"),
            "max_tokens": api_cfg.get("max_tokens"),
            "max_completion_tokens": api_cfg.get("max_completion_tokens"),
            "reasoning_effort": api_cfg.get("reasoning_effort"),
            "embedding_model": api_cfg.get("embedding_model"),
            "allow_empty_key": api_cfg.get("allow_empty_key"),
        }
        presets = [root_candidate]
    for candidate in presets:
        _ingest_legacy_candidate(
            candidate,
            providers,
            credential_store=store,
            is_active=str(candidate.get("name") or "").strip() == active_preset,
        )
    preferred_active_provider_id = str(center.get("active_provider_id") or "").strip().lower()
    if preferred_active_provider_id:
        preferred_entry = providers.get(preferred_active_provider_id) or {}
        preferred_profile, _ = _select_runtime_profile(preferred_entry)
        if preferred_profile is None:
            preferred_active_provider_id = ""
    api_cfg["provider_auth_center"] = {
        "version": CENTER_VERSION,
        "active_provider_id": preferred_active_provider_id or next(
            (
                provider_id
                for provider_id, entry in providers.items()
                if str(entry.get("legacy_preset_name") or "").strip() == active_preset
            ),
            "",
        ),
        "providers": providers,
        "updated_at": int(center.get("updated_at") or _now()),
    }
    api_cfg = project_provider_auth_center(api_cfg)
    active_provider_id = str(api_cfg["provider_auth_center"].get("active_provider_id") or "").strip().lower()
    active_name = ""
    for provider_id, entry in providers.items():
        if provider_id == active_provider_id:
            active_name = str(entry.get("legacy_preset_name") or "").strip()
            break
    if active_name:
        api_cfg["active_preset"] = active_name
    normalized["api"] = api_cfg
    return normalized
