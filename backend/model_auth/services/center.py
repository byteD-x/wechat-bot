from __future__ import annotations

import time
import webbrowser
from copy import deepcopy
from typing import Any, Dict, Optional

from backend.core.oauth_support import (
    launch_oauth_login,
    logout_oauth_provider,
    resolve_oauth_settings,
    submit_auth_callback,
)
from backend.core.config_service import get_config_service

from ..domain.enums import AuthMethodType, CredentialSource, SyncPolicy
from ..providers.registry import (
    get_method_auth_provider_id,
    get_provider_definition,
    get_provider_method,
    list_provider_definitions,
)
from ..storage.credential_store import get_credential_store
from ..sync.discovery import extract_locator_path, get_legacy_status_map, get_method_local_status
from ..sync.orchestrator import get_local_auth_sync_orchestrator
from .health import run_profile_health_check
from .migration import (
    _canonicalize_provider_id,
    _collect_runtime_metadata_values,
    _default_provider_entry,
    _normalize_runtime_base_url,
    _provider_map,
    _reconcile_selected_profile,
    _resolve_method_runtime_defaults,
    _runtime_metadata_field_names,
    _select_runtime_profile,
    _slugify,
    _store_api_key_secret,
    _upsert_profile,
    ensure_provider_auth_center_config,
    project_provider_auth_center,
)
from .status import build_provider_overview_cards


def _now() -> int:
    return int(time.time())


def _resolve_local_credential_source(method_type: AuthMethodType, local_status: Dict[str, Any]) -> str:
    if local_status.get("keychain_targets"):
        return CredentialSource.SYSTEM_KEYCHAIN.value
    if method_type is AuthMethodType.WEB_SESSION:
        return CredentialSource.BROWSER_SESSION.value
    return CredentialSource.LOCAL_CONFIG_FILE.value


def _preferred_account_label(local_status: Dict[str, Any], *, payload_label: Any = "", fallback: str = "") -> str:
    return str(
        local_status.get("account_email")
        or payload_label
        or local_status.get("account_label")
        or fallback
        or ""
    ).strip()


def _resolve_runtime_snapshot_payload(resolved_settings: Dict[str, Any], *, adapter_id: str) -> Dict[str, Any]:
    api_key = resolved_settings.get("api_key")
    if callable(api_key):
        api_key = api_key()
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError("本机登录源没有产出可同步的运行时凭据。")
    extra_headers = resolved_settings.get("extra_headers")
    if callable(extra_headers):
        extra_headers = extra_headers()
    return {
        "kind": "runtime_context_snapshot",
        "adapter_id": str(adapter_id or "").strip(),
        "api_key": api_key,
        "base_url": str(resolved_settings.get("base_url") or "").strip(),
        "auth_transport": str(resolved_settings.get("auth_transport") or "").strip(),
        "extra_headers": dict(extra_headers or {}) if isinstance(extra_headers, dict) else {},
        "metadata": dict(resolved_settings.get("resolved_auth_metadata") or {}),
        "captured_at": _now(),
    }


