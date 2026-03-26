from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums import AuthMethodType, AuthStatus, CredentialSource, SyncPolicy


@dataclass(frozen=True)
class ProviderCapability:
    supports_api_key: bool = False
    supports_oauth: bool = False
    supports_local_auth_import: bool = False
    supports_web_session: bool = False
    supports_multi_account: bool = False
    supports_health_check: bool = False
    supports_auto_refresh: bool = False
    supports_local_file_watch: bool = False
    supports_default_auth_selection: bool = True
    supports_credential_follow_mode: bool = False


@dataclass(frozen=True)
class AuthMethodDefinition:
    id: str
    type: AuthMethodType
    label: str
    description: str = ""
    experimental: bool = False
    runtime_supported: bool = True
    supports_browser_flow: bool = False
    supports_local_discovery: bool = False
    supports_follow_mode: bool = False
    supports_import_copy: bool = False
    supports_multi_account: bool = False
    supports_refresh: bool = False
    requires_fields: tuple[str, ...] = ()
    auth_provider_id: str = ""
    legacy_provider_id: str = ""
    browser_entry_url: str = ""
    api_key_url: str = ""
    browser_flow_kind: str = ""
    connect_label: str = ""
    follow_label: str = ""
    import_label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    label: str
    description: str
    homepage_url: str = ""
    docs_url: str = ""
    api_key_url: str = ""
    default_base_url: str = ""
    default_model: str = ""
    capability: ProviderCapability = field(default_factory=ProviderCapability)
    auth_methods: tuple[AuthMethodDefinition, ...] = ()
    default_auth_order: tuple[str, ...] = ()
    supported_models: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CredentialBinding:
    source: str = ""
    source_type: str = ""
    credential_source: CredentialSource = CredentialSource.MANUAL_INPUT
    sync_policy: SyncPolicy = SyncPolicy.MANUAL
    follow_local_auth: bool = False
    locator_path: str = ""
    account_label: str = ""
    account_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthProfileRecord:
    id: str
    provider_id: str
    method_id: str
    method_type: AuthMethodType
    label: str
    credential_ref: str = ""
    credential_source: str = ""
    binding: CredentialBinding | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    ok: bool = False
    state: str = "unknown"
    checked_at: int = 0
    message: str = ""
    error_code: str = ""
    can_retry: bool = True


@dataclass
class AuthStateSnapshot:
    provider_id: str
    method_id: str
    status: AuthStatus
    summary: str
    detail: str = ""
    account_label: str = ""
    account_email: str = ""
    default_selected: bool = False
    available_actions: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    health: HealthCheckResult = field(default_factory=HealthCheckResult)
    binding: CredentialBinding | None = None
    has_secret: bool = False
    requires_attention: bool = False
    experimental: bool = False
    runtime_supported: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderOverviewCard:
    provider: ProviderDefinition
    state: AuthStatus
    summary: str
    detail: str = ""
    sort_order: int = 99
    selected_profile_id: str = ""
    selected_method_id: str = ""
    selected_method_type: str = ""
    selected_label: str = ""
    auth_states: List[AuthStateSnapshot] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": {
                "id": self.provider.id,
                "label": self.provider.label,
                "description": self.provider.description,
                "homepage_url": self.provider.homepage_url,
                "docs_url": self.provider.docs_url,
                "api_key_url": self.provider.api_key_url,
                "default_base_url": self.provider.default_base_url,
                "default_model": self.provider.default_model,
                "capability": {
                    "supportsApiKey": self.provider.capability.supports_api_key,
                    "supportsOAuth": self.provider.capability.supports_oauth,
                    "supportsLocalAuthImport": self.provider.capability.supports_local_auth_import,
                    "supportsWebSession": self.provider.capability.supports_web_session,
                    "supportsMultiAccount": self.provider.capability.supports_multi_account,
                    "supportsHealthCheck": self.provider.capability.supports_health_check,
                    "supportsAutoRefresh": self.provider.capability.supports_auto_refresh,
                    "supportsLocalFileWatch": self.provider.capability.supports_local_file_watch,
                    "supportsDefaultAuthSelection": self.provider.capability.supports_default_auth_selection,
                    "supportsCredentialFollowMode": self.provider.capability.supports_credential_follow_mode,
                },
                "auth_methods": [
                    {
                        "id": method.id,
                        "type": method.type.value,
                        "label": method.label,
                        "description": method.description,
                        "experimental": method.experimental,
                        "runtime_supported": method.runtime_supported,
                        "supports_browser_flow": method.supports_browser_flow,
                        "supports_local_discovery": method.supports_local_discovery,
                        "supports_follow_mode": method.supports_follow_mode,
                        "supports_import_copy": method.supports_import_copy,
                        "supports_multi_account": method.supports_multi_account,
                        "supports_refresh": method.supports_refresh,
                        "requires_fields": list(method.requires_fields),
                        "auth_provider_id": method.auth_provider_id,
                        "browser_flow_kind": method.browser_flow_kind,
                        "connect_label": method.connect_label,
                        "follow_label": method.follow_label,
                        "import_label": method.import_label,
                        "browser_entry_url": method.browser_entry_url,
                        "api_key_url": method.api_key_url,
                        "metadata": dict(method.metadata),
                    }
                    for method in self.provider.auth_methods
                ],
                "default_auth_order": list(self.provider.default_auth_order),
                "supported_models": list(self.provider.supported_models),
                "tags": list(self.provider.tags),
                "metadata": dict(self.provider.metadata),
            },
            "state": self.state.value,
            "summary": self.summary,
            "detail": self.detail,
            "sort_order": self.sort_order,
            "selected_profile_id": self.selected_profile_id,
            "selected_method_id": self.selected_method_id,
            "selected_method_type": self.selected_method_type,
            "selected_label": self.selected_label,
            "auth_states": [
                {
                    "provider_id": item.provider_id,
                    "method_id": item.method_id,
                    "status": item.status.value,
                    "summary": item.summary,
                    "detail": item.detail,
                    "account_label": item.account_label,
                    "account_email": item.account_email,
                    "default_selected": item.default_selected,
                    "available_actions": list(item.available_actions),
                    "actions": list(item.actions),
                    "health": {
                        "ok": item.health.ok,
                        "state": item.health.state,
                        "checked_at": item.health.checked_at,
                        "message": item.health.message,
                        "error_code": item.health.error_code,
                        "can_retry": item.health.can_retry,
                    },
                    "binding": {
                        "source": item.binding.source,
                        "source_type": item.binding.source_type,
                        "credential_source": item.binding.credential_source.value,
                        "sync_policy": item.binding.sync_policy.value,
                        "follow_local_auth": item.binding.follow_local_auth,
                        "locator_path": item.binding.locator_path,
                        "account_label": item.binding.account_label,
                        "account_id": item.binding.account_id,
                        "metadata": dict(item.binding.metadata),
                    }
                    if item.binding
                    else None,
                    "has_secret": item.has_secret,
                    "requires_attention": item.requires_attention,
                    "experimental": item.experimental,
                    "runtime_supported": item.runtime_supported,
                    "metadata": dict(item.metadata),
                }
                for item in self.auth_states
            ],
            "actions": list(self.actions),
            "metadata": dict(self.metadata),
        }
