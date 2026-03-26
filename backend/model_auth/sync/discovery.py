from __future__ import annotations

from typing import Any, Dict

from ..domain.models import AuthMethodDefinition
from ..providers.registry import get_method_auth_provider_id
from .orchestrator import get_local_auth_sync_orchestrator


def get_legacy_status_map(*, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    payload = get_local_auth_sync_orchestrator().get_snapshot(
        force_refresh=force_refresh,
        reason="discovery_scan" if force_refresh else "discovery_read",
    )
    providers = payload.get("providers") if isinstance(payload, dict) else {}
    if not isinstance(providers, dict):
        return {}
    return {
        str(provider_id): dict(status or {})
        for provider_id, status in providers.items()
        if isinstance(status, dict)
    }


def get_method_local_status(
    method: AuthMethodDefinition,
    statuses: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    adapter_id = get_method_auth_provider_id(method)
    if not adapter_id:
        return {}
    resolved = statuses or get_legacy_status_map()
    status = resolved.get(adapter_id)
    return dict(status or {}) if isinstance(status, dict) else {}


def extract_locator_path(status: Dict[str, Any]) -> str:
    for key in (
        "auth_path",
        "oauth_creds_path",
        "google_accounts_path",
        "config_path",
        "managed_settings_path",
        "keychain_locator",
        "private_storage_path",
        "session_path",
        "cookie_path",
        "indexeddb_path",
        "local_storage_path",
    ):
        value = str(status.get(key) or "").strip()
        if value:
            return value
    return ""