class ModelAuthCenterService:
    def __init__(self) -> None:
        self._config_service = get_config_service()
        self._credential_store = get_credential_store()
        self._sync_orchestrator = get_local_auth_sync_orchestrator()

    def _ensure_sync_started(self) -> None:
        self._sync_orchestrator.start()

    def _build_local_auth_sync_state(self) -> Dict[str, Any]:
        snapshot = self._sync_orchestrator.get_snapshot(reason="overview_state")
        return {
            "refreshing": bool(snapshot.get("refreshing")),
            "refreshed_at": int(snapshot.get("refreshed_at") or 0),
            "revision": int(snapshot.get("revision") or 0),
            "changed_provider_ids": [
                str(item).strip()
                for item in (snapshot.get("changed_provider_ids") or [])
                if str(item).strip()
            ],
            "message": str(snapshot.get("message") or "").strip(),
        }

    def _build_overview_response(self, config: Dict[str, Any], cards: list[Dict[str, Any]], *, message: str = "") -> Dict[str, Any]:
        center = dict(((config.get("api") or {}).get("provider_auth_center") or {}))
        return {
            "success": True,
            "message": message,
            "overview": {
                "updated_at": int(center.get("updated_at") or _now()),
                "active_provider_id": str(center.get("active_provider_id") or "").strip(),
                "cards": cards,
                "local_auth_sync": self._build_local_auth_sync_state(),
            },
        }

    def _needs_config_normalization(self, config: Dict[str, Any]) -> bool:
        api_cfg = dict(config.get("api") or {})
        center = api_cfg.get("provider_auth_center")
        if not isinstance(center, dict):
            return True
        if int(center.get("version") or 0) < 1:
            return True

        providers = center.get("providers")
        if not isinstance(providers, dict):
            return True

        current_provider_ids = {
            _canonicalize_provider_id(provider_id)
            for provider_id, payload in providers.items()
            if isinstance(payload, dict) and _canonicalize_provider_id(provider_id)
        }
        expected_provider_ids = {
            _canonicalize_provider_id(definition.id)
            for definition in list_provider_definitions()
            if _canonicalize_provider_id(definition.id)
        }
        return current_provider_ids != expected_provider_ids

    def _load_config(self) -> Dict[str, Any]:
        snapshot = self._config_service.get_snapshot()
        current = snapshot.to_dict()
        if not self._needs_config_normalization(current):
            return current
        normalized = ensure_provider_auth_center_config(current, credential_store=self._credential_store)
        if normalized != current:
            saved = self._config_service.save_effective_config(
                normalized,
                source="model_auth_center_migration",
            )
            return saved.to_dict()
        return normalized

    def _save_config(self, config: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        payload = deepcopy(config)
        api_cfg = dict(payload.get("api") or {})
        center = dict(api_cfg.get("provider_auth_center") or {})
        center["updated_at"] = _now()
        api_cfg["provider_auth_center"] = center
        payload["api"] = project_provider_auth_center(api_cfg)
        saved = self._config_service.save_effective_config(payload, source=source)
        return saved.to_dict()

    def _get_provider_entry(self, config: Dict[str, Any], provider_id: str) -> Dict[str, Any]:
        api_cfg = dict(config.get("api") or {})
        center = dict(api_cfg.get("provider_auth_center") or {})
        providers = _provider_map(center)
        key = _canonicalize_provider_id(provider_id)
        entry = providers.setdefault(key, _default_provider_entry(key))
        center["providers"] = providers
        api_cfg["provider_auth_center"] = center
        config["api"] = api_cfg
        return entry

    def _get_profile(self, entry: Dict[str, Any], profile_id: str) -> Optional[Dict[str, Any]]:
        wanted = str(profile_id or "").strip()
        for profile in entry.get("auth_profiles") or []:
            if isinstance(profile, dict) and str(profile.get("id") or "").strip() == wanted:
                return profile
        return None

    def _resolve_action_method(
        self,
        provider_id: str,
        method_id: str,
        *,
        allowed_types: tuple[AuthMethodType, ...] = (),
        require_browser_flow: bool = False,
        require_local_discovery: bool = False,
    ):
        def _matches(method) -> bool:
            if method is None:
                return False
            if allowed_types and method.type not in allowed_types:
                return False
            if require_browser_flow and not method.supports_browser_flow:
                return False
            if require_local_discovery and not method.supports_local_discovery:
                return False
            return True

        requested = get_provider_method(provider_id, method_id)
        if _matches(requested):
            return requested

        definition = get_provider_definition(provider_id)
        if definition is None:
            return None

        candidates = [method for method in definition.auth_methods if _matches(method)]
        wanted = str(method_id or "").strip().lower()
        if wanted:
            typed_matches = [method for method in candidates if method.type.value == wanted]
            if len(typed_matches) == 1:
                return typed_matches[0]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _should_sync_profile_field_from_provider_defaults(
        self,
        profile: Dict[str, Any],
        method,
        *,
        field_name: str,
        previous_default: str,
    ) -> bool:
        metadata = dict(profile.get("metadata") or {})
        current_value = str(metadata.get(field_name) or "").strip()
        if not current_value:
            return True
        previous = str(previous_default or "").strip()
        if previous and current_value == previous:
            return True
        method_metadata = dict(getattr(method, "metadata", {}) or {})
        recommended_value = str(method_metadata.get(f"recommended_{field_name}") or "").strip()
        return bool(method.id == "api_key" and recommended_value and current_value == recommended_value)

    def _sync_selected_profile_defaults(
        self,
        entry: Dict[str, Any],
        provider_id: str,
        *,
        previous_default_model: str,
        previous_default_base_url: str,
        sync_model: bool,
        sync_base_url: bool,
    ) -> None:
        selected_profile = self._get_profile(entry, entry.get("selected_profile_id"))
        if selected_profile is None:
            return
        method = get_provider_method(provider_id, selected_profile.get("method_id"))
        if method is None:
            return
        metadata = dict(selected_profile.get("metadata") or {})
        changed = False
        if sync_model and self._should_sync_profile_field_from_provider_defaults(
            selected_profile,
            method,
            field_name="model",
            previous_default=previous_default_model,
        ):
            metadata["model"] = str(entry.get("default_model") or "").strip()
            changed = True
        if sync_base_url and self._should_sync_profile_field_from_provider_defaults(
            selected_profile,
            method,
            field_name="base_url",
            previous_default=previous_default_base_url,
        ):
            metadata["base_url"] = str(entry.get("default_base_url") or "").strip()
            changed = True
        if changed:
            selected_profile["metadata"] = metadata

    def _build_local_binding_metadata(self, local_status: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "account_email": str(local_status.get("account_email") or "").strip(),
            "account_label": str(local_status.get("account_label") or "").strip(),
            "detected_from_cli": bool(local_status.get("cli_available")),
            "local_storage_kind": str(local_status.get("local_storage_kind") or "").strip(),
            "browser_name": str(local_status.get("browser_name") or "").strip(),
            "browser_profile": str(local_status.get("browser_profile") or "").strip(),
            "cookie_count": int(local_status.get("cookie_count") or 0),
            "auth_cookie_count": int(local_status.get("auth_cookie_count") or 0),
            "keychain_provider": str(local_status.get("keychain_provider") or "").strip(),
            "keychain_targets": [
                str(item).strip()
                for item in (local_status.get("keychain_targets") or [])
                if str(item).strip()
            ],
            "keychain_locator": str(local_status.get("keychain_locator") or "").strip(),
            "managed_settings_path": str(local_status.get("managed_settings_path") or "").strip(),
            "cookie_path": str(local_status.get("cookie_path") or "").strip(),
            "indexeddb_path": str(local_status.get("indexeddb_path") or "").strip(),
            "local_storage_path": str(local_status.get("local_storage_path") or "").strip(),
            "private_storage_path": str(local_status.get("private_storage_path") or "").strip(),
            "private_auth_file_path": str(local_status.get("private_auth_file_path") or "").strip(),
            "watch_paths": [
                str(item).strip()
                for item in (local_status.get("watch_paths") or [])
                if str(item).strip()
            ],
        }

    def _build_runtime_settings_for_method(
        self,
        entry: Dict[str, Any],
        method,
        *,
        binding: Dict[str, Any],
        credential_ref: str = "",
        profile_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = dict(entry.get("metadata") or {})
        runtime_defaults = _resolve_method_runtime_defaults(entry, method, profile_metadata)
        settings = {
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
            "auth_mode": "oauth",
            "credential_ref": credential_ref,
            "oauth_provider": get_method_auth_provider_id(method),
            "oauth_source": str(binding.get("source") or method.id).strip(),
            "oauth_binding": dict(binding or {}),
            "oauth_experimental_ack": True,
        }
        settings.update(_collect_runtime_metadata_values(entry, method=method))
        return settings

    def _capture_import_copy_ref(
        self,
        entry: Dict[str, Any],
        method,
        *,
        label: str,
        binding: Dict[str, Any],
        profile_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        adapter_id = get_method_auth_provider_id(method)
        if not adapter_id:
            raise ValueError("这种认证方式暂不支持导入为可同步的登录副本。")
        resolved = resolve_oauth_settings(
            self._build_runtime_settings_for_method(
                entry,
                method,
                binding=binding,
                profile_metadata=profile_metadata,
            )
        ).settings
        payload = _resolve_runtime_snapshot_payload(resolved, adapter_id=adapter_id)
        ref = f"provider-auth::{entry.get('provider_id')}::{method.id}::{_slugify(label, fallback='imported')}"
        self._credential_store.set(
            ref,
            provider_id=str(entry.get("provider_id") or "").strip().lower(),
            method_type=method.type.value,
            payload=payload,
        )
        return ref

    def _save_and_render(self, config: Dict[str, Any], *, source: str, message: str = "") -> Dict[str, Any]:
        saved = self._save_config(config, source=source)
        cards = [
            card.to_dict()
            for card in build_provider_overview_cards(
                saved,
                credential_store=self._credential_store,
                assume_normalized=True,
            )
        ]
        return self._build_overview_response(saved, cards, message=message)

    def get_overview(self) -> Dict[str, Any]:
        self._ensure_sync_started()
        config = self._load_config()
        cards = [
            card.to_dict()
            for card in build_provider_overview_cards(
                config,
                credential_store=self._credential_store,
                assume_normalized=True,
            )
        ]
        return self._build_overview_response(config, cards)

    def scan(self) -> Dict[str, Any]:
        self._ensure_sync_started()
        self._sync_orchestrator.force_refresh(reason="manual_scan")
        config = self._load_config()
        return self._save_and_render(config, source="model_auth_center_scan", message="已重新检查本机登录源。")

    def update_provider_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        entry = self._get_provider_entry(config, provider_id)
        previous_default_model = str(entry.get("default_model") or "").strip()
        previous_default_base_url = str(entry.get("default_base_url") or "").strip()
        sync_model = False
        sync_base_url = False
        for field_name in ("legacy_preset_name", "alias", "default_model", "default_base_url"):
            value = payload.get(field_name)
            if value is not None:
                normalized_value = str(value or "").strip()
                if field_name == "default_base_url":
                    normalized_value = _normalize_runtime_base_url(normalized_value)
                entry[field_name] = normalized_value
                if field_name == "default_model":
                    sync_model = True
                elif field_name == "default_base_url":
                    sync_base_url = True
        entry.setdefault("metadata", {})
        for field_name in _runtime_metadata_field_names(provider_id):
            if field_name in payload:
                entry["metadata"][field_name] = str(payload.get(field_name) or "").strip()
        if sync_model or sync_base_url:
            self._sync_selected_profile_defaults(
                entry,
                provider_id,
                previous_default_model=previous_default_model,
                previous_default_base_url=previous_default_base_url,
                sync_model=sync_model,
                sync_base_url=sync_base_url,
            )
        entry["metadata"]["project_to_runtime"] = bool(entry.get("auth_profiles"))
        return self._save_and_render(config, source="model_auth_center_defaults", message="服务方默认设置已更新。")

    def save_api_key(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "api_key").strip().lower() or "api_key"
        api_key = str(payload.get("api_key") or "").strip()
        if not provider_id or not api_key:
            raise ValueError("缺少 provider_id 或 api_key。")
        method = self._resolve_action_method(
            provider_id,
            method_id,
            allowed_types=(AuthMethodType.API_KEY,),
        )
        if method is None or method.type is not AuthMethodType.API_KEY:
            raise ValueError("这家服务方不支持 API Key 认证。")
        config = self._load_config()
        entry = self._get_provider_entry(config, provider_id)
        label = str(payload.get("label") or method.label or entry.get("legacy_preset_name") or provider_id).strip()
        requested_model = str(payload.get("default_model") or "").strip()
        requested_base_url = _normalize_runtime_base_url(payload.get("default_base_url"))
        recommended_model = str(method.metadata.get("recommended_model") or "").strip()
        recommended_base_url = _normalize_runtime_base_url(method.metadata.get("recommended_base_url"))
        provider_default_model = str(entry.get("default_model") or "").strip()
        provider_default_base_url = _normalize_runtime_base_url(entry.get("default_base_url"))
        if method.id == "api_key":
            profile_model = requested_model or provider_default_model or recommended_model
            profile_base_url = requested_base_url or provider_default_base_url or recommended_base_url
        else:
            profile_model = requested_model or recommended_model or provider_default_model
            profile_base_url = requested_base_url or recommended_base_url or provider_default_base_url
        if payload.get("default_model") is not None and requested_model:
            entry["default_model"] = requested_model
        if payload.get("default_base_url") is not None and requested_base_url:
            entry["default_base_url"] = requested_base_url
        ref = _store_api_key_secret(provider_id, method_id, label, api_key, self._credential_store)
        _upsert_profile(
            entry,
            {
                "id": f"{provider_id}:{method_id}:{_slugify(label, fallback='default')}",
                "provider_id": provider_id,
                "method_id": method_id,
                "method_type": AuthMethodType.API_KEY.value,
                "label": label,
                "credential_ref": ref,
                "credential_source": CredentialSource.MANUAL_INPUT.value,
                "binding": {
                    "source": "manual_input",
                    "source_type": "api_key",
                    "credential_source": CredentialSource.MANUAL_INPUT.value,
                    "sync_policy": SyncPolicy.MANUAL.value,
                },
                "metadata": {
                    "base_url": profile_base_url,
                    "model": profile_model,
                    "method_label": method.label,
                    "key_env_hint": str(method.metadata.get("key_env_hint") or "").strip(),
                    "subscription": bool(method.metadata.get("subscription")),
                },
            },
            select=bool(payload.get("set_default", True)),
            selection_mode="manual",
        )
        return self._save_and_render(
            config,
            source="model_auth_center_api_key",
            message=f"{method.label} 已安全保存。",
        )

    def _bind_local_auth_profile(self, payload: Dict[str, Any], *, follow_local_auth: bool) -> Dict[str, Any]:
        self._ensure_sync_started()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "").strip().lower()
        method = self._resolve_action_method(
            provider_id,
            method_id,
            allowed_types=(AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH, AuthMethodType.WEB_SESSION),
            require_local_discovery=True,
        )
        if method is None or (
            method.type not in {AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH, AuthMethodType.WEB_SESSION}
            or not method.supports_local_discovery
        ):
            raise ValueError("这种认证方式不支持绑定本机登录。")
        method_id = method.id
        statuses = get_legacy_status_map(force_refresh=True)
        local_status = get_method_local_status(method, statuses)
        if not bool(local_status.get("detected") or local_status.get("configured")):
            raise ValueError("当前没有检测到可同步的本机登录源。")
        if follow_local_auth and not method.supports_follow_mode:
            raise ValueError("这种认证方式不支持跟随模式。")
        if not follow_local_auth and not method.supports_import_copy:
            raise ValueError("这种认证方式不支持导入副本模式。")
        config = self._load_config()
        entry = self._get_provider_entry(config, provider_id)
        label = _preferred_account_label(local_status, payload_label=payload.get("label"), fallback=method.label)
        credential_source = _resolve_local_credential_source(method.type, local_status)
        adapter_id = get_method_auth_provider_id(method)
        binding = {
            "source": str(local_status.get("local_source_label") or method.id).strip(),
            "source_type": str(adapter_id or method.type.value).strip(),
            "credential_source": credential_source,
            "sync_policy": SyncPolicy.FOLLOW.value if follow_local_auth else SyncPolicy.IMPORT_COPY.value,
            "follow_local_auth": bool(follow_local_auth),
            "locator_path": extract_locator_path(local_status),
            "account_label": _preferred_account_label(local_status),
            "metadata": self._build_local_binding_metadata(local_status),
        }
        runtime_defaults = _resolve_method_runtime_defaults(entry, method)
        credential_ref = ""
        if follow_local_auth:
            runtime_ready = bool(local_status.get("runtime_available")) if "runtime_available" in local_status else bool(local_status.get("configured"))
            runtime_unavailable_reason = str(local_status.get("runtime_unavailable_reason") or "").strip()
            if not runtime_ready and not runtime_unavailable_reason:
                runtime_unavailable_reason = "已经检测到本机登录源，但暂时还不能直接投射到运行时请求。"
        else:
            credential_ref = self._capture_import_copy_ref(
                entry,
                method,
                label=label,
                binding=binding,
                profile_metadata={
                    "base_url": runtime_defaults["base_url"],
                    "model": runtime_defaults["model"],
                },
            )
            runtime_ready = bool(method.runtime_supported)
            runtime_unavailable_reason = ""
        _upsert_profile(
            entry,
            {
                "id": f"{provider_id}:{method_id}:{_slugify(label, fallback='local')}",
                "provider_id": provider_id,
                "method_id": method_id,
                "method_type": method.type.value,
                "label": label,
                "credential_ref": credential_ref,
                "credential_source": credential_source,
                "binding": binding,
                "metadata": {
                    "base_url": runtime_defaults["base_url"],
                    "model": runtime_defaults["model"],
                    "method_label": method.label,
                    "runtime_ready": runtime_ready,
                    "runtime_available": runtime_ready,
                    "runtime_unavailable_reason": runtime_unavailable_reason,
                },
            },
            select=bool(payload.get("set_default", True)),
            selection_mode="manual",
        )
        action_source = "model_auth_center_local_bind" if follow_local_auth else "model_auth_center_local_import_copy"
        action_message = "已保存本机登录同步配置。" if follow_local_auth else "已导入一份静态的本机登录副本。"
        return self._save_and_render(config, source=action_source, message=action_message)

    def bind_local_auth(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "").strip().lower()
        method = self._resolve_action_method(
            provider_id,
            method_id,
            allowed_types=(AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH, AuthMethodType.WEB_SESSION),
            require_local_discovery=True,
        )
        follow_local_auth = bool(method and method.supports_follow_mode)
        next_payload = dict(payload)
        if method is not None:
            next_payload["method_id"] = method.id
        return self._bind_local_auth_profile(next_payload, follow_local_auth=follow_local_auth)

    def import_local_auth_copy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._bind_local_auth_profile(payload, follow_local_auth=False)

    def import_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "").strip().lower()
        session_payload = payload.get("session_payload")
        if not provider_id or not method_id or session_payload in (None, "", {}):
            raise ValueError("缺少 provider_id、method_id 或 session_payload。")
        method = get_provider_method(provider_id, method_id)
        if method is None or method.type is not AuthMethodType.WEB_SESSION:
            raise ValueError("这家服务方不支持导入网页登录会话。")
        config = self._load_config()
        entry = self._get_provider_entry(config, provider_id)
        label = str(payload.get("label") or method.label).strip()
        runtime_defaults = _resolve_method_runtime_defaults(entry, method)
        runtime_ready = bool(method.runtime_supported)
        runtime_unavailable_reason = ""
        if not runtime_ready:
            runtime_unavailable_reason = (
                "网页登录会话已经导入，但这种认证方式暂时还不能直接用于运行时调用。"
            )
        ref = f"provider-auth::{provider_id}::{method_id}::{_slugify(label, fallback='session')}"
        self._credential_store.set(
            ref,
            provider_id=provider_id,
            method_type=method.type.value,
            payload={"session_payload": session_payload},
        )
        _upsert_profile(
            entry,
            {
                "id": f"{provider_id}:{method_id}:{_slugify(label, fallback='session')}",
                "provider_id": provider_id,
                "method_id": method_id,
                "method_type": method.type.value,
                "label": label,
                "credential_ref": ref,
                "credential_source": CredentialSource.IMPORTED_SESSION.value,
                "binding": {
                    "source": "imported_session",
                    "source_type": "web_session",
                    "credential_source": CredentialSource.IMPORTED_SESSION.value,
                    "sync_policy": SyncPolicy.IMPORT_COPY.value,
                },
                "metadata": {
                    "base_url": runtime_defaults["base_url"],
                    "model": runtime_defaults["model"],
                    "method_label": method.label,
                    "runtime_ready": runtime_ready,
                    "runtime_available": runtime_ready,
                    "runtime_unavailable_reason": runtime_unavailable_reason,
                },
            },
            select=bool(payload.get("set_default", True)),
            selection_mode="manual",
        )
        return self._save_and_render(config, source="model_auth_center_session_import", message="登录会话已安全导入。")

    def start_browser_auth(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "").strip().lower()
        method = self._resolve_action_method(
            provider_id,
            method_id,
            require_browser_flow=True,
        )
        if method is None or not method.supports_browser_flow:
            raise ValueError("这种认证方式不支持网页登录。")
        method_id = method.id
        adapter_id = get_method_auth_provider_id(method)
        config = self._load_config()
        entry = self._get_provider_entry(config, provider_id)
        entry.setdefault("metadata", {})
        pending = dict(entry["metadata"].get("pending_flows") or {})
        if adapter_id:
            settings = _collect_runtime_metadata_values(entry, method=method, provider_id=provider_id)
            result = launch_oauth_login(adapter_id, settings=settings)
            pending[method_id] = {
                "flow_id": str(result.get("flow_id") or "").strip(),
                "auth_provider_id": adapter_id,
                "started_at": int(result.get("created_at") or _now()),
            }
            entry["metadata"]["pending_flows"] = pending
            response = self._save_and_render(config, source="model_auth_center_browser_start", message=str(result.get("message") or "网页登录流程已启动。"))
            response["action_result"] = result
            return response
        if method.browser_entry_url:
            webbrowser.open(method.browser_entry_url)
        pending[method_id] = {
            "flow_id": "",
            "auth_provider_id": "",
            "started_at": _now(),
            "browser_entry_url": str(method.browser_entry_url or "").strip(),
        }
        entry["metadata"]["pending_flows"] = pending
        return self._save_and_render(config, source="model_auth_center_browser_hint", message="登录页已打开。登录后回来继续。")

    def complete_browser_auth(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        method_id = str(payload.get("method_id") or "").strip().lower()
        flow_id = str(payload.get("flow_id") or "").strip()
        if flow_id == "__local_rescan__":
            flow_id = ""
        method = self._resolve_action_method(
            provider_id,
            method_id,
            require_browser_flow=True,
        )
        if method is None or not method.supports_browser_flow:
            raise ValueError("provider_id 和 method_id 必须指向支持网页登录的认证方式。")
        method_id = method.id
        adapter_id = get_method_auth_provider_id(method)
        browser_flow_completion = str(method.metadata.get("browser_flow_completion") or "").strip().lower()
        if adapter_id and flow_id and browser_flow_completion != "local_rescan":
            result = submit_auth_callback(adapter_id, flow_id, payload=payload.get("callback_payload"))
        else:
            statuses = get_legacy_status_map(force_refresh=True)
            local_status = get_method_local_status(method, statuses)
            local_available = bool(local_status.get("detected") or local_status.get("configured"))
            result = {
                "success": True,
                "completed": local_available,
                "message": (
                    "已检测到可同步的本机登录状态。"
                    if local_available
                    else "还没检测到本机登录。先登录，再试一次。"
                ),
            }
        config = self._load_config()
        entry = self._get_provider_entry(config, provider_id)
        pending = dict((entry.get("metadata") or {}).get("pending_flows") or {})
        if result.get("completed"):
            pending.pop(method_id, None)
            entry.setdefault("metadata", {})
            entry["metadata"]["pending_flows"] = pending
            local_status = get_method_local_status(method, get_legacy_status_map(force_refresh=True))
            local_available = bool(local_status.get("detected") or local_status.get("configured"))
            label = _preferred_account_label(local_status, payload_label=payload.get("label"), fallback=method.label)
            local_credential_source = _resolve_local_credential_source(method.type, local_status)
            runtime_defaults = _resolve_method_runtime_defaults(entry, method)
            runtime_ready = bool(local_status.get("runtime_available")) if "runtime_available" in local_status else bool(local_available)
            runtime_unavailable_reason = str(local_status.get("runtime_unavailable_reason") or "").strip()
            if not runtime_ready and not runtime_unavailable_reason:
                runtime_unavailable_reason = (
                    "已登录，但还没检测到可同步的本机登录状态。"
                    if not local_available
                    else "已检测到本机登录状态，但当前还不能直接用于运行时请求。"
                )
            _upsert_profile(
                entry,
                {
                    "id": f"{provider_id}:{method_id}:{_slugify(label, fallback='oauth')}",
                    "provider_id": provider_id,
                    "method_id": method_id,
                    "method_type": method.type.value,
                    "label": label,
                    "credential_ref": "",
                    "credential_source": (
                        local_credential_source
                        if local_available
                        else CredentialSource.OAUTH_CALLBACK.value
                    ),
                    "binding": {
                        "source": str(local_status.get("local_source_label") or adapter_id or method.id).strip(),
                        "source_type": str(adapter_id or method.type.value).strip(),
                        "credential_source": (
                            local_credential_source
                            if local_available
                            else CredentialSource.OAUTH_CALLBACK.value
                        ),
                        "sync_policy": SyncPolicy.FOLLOW.value if method.supports_follow_mode else SyncPolicy.MANUAL.value,
                        "follow_local_auth": bool(method.supports_follow_mode and local_available),
                        "locator_path": extract_locator_path(local_status),
                        "account_label": _preferred_account_label(local_status),
                        "metadata": {
                            **self._build_local_binding_metadata(local_status),
                            "awaiting_local_sync": not local_available,
                            "callback_completed_at": _now(),
                        },
                    },
                    "metadata": {
                        "base_url": runtime_defaults["base_url"],
                        "model": runtime_defaults["model"],
                        "method_label": method.label,
                        "runtime_ready": runtime_ready,
                        "runtime_available": runtime_ready,
                        "runtime_unavailable_reason": runtime_unavailable_reason,
                    },
                },
                select=bool(payload.get("set_default", True)),
                selection_mode="manual",
            )
            return self._save_and_render(
                config,
                source="model_auth_center_browser_complete",
                message=str(
                    result.get("message")
                    or (
                        "网页登录已完成，已关联本机登录。"
                        if local_available
                        else "网页登录已完成，等待本机登录同步。"
                    )
                ),
            )
        pending[method_id] = {
            "flow_id": flow_id,
            "auth_provider_id": adapter_id,
            "started_at": int(result.get("created_at") or pending.get(method_id, {}).get("started_at") or _now()),
        }
        entry.setdefault("metadata", {})
        entry["metadata"]["pending_flows"] = pending
        response = self._save_and_render(config, source="model_auth_center_browser_poll", message=str(result.get("message") or "还在等待登录完成。"))
        response["action_result"] = result
        return response

    def set_default_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        profile_id = str(payload.get("profile_id") or "").strip()
        entry = self._get_provider_entry(config, provider_id)
        if not self._get_profile(entry, profile_id):
            raise ValueError("未找到这组认证配置。")
        entry["selected_profile_id"] = profile_id
        entry.setdefault("metadata", {})
        entry["metadata"]["selection_mode"] = "manual"
        return self._save_and_render(config, source="model_auth_center_default_profile", message="默认认证已更新。")

    def set_active_provider(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        entry = self._get_provider_entry(config, provider_id)
        profile, _ = _select_runtime_profile(entry)
        if profile is None:
            raise ValueError("请先配置一组支持运行时调用的认证，再设为当前回复模型。")
        center = dict(((config.get("api") or {}).get("provider_auth_center") or {}))
        center["active_provider_id"] = provider_id
        api_cfg = dict(config.get("api") or {})
        api_cfg["provider_auth_center"] = center
        api_cfg["active_preset"] = str(entry.get("legacy_preset_name") or provider_id).strip() or provider_id
        config["api"] = api_cfg
        return self._save_and_render(config, source="model_auth_center_active_provider", message="当前回复模型已更新。")

    async def test_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        profile_id = str(payload.get("profile_id") or "").strip()
        entry = self._get_provider_entry(config, provider_id)
        profile = self._get_profile(entry, profile_id)
        if profile is None:
            raise ValueError("未找到这组认证配置。")
        health = await run_profile_health_check(entry, profile, credential_store=self._credential_store)
        profile.setdefault("metadata", {})
        profile["metadata"]["health"] = {
            "ok": health.ok,
            "state": health.state,
            "checked_at": health.checked_at,
            "message": health.message,
            "error_code": health.error_code,
            "can_retry": health.can_retry,
        }
        return self._save_and_render(
            config,
            source="model_auth_center_test_profile",
            message=health.message or "连接检查已完成。",
        )

    def disconnect_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        profile_id = str(payload.get("profile_id") or "").strip()
        entry = self._get_provider_entry(config, provider_id)
        profile = self._get_profile(entry, profile_id)
        if profile is None:
            raise ValueError("未找到这组认证配置。")
        ref = str(profile.get("credential_ref") or "").strip()
        if ref:
            self._credential_store.delete(ref)
        entry["auth_profiles"] = [
            item for item in entry.get("auth_profiles") or []
            if str((item or {}).get("id") or "").strip() != profile_id
        ]
        _reconcile_selected_profile(entry)
        return self._save_and_render(config, source="model_auth_center_disconnect", message="这组认证已移除。")

    def logout_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._load_config()
        provider_id = _canonicalize_provider_id(payload.get("provider_id"))
        profile_id = str(payload.get("profile_id") or "").strip()
        entry = self._get_provider_entry(config, provider_id)
        profile = self._get_profile(entry, profile_id)
        if profile is None:
            raise ValueError("未找到这组认证配置。")
        method = get_provider_method(provider_id, profile.get("method_id"))
        adapter_id = get_method_auth_provider_id(method)
        if method is None or not adapter_id:
            raise ValueError("这组认证不支持退出本机登录。")
        result = logout_oauth_provider(adapter_id, settings={})
        self._ensure_sync_started()
        self._sync_orchestrator.force_refresh(reason="source_logout")
        return self._save_and_render(
            config,
            source="model_auth_center_logout_source",
            message=str(result.get("message") or "已退出本机登录。"),
        )

    async def perform_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        wanted = str(action or "").strip().lower()
        if wanted == "scan":
            return self.scan()
        if wanted == "update_provider_defaults":
            return self.update_provider_defaults(payload)
        if wanted == "save_api_key":
            return self.save_api_key(payload)
        if wanted == "bind_local_auth":
            return self.bind_local_auth(payload)
        if wanted == "import_local_auth_copy":
            return self.import_local_auth_copy(payload)
        if wanted == "import_session":
            return self.import_session(payload)
        if wanted == "start_browser_auth":
            return self.start_browser_auth(payload)
        if wanted == "complete_browser_auth":
            return self.complete_browser_auth(payload)
        if wanted == "set_default_profile":
            return self.set_default_profile(payload)
        if wanted == "set_active_provider":
            return self.set_active_provider(payload)
        if wanted == "test_profile":
            return await self.test_profile(payload)
        if wanted == "disconnect_profile":
            return self.disconnect_profile(payload)
        if wanted == "logout_source":
            return self.logout_source(payload)
        raise ValueError(f"暂不支持的操作：{action}")


_SERVICE = ModelAuthCenterService()


def get_model_auth_center_service() -> ModelAuthCenterService:
    return _SERVICE
