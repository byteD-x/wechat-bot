from __future__ import annotations

from typing import Any, Dict, List

from ..domain.enums import AuthMethodType, AuthStatus, CredentialSource, SyncPolicy
from ..domain.models import (
    AuthStateSnapshot,
    CredentialBinding,
    HealthCheckResult,
    ProviderOverviewCard,
)
from ..providers.registry import (
    get_method_auth_provider_id,
    get_provider_definition,
    get_provider_required_fields,
)
from ..storage.credential_store import CredentialStore, get_credential_store
from ..sync.discovery import extract_locator_path, get_legacy_status_map, get_method_local_status
from ..sync.orchestrator import build_local_sync_state
from .migration import (
    _collect_runtime_metadata_values,
    _resolve_method_runtime_defaults,
    _resolve_profile_runtime_readiness,
    _select_runtime_profile,
    ensure_provider_auth_center_config,
)

_CARD_RANK = {
    AuthStatus.CONNECTED: 1,
    AuthStatus.FOLLOWING_LOCAL_AUTH: 2,
    AuthStatus.IMPORTED: 3,
    AuthStatus.CONNECTING: 4,
    AuthStatus.EXPIRED: 5,
    AuthStatus.INVALID: 5,
    AuthStatus.ERROR: 5,
    AuthStatus.AVAILABLE_TO_IMPORT: 6,
    AuthStatus.NOT_CONFIGURED: 7,
}

_READY_STATUSES = {AuthStatus.CONNECTED, AuthStatus.FOLLOWING_LOCAL_AUTH, AuthStatus.IMPORTED}
_ATTENTION_STATUSES = {AuthStatus.EXPIRED, AuthStatus.INVALID, AuthStatus.ERROR}


def _normalize_group_value(value: Any) -> str:
    return str(value or "").strip().lower()


def _get_account_display(*values: Any, fallback: str = "") -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return str(fallback or "").strip()


def _build_source_group(
    definition,
    method,
    *,
    local_status: Dict[str, Any],
    binding: Dict[str, Any],
    sync_state: Dict[str, Any],
    profile_id: str = "",
    placeholder: bool = False,
) -> Dict[str, str]:
    shared_auth_provider_id = str(get_method_auth_provider_id(method) or "").strip()
    binding_meta = dict(binding.get("metadata") or {})
    previous_local_sync = dict(binding_meta.get("local_sync") or {})
    account_key = (
        _normalize_group_value(previous_local_sync.get("account_key"))
        or _normalize_group_value(binding_meta.get("account_email"))
        or _normalize_group_value(sync_state.get("account_key"))
        or _normalize_group_value(local_status.get("account_email"))
        or _normalize_group_value(profile_id)
    )
    if not account_key:
        account_key = "placeholder" if placeholder else "unknown"
    if shared_auth_provider_id:
        label = (
            f"{definition.label} 本机会话"
            if method.type is AuthMethodType.WEB_SESSION
            else f"{definition.label} 登录态"
        )
        kind = "shared_auth_provider"
    else:
        label = method.label
        kind = "auth_method"
    return {
        "id": f"{shared_auth_provider_id or method.id}:{account_key}",
        "label": label,
        "kind": kind,
        "shared_auth_provider_id": shared_auth_provider_id or method.id,
        "account_key": account_key,
    }


def _resolve_runtime_readiness(
    entry: Dict[str, Any],
    method,
    profile: Dict[str, Any] | None,
    local_status: Dict[str, Any],
) -> tuple[bool, str]:
    if not bool(method.runtime_supported):
        return False, "这种认证方式暂不支持直接用于运行时调用。"
    if profile is not None:
        ready, reason = _resolve_profile_runtime_readiness(entry, profile, method)
        if not ready and not reason:
            reason = "这组认证已经配置，但暂时还没有可用于运行时请求的凭据。"
        return ready, reason
    ready = bool(local_status.get("runtime_available", True))
    reason = str(local_status.get("runtime_unavailable_reason") or "").strip()
    if not ready and not reason:
        reason = "已经检测到本机登录态，但暂时还不能直接投射到运行时请求。"
    return ready, reason


def _build_health(payload: Dict[str, Any] | None) -> HealthCheckResult:
    data = dict(payload or {})
    return HealthCheckResult(
        ok=bool(data.get("ok")),
        state=str(data.get("state") or "unknown").strip() or "unknown",
        checked_at=int(data.get("checked_at") or 0),
        message=str(data.get("message") or "").strip(),
        error_code=str(data.get("error_code") or "").strip(),
        can_retry=bool(data.get("can_retry", True)),
    )


def _build_binding(payload: Dict[str, Any] | None) -> CredentialBinding | None:
    if not isinstance(payload, dict):
        return None
    credential_source = str(payload.get("credential_source") or CredentialSource.MANUAL_INPUT.value).strip().lower()
    sync_policy = str(payload.get("sync_policy") or SyncPolicy.MANUAL.value).strip().lower()
    return CredentialBinding(
        source=str(payload.get("source") or "").strip(),
        source_type=str(payload.get("source_type") or "").strip(),
        credential_source=CredentialSource(credential_source),
        sync_policy=SyncPolicy(sync_policy),
        follow_local_auth=bool(payload.get("follow_local_auth")),
        locator_path=str(payload.get("locator_path") or "").strip(),
        account_label=str(payload.get("account_label") or "").strip(),
        account_id=str(payload.get("account_id") or "").strip(),
        metadata=dict(payload.get("metadata") or {}),
    )


def _api_key_status(profile: Dict[str, Any], credential_store: CredentialStore) -> tuple[AuthStatus, str, str]:
    ref = str(profile.get("credential_ref") or "").strip()
    if not ref:
        return AuthStatus.NOT_CONFIGURED, "API Key 未配置", "请补充或恢复这家服务方的 API Key。"
    lookup = credential_store.lookup(ref)
    if not lookup.exists:
        return AuthStatus.NOT_CONFIGURED, "API Key 未配置", "请补充或恢复这家服务方的 API Key。"
    if not lookup.readable:
        return AuthStatus.INVALID, "API Key 需要重新配置", "这条已保存的 API Key 无法读取，请重新填写。"
    return AuthStatus.CONNECTED, "API Key 已配置", "凭据已安全保存到后端凭据库。"


def _local_or_oauth_status(
    method_type: AuthMethodType,
    profile: Dict[str, Any],
    local_status: Dict[str, Any],
    credential_store: CredentialStore,
) -> tuple[AuthStatus, str, str]:
    binding = dict(profile.get("binding") or {})
    binding_meta = dict(binding.get("metadata") or {})
    sync_state = build_local_sync_state(profile, local_status)
    account_label = _get_account_display(
        local_status.get("account_email"),
        binding_meta.get("account_email"),
        local_status.get("account_label"),
        binding.get("account_label"),
    )
    sync_policy = str(binding.get("sync_policy") or SyncPolicy.MANUAL.value).strip().lower()
    configured = bool(local_status.get("configured"))
    detected = bool(local_status.get("detected"))
    source_error = str(sync_state.get("source_error") or "").strip()
    if source_error:
        return (
            AuthStatus.ERROR,
            "本机登录不可用",
            str(sync_state.get("source_message") or source_error).strip() or "无法读取本机登录源。",
        )
    switch_notice = ""
    if sync_state.get("account_switched"):
        next_label = _get_account_display(
            sync_state.get("account_email"),
            sync_state.get("account_label"),
            fallback="最新检测到的账号",
        )
        switch_notice = f" 本机登录账号已切换，当前正在跟随 {next_label}。"
    if sync_policy == SyncPolicy.IMPORT_COPY.value:
        ref = str(profile.get("credential_ref") or "").strip()
        lookup = credential_store.lookup(ref) if ref else None
        if lookup and lookup.readable:
            detail = account_label or "当前项目正在使用一份导入后冻结的认证副本。"
            if method_type is AuthMethodType.LOCAL_IMPORT:
                return AuthStatus.IMPORTED, "已导入本机登录副本", detail
            return AuthStatus.IMPORTED, "已导入认证副本", detail
        if lookup and lookup.exists:
            summary = "本机登录副本需要重新导入" if method_type is AuthMethodType.LOCAL_IMPORT else "认证副本需要重新导入"
            return (
                AuthStatus.INVALID,
                summary,
                "这份导入的认证副本无法读取，请重新导入或切回同步模式。",
            )
        return (
            AuthStatus.INVALID,
            "导入副本已失效",
            "这份导入的认证副本已经丢失，请重新导入或切回同步模式。",
        )
    if method_type is AuthMethodType.LOCAL_IMPORT:
        if configured or detected:
            return (
                AuthStatus.FOLLOWING_LOCAL_AUTH,
                "正在跟随本机登录",
                (account_label or "当前项目正在跟随本机登录源。") + switch_notice,
            )
        return AuthStatus.EXPIRED, "本机登录已丢失", "原先绑定的本机登录源已经不可用。"
    if configured or detected:
        if sync_policy == SyncPolicy.FOLLOW.value:
            detail = account_label or "网页登录已经接通，运行时请求会持续跟随本机登录源。"
        elif sync_policy == SyncPolicy.IMPORT_COPY.value:
            detail = account_label or "网页登录已经接通，当前使用的是导入的认证副本。"
        else:
            detail = account_label or "网页登录已经接通。"
        return (
            AuthStatus.CONNECTED,
            "网页登录已连接",
            detail + switch_notice,
        )
    if bool(binding_meta.get("awaiting_local_sync")):
        return (
            AuthStatus.CONNECTING,
            "等待本机登录同步",
            "网页登录已经完成，请在检测到本机登录状态后重新检查。",
        )
    return AuthStatus.EXPIRED, "网页登录需要处理", "关联的登录源缺失或已过期，请重新登录。"


def _session_status(
    profile: Dict[str, Any],
    credential_store: CredentialStore,
    local_status: Dict[str, Any],
) -> tuple[AuthStatus, str, str]:
    ref = str(profile.get("credential_ref") or "").strip()
    binding = dict(profile.get("binding") or {})
    sync_state = build_local_sync_state(profile, local_status)
    follow_local = bool(binding.get("follow_local_auth")) or str(
        binding.get("sync_policy") or SyncPolicy.MANUAL.value
    ).strip().lower() == SyncPolicy.FOLLOW.value
    if follow_local:
        source_error = str(sync_state.get("source_error") or "").strip()
        if source_error:
            return (
                AuthStatus.ERROR,
                "本机会话不可用",
                str(sync_state.get("source_message") or source_error).strip()
                or "无法读取关联的本机浏览器或应用会话。",
            )
        if bool(local_status.get("detected") or local_status.get("configured")):
            binding_meta = dict(binding.get("metadata") or {})
            account_label = _get_account_display(
                local_status.get("account_email"),
                binding_meta.get("account_email"),
                local_status.get("account_label"),
                binding.get("account_label"),
            )
            return (
                AuthStatus.FOLLOWING_LOCAL_AUTH,
                "正在跟随本机会话",
                account_label or "当前项目正在跟随可同步的本机浏览器或应用会话。",
            )
        return (
            AuthStatus.EXPIRED,
            "本机会话已丢失",
            "关联的本机浏览器或应用会话已经不可用。",
        )
    lookup = credential_store.lookup(ref) if ref else None
    if lookup and lookup.readable:
        return AuthStatus.IMPORTED, "会话已导入", "这家服务方当前使用的是一份导入的浏览器或应用会话。"
    if lookup and lookup.exists:
        return AuthStatus.INVALID, "会话需要重新导入", "这份已导入的会话无法读取，请重新导入或重新连接这家服务方。"
    return AuthStatus.INVALID, "会话不可用", "请导入一份有效会话，或重新连接这家服务方。"


def _pending_summary(method) -> tuple[str, str]:
    if method.type is AuthMethodType.OAUTH:
        return "等待网页登录完成", "先登录，再回来检查。"
    if method.type is AuthMethodType.LOCAL_IMPORT:
        return "等待检测本机登录", "先在服务方完成登录。"
    if method.type is AuthMethodType.WEB_SESSION:
        return "等待会话登录完成", "先登录，再导入或同步。"
    return "等待连接完成", "先完成连接，再回来检查。"


def _placeholder_status(method, local_status: Dict[str, Any], pending_flow: bool) -> tuple[AuthStatus, str, str]:
    local_error = str(local_status.get("error") or "").strip()
    if local_error:
        return (
            AuthStatus.ERROR,
            "本机登录源无法读取",
            str(local_status.get("message") or local_error).strip() or "无法读取本机登录源。",
        )
    if pending_flow:
        summary, detail = _pending_summary(method)
        return AuthStatus.CONNECTING, summary, detail
    if method.supports_local_discovery and bool(local_status.get("detected") or local_status.get("configured")):
        if method.supports_follow_mode:
            detail = "检测到本机登录，可直接同步。"
        else:
            detail = "检测到本机登录，可导入副本。"
        return AuthStatus.AVAILABLE_TO_IMPORT, "可同步", detail
    if method.type is AuthMethodType.API_KEY:
        return AuthStatus.NOT_CONFIGURED, "API Key 未配置", "填入 API Key 后即可使用。"
    if method.type is AuthMethodType.WEB_SESSION:
        return AuthStatus.NOT_CONFIGURED, "登录会话未配置", "导入会话后即可使用。"
    return AuthStatus.NOT_CONFIGURED, "未配置", "先接通这项认证。"


def _action_label(action_id: str, method) -> str:
    if action_id == "refresh_status":
        return "重新检查"
    if action_id == "set_default_profile":
        return "设为默认认证"
    if action_id == "test_profile":
        return "测试连接"
    if action_id == "disconnect_profile":
        return "移除当前认证"
    if action_id == "logout_source":
        return "退出本机登录"
    if action_id == "show_api_key_form":
        return "配置 API Key"
    if action_id == "show_session_form":
        return "导入会话"
    if action_id == "bind_local_auth":
        return str(getattr(method, "follow_label", "") or "").strip() or "同步本机登录"
    if action_id == "import_local_auth_copy":
        return str(getattr(method, "import_label", "") or "").strip() or "导入认证副本"
    if action_id == "start_browser_auth":
        return str(getattr(method, "connect_label", "") or "").strip() or "前往登录页"
    if action_id == "complete_browser_auth":
        return "我已登录，继续"
    return action_id


def _action_item(action_id: str, method) -> Dict[str, Any]:
    kind = "invoke"
    if action_id == "refresh_status":
        kind = "refresh"
    elif action_id in {"show_api_key_form", "show_session_form"}:
        kind = "expand"
    return {
        "id": action_id,
        "kind": kind,
        "label": _action_label(action_id, method),
        "danger": action_id in {"disconnect_profile", "logout_source"},
    }


def _supports_import_copy_action(method) -> bool:
    if not bool(method.supports_import_copy):
        return False
    if method.type is AuthMethodType.WEB_SESSION and not bool(method.runtime_supported):
        return False
    return bool(get_method_auth_provider_id(method))


def _actions_for_state(
    status: AuthStatus,
    method,
    *,
    has_profile: bool,
    local_available: bool,
    runtime_ready: bool = True,
    binding: CredentialBinding | None = None,
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = [_action_item("refresh_status", method)]
    import_copy_action_available = _supports_import_copy_action(method)
    if has_profile:
        if method.type is AuthMethodType.API_KEY:
            actions.append(_action_item("show_api_key_form", method))
        elif method.type is AuthMethodType.WEB_SESSION:
            actions.append(_action_item("show_session_form", method))
            if method.supports_browser_flow:
                actions.append(_action_item("start_browser_auth", method))
        elif method.supports_browser_flow and method.type in {AuthMethodType.OAUTH, AuthMethodType.LOCAL_IMPORT}:
            actions.append(_action_item("start_browser_auth", method))
        follow_mode = bool(binding and binding.follow_local_auth)
        import_copy_mode = bool(binding and binding.sync_policy is SyncPolicy.IMPORT_COPY)
        if local_available and follow_mode and import_copy_action_available:
            actions.append(_action_item("import_local_auth_copy", method))
        if local_available and import_copy_mode and method.supports_follow_mode:
            actions.append(_action_item("bind_local_auth", method))
        actions.append(_action_item("set_default_profile", method))
        if method.runtime_supported and runtime_ready:
            actions.append(_action_item("test_profile", method))
        actions.append(_action_item("disconnect_profile", method))
        allow_source_logout = bool(
            method.metadata.get(
                "supports_source_logout",
                method.type in {AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH},
            )
        )
        if allow_source_logout:
            actions.append(_action_item("logout_source", method))
        return actions
    if method.type is AuthMethodType.API_KEY:
        return actions + [_action_item("show_api_key_form", method)]
    if method.type is AuthMethodType.WEB_SESSION:
        if local_available:
            actions.append(_action_item("bind_local_auth", method))
        return actions + [_action_item("show_session_form", method), _action_item("start_browser_auth", method)]
    if local_available:
        actions.append(_action_item("bind_local_auth", method))
        if import_copy_action_available:
            actions.append(_action_item("import_local_auth_copy", method))
    if method.supports_browser_flow:
        actions.append(_action_item("start_browser_auth", method))
    return actions


def _method_label(definition, method_id: str) -> str:
    wanted = str(method_id or "").strip()
    for method in definition.auth_methods:
        if method.id == wanted:
            return method.label
    return wanted


def _build_provider_counts(auth_states: List[AuthStateSnapshot]) -> Dict[str, int]:
    return {
        "connected": sum(1 for item in auth_states if item.status in _READY_STATUSES),
        "attention": sum(1 for item in auth_states if item.status in _ATTENTION_STATUSES),
        "local_ready": sum(
            1 for item in auth_states if item.status in {AuthStatus.AVAILABLE_TO_IMPORT, AuthStatus.FOLLOWING_LOCAL_AUTH}
        ),
    }


def _build_provider_sync_summary(definition, auth_states: List[AuthStateSnapshot]) -> Dict[str, Any]:
    if not (
        definition.capability.supports_local_auth_import
        or definition.capability.supports_credential_follow_mode
    ):
        return {
            "code": "unsupported",
            "checked_at": 0,
            "changed_at": 0,
            "watch_mode": "",
            "method_id": "",
            "method_label": "",
            "account_label": "",
            "account_email": "",
            "detected": False,
            "configured": False,
            "account_switched": False,
            "source_error": "",
            "source_message": "",
            "follow_mode": False,
        }

    candidates: List[tuple[AuthStateSnapshot, Dict[str, Any]]] = []
    for state in auth_states:
        local_sync = dict(state.metadata.get("local_sync") or {})
        follow_mode = bool(state.binding and state.binding.follow_local_auth)
        if not local_sync and not follow_mode:
            continue
        candidates.append((state, local_sync))

    if not candidates:
        return {
            "code": "not_detected",
            "checked_at": 0,
            "changed_at": 0,
            "watch_mode": "",
            "method_id": "",
            "method_label": "",
            "account_label": "",
            "account_email": "",
            "detected": False,
            "configured": False,
            "account_switched": False,
            "source_error": "",
            "source_message": "",
            "follow_mode": False,
        }

    def _sort_key(item: tuple[AuthStateSnapshot, Dict[str, Any]]) -> tuple[int, int, int, int]:
        state, local_sync = item
        return (
            0 if state.default_selected else 1,
            0 if (state.binding and state.binding.follow_local_auth) or state.status is AuthStatus.FOLLOWING_LOCAL_AUTH else 1,
            0 if str(local_sync.get("source_error") or "").strip() else 1,
            -int(local_sync.get("last_checked_at") or 0),
        )

    state, local_sync = sorted(candidates, key=_sort_key)[0]
    follow_mode = bool(state.binding and state.binding.follow_local_auth) or state.status is AuthStatus.FOLLOWING_LOCAL_AUTH
    source_error = str(local_sync.get("source_error") or "").strip()
    detected = bool(local_sync.get("detected"))
    configured = bool(local_sync.get("configured"))
    if source_error:
        code = "error"
    elif follow_mode and (detected or configured):
        code = "following_local_auth"
    elif detected or configured:
        code = "available_to_import"
    else:
        code = "not_detected"
    return {
        "code": code,
        "checked_at": int(local_sync.get("last_checked_at") or 0),
        "changed_at": int(local_sync.get("changed_at") or 0),
        "watch_mode": str(local_sync.get("watch_mode") or "").strip(),
        "method_id": state.method_id,
        "method_label": _method_label(definition, state.method_id),
        "account_label": _get_account_display(
            local_sync.get("account_email"),
            local_sync.get("account_label"),
            state.account_email,
            state.account_label,
        ),
        "account_email": _get_account_display(local_sync.get("account_email"), state.account_email),
        "detected": detected,
        "configured": configured,
        "account_switched": bool(local_sync.get("account_switched")),
        "source_error": source_error,
        "source_message": str(local_sync.get("source_message") or "").strip(),
        "follow_mode": follow_mode,
    }


def _build_provider_health_summary(definition, auth_states: List[AuthStateSnapshot]) -> Dict[str, Any]:
    runtime_states = [item for item in auth_states if item.runtime_supported]
    if not runtime_states:
        return {
            "code": "unsupported",
            "checked_at": 0,
            "method_id": "",
            "method_label": "",
            "message": "",
            "error_code": "",
            "default_selected": False,
        }

    selected_state = next((item for item in runtime_states if item.default_selected), None)
    runtime_ready_states = [item for item in runtime_states if item.metadata.get("runtime_ready", True)]
    checked_states = [item for item in runtime_ready_states if item.health.checked_at]
    preferred = next((item for item in checked_states if item.default_selected), None)
    if preferred is None and checked_states:
        preferred = max(checked_states, key=lambda item: item.health.checked_at)

    if preferred is not None:
        return {
            "code": "healthy" if preferred.health.ok else "warning",
            "checked_at": int(preferred.health.checked_at or 0),
            "method_id": preferred.method_id,
            "method_label": _method_label(definition, preferred.method_id),
            "message": str(preferred.health.message or preferred.health.state or "").strip(),
            "error_code": str(preferred.health.error_code or "").strip(),
            "default_selected": bool(preferred.default_selected),
        }

    if selected_state is not None and not selected_state.metadata.get("runtime_ready", True):
        code = "blocked"
        message = str(selected_state.metadata.get("runtime_unavailable_reason") or "").strip()
    elif selected_state is not None and selected_state.status in _READY_STATUSES:
        code = "not_checked"
        message = ""
    elif selected_state is not None and selected_state.requires_attention:
        code = "attention"
        message = ""
    else:
        code = "idle"
        message = ""
    return {
        "code": code,
        "checked_at": 0,
        "method_id": selected_state.method_id if selected_state else "",
        "method_label": _method_label(definition, selected_state.method_id) if selected_state else "",
        "message": message,
        "error_code": "",
        "default_selected": bool(selected_state.default_selected) if selected_state else False,
    }


def build_provider_overview_cards(
    config: Dict[str, Any],
    *,
    credential_store: CredentialStore | None = None,
    assume_normalized: bool = False,
) -> List[ProviderOverviewCard]:
    store = credential_store or get_credential_store()
    normalized = config if assume_normalized else ensure_provider_auth_center_config(config, credential_store=store)
    center = dict(((normalized.get("api") or {}).get("provider_auth_center") or {}))
    provider_entries = dict(center.get("providers") or {})
    active_provider_id = str(center.get("active_provider_id") or "").strip().lower()
    legacy_statuses = get_legacy_status_map()
    cards: List[ProviderOverviewCard] = []
    for provider_id in sorted(provider_entries.keys()):
        definition = get_provider_definition(provider_id)
        if definition is None:
            continue
        entry = dict(provider_entries.get(provider_id) or {})
        active_profile, _ = _select_runtime_profile(entry)
        can_set_active_provider = active_profile is not None
        profiles = [dict(item) for item in entry.get("auth_profiles") or [] if isinstance(item, dict)]
        selected_profile_id = str(entry.get("selected_profile_id") or "").strip()
        pending_flows = dict((entry.get("metadata") or {}).get("pending_flows") or {})
        auth_states: List[AuthStateSnapshot] = []
        for method in definition.auth_methods:
            local_status = get_method_local_status(method, legacy_statuses)
            method_profiles = [
                profile for profile in profiles if str(profile.get("method_id") or "").strip() == method.id
            ]
            if method_profiles:
                for profile in method_profiles:
                    binding = dict(profile.get("binding") or {})
                    profile_metadata = dict(profile.get("metadata") or {})
                    sync_state = build_local_sync_state(profile, local_status)
                    source_group = _build_source_group(
                        definition,
                        method,
                        local_status=local_status,
                        binding=binding,
                        sync_state=sync_state,
                        profile_id=str(profile.get("id") or "").strip(),
                    )
                    runtime_ready, runtime_unavailable_reason = _resolve_runtime_readiness(
                        entry,
                        method,
                        profile,
                        local_status,
                    )
                    runtime_defaults = _resolve_method_runtime_defaults(entry, method, profile_metadata)
                    if not binding.get("locator_path"):
                        binding["locator_path"] = extract_locator_path(local_status)
                    binding.setdefault("metadata", {})
                    binding["metadata"]["local_sync"] = sync_state
                    for meta_key in (
                        "local_storage_kind",
                        "browser_name",
                        "browser_profile",
                        "keychain_provider",
                        "keychain_locator",
                        "managed_settings_path",
                        "cookie_path",
                        "indexeddb_path",
                        "local_storage_path",
                        "private_storage_path",
                        "private_auth_file_path",
                    ):
                        value = str(local_status.get(meta_key) or "").strip()
                        if value and not str(binding["metadata"].get(meta_key) or "").strip():
                            binding["metadata"][meta_key] = value
                    if local_status.get("keychain_targets") and not binding["metadata"].get("keychain_targets"):
                        binding["metadata"]["keychain_targets"] = [
                            str(item).strip()
                            for item in (local_status.get("keychain_targets") or [])
                            if str(item).strip()
                        ]
                    if local_status.get("cookie_count") is not None and "cookie_count" not in binding["metadata"]:
                        binding["metadata"]["cookie_count"] = int(local_status.get("cookie_count") or 0)
                    if local_status.get("auth_cookie_count") is not None and "auth_cookie_count" not in binding["metadata"]:
                        binding["metadata"]["auth_cookie_count"] = int(local_status.get("auth_cookie_count") or 0)
                    if local_status.get("watch_paths") and not binding["metadata"].get("watch_paths"):
                        binding["metadata"]["watch_paths"] = [
                            str(item).strip()
                            for item in (local_status.get("watch_paths") or [])
                            if str(item).strip()
                        ]
                    if local_status.get("account_email") and not binding["metadata"].get("account_email"):
                        binding["metadata"]["account_email"] = str(local_status.get("account_email") or "").strip()
                    health = _build_health(dict(profile.get("metadata") or {}).get("health"))
                    if method.type is AuthMethodType.API_KEY:
                        status, summary, detail = _api_key_status(profile, store)
                    elif method.type in {AuthMethodType.LOCAL_IMPORT, AuthMethodType.OAUTH}:
                        status, summary, detail = _local_or_oauth_status(method.type, profile, local_status, store)
                    else:
                        status, summary, detail = _session_status(profile, store, local_status)
                    binding_object = _build_binding(binding)
                    if health.error_code in {"expired"}:
                        status = AuthStatus.EXPIRED
                    elif health.error_code and not health.ok and status not in {AuthStatus.EXPIRED, AuthStatus.INVALID}:
                        status = AuthStatus.ERROR
                    action_items = _actions_for_state(
                        status,
                        method,
                        has_profile=True,
                        local_available=bool(local_status.get("detected") or local_status.get("configured")),
                        runtime_ready=runtime_ready,
                        binding=binding_object,
                    )
                    auth_states.append(
                        AuthStateSnapshot(
                            provider_id=provider_id,
                            method_id=method.id,
                            status=status,
                            summary=summary,
                            detail=detail,
                            account_label=_get_account_display(
                                binding["metadata"].get("account_email"),
                                binding.get("account_label"),
                                local_status.get("account_email"),
                                local_status.get("account_label"),
                                profile.get("label"),
                            ),
                            account_email=_get_account_display(
                                binding["metadata"].get("account_email"),
                                local_status.get("account_email"),
                            ),
                            default_selected=str(profile.get("id") or "").strip() == selected_profile_id,
                            available_actions=[item["id"] for item in action_items],
                            actions=action_items,
                            health=health,
                            binding=binding_object,
                            has_secret=store.has(str(profile.get("credential_ref") or "").strip()),
                            requires_attention=status in {AuthStatus.EXPIRED, AuthStatus.INVALID, AuthStatus.ERROR},
                            experimental=bool(method.experimental),
                            runtime_supported=bool(method.runtime_supported),
                            metadata={
                                "profile_id": str(profile.get("id") or "").strip(),
                                "model": runtime_defaults["model"],
                                "base_url": runtime_defaults["base_url"],
                                "local_sync": sync_state,
                                "runtime_ready": runtime_ready,
                                "runtime_unavailable_reason": runtime_unavailable_reason,
                                "source_group": source_group,
                            },
                        )
                    )
            else:
                status, summary, detail = _placeholder_status(
                    method,
                    local_status,
                    pending_flow=bool(pending_flows.get(method.id)),
                )
                runtime_ready, runtime_unavailable_reason = _resolve_runtime_readiness(
                    entry,
                    method,
                    None,
                    local_status,
                )
                runtime_defaults = _resolve_method_runtime_defaults(entry, method)
                action_items = _actions_for_state(
                    status,
                    method,
                    has_profile=False,
                    local_available=bool(local_status.get("detected") or local_status.get("configured")),
                    runtime_ready=runtime_ready,
                )
                if bool(pending_flows.get(method.id)) and method.supports_browser_flow:
                    action_items.append(_action_item("complete_browser_auth", method))
                sync_state = build_local_sync_state({"binding": {}}, local_status)
                credential_source = (
                    CredentialSource.SYSTEM_KEYCHAIN.value
                    if local_status.get("keychain_targets")
                    else (
                        CredentialSource.BROWSER_SESSION.value
                        if method.type is AuthMethodType.WEB_SESSION
                        else CredentialSource.LOCAL_CONFIG_FILE.value
                    )
                )
                auth_states.append(
                    AuthStateSnapshot(
                        provider_id=provider_id,
                        method_id=method.id,
                        status=status,
                        summary=summary,
                        detail=detail,
                        account_label=_get_account_display(
                            local_status.get("account_email"),
                            local_status.get("account_label"),
                        ),
                        account_email=_get_account_display(local_status.get("account_email")),
                        default_selected=False,
                        available_actions=[item["id"] for item in action_items],
                        actions=action_items,
                        binding=_build_binding(
                            {
                                "source": str(local_status.get("local_source_label") or method.id).strip(),
                                "source_type": str(get_method_auth_provider_id(method) or method.type.value).strip(),
                                "credential_source": credential_source,
                                "sync_policy": SyncPolicy.FOLLOW.value if method.supports_follow_mode else SyncPolicy.MANUAL.value,
                                "follow_local_auth": bool(method.supports_follow_mode),
                                "locator_path": extract_locator_path(local_status),
                                "account_label": str(local_status.get("account_label") or "").strip(),
                                "metadata": {
                                    "account_email": str(local_status.get("account_email") or "").strip(),
                                    "local_sync": sync_state,
                                    "local_storage_kind": str(local_status.get("local_storage_kind") or "").strip(),
                                    "browser_name": str(local_status.get("browser_name") or "").strip(),
                                    "browser_profile": str(local_status.get("browser_profile") or "").strip(),
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
                                },
                            }
                        )
                        if status is AuthStatus.AVAILABLE_TO_IMPORT
                        else None,
                        has_secret=False,
                        requires_attention=status in {AuthStatus.EXPIRED, AuthStatus.INVALID, AuthStatus.ERROR},
                        experimental=bool(method.experimental),
                        runtime_supported=bool(method.runtime_supported),
                        metadata={
                            "pending_flow": dict(pending_flows.get(method.id) or {}),
                            "model": runtime_defaults["model"],
                            "base_url": runtime_defaults["base_url"],
                            "local_sync": sync_state,
                            "runtime_ready": runtime_ready,
                            "runtime_unavailable_reason": runtime_unavailable_reason,
                            "source_group": _build_source_group(
                                definition,
                                method,
                                local_status=local_status,
                                binding={
                                    "metadata": {
                                        "account_email": str(local_status.get("account_email") or "").strip(),
                                    }
                                },
                                sync_state=sync_state,
                                placeholder=True,
                            ),
                        },
                    )
                )
        selected_state = next((item for item in auth_states if item.default_selected), None)
        best_state = min(auth_states, key=lambda item: _CARD_RANK.get(item.status, 99)) if auth_states else None
        display_state = selected_state or best_state
        provider_state = display_state.status if display_state else AuthStatus.NOT_CONFIGURED
        summary = display_state.summary if display_state else "未配置"
        detail = display_state.detail if display_state else ""
        sort_order = _CARD_RANK.get(provider_state, 99)
        if provider_id == active_provider_id:
            sort_order -= 1
            summary = f"当前回复服务方 · {summary}"
        selected_profile = next(
            (dict(item) for item in profiles if str(item.get("id") or "").strip() == selected_profile_id),
            {},
        )
        selected_method = None
        if selected_profile:
            for method in definition.auth_methods:
                if method.id == str(selected_profile.get("method_id") or "").strip():
                    selected_method = method
                    break
        provider_counts = _build_provider_counts(auth_states)
        provider_sync = _build_provider_sync_summary(definition, auth_states)
        provider_health = _build_provider_health_summary(definition, auth_states)
        runtime_unavailable_reason = ""
        if not can_set_active_provider and selected_profile and selected_method is not None:
            _, runtime_unavailable_reason = _resolve_runtime_readiness(
                entry,
                selected_method,
                selected_profile,
                get_method_local_status(selected_method, legacy_statuses),
            )
        cards.append(
            ProviderOverviewCard(
                provider=definition,
                state=provider_state,
                summary=summary,
                detail=detail,
                sort_order=sort_order,
                selected_profile_id=selected_profile_id,
                selected_method_id=str(selected_profile.get("method_id") or "").strip(),
                selected_method_type=str(selected_profile.get("method_type") or "").strip(),
                selected_label=_get_account_display(
                    getattr(selected_state, "account_email", ""),
                    getattr(selected_state, "account_label", ""),
                    dict((selected_profile.get("binding") or {}).get("metadata") or {}).get("account_email"),
                    selected_profile.get("label"),
                ),
                auth_states=auth_states,
                actions=[
                    {"id": "set_active_provider", "label": "设为当前回复模型", "disabled": not can_set_active_provider},
                    {"id": "update_provider_defaults", "label": "保存模型配置"},
                    {"id": "refresh_status", "label": "重新检查"},
                ],
                metadata={
                    "is_active_provider": provider_id == active_provider_id,
                    "can_set_active_provider": can_set_active_provider,
                    "active_provider_reason": (
                        ""
                        if can_set_active_provider
                        else (
                            runtime_unavailable_reason
                            or "请先配置一组支持运行时调用的认证，再把这家服务方设为当前回复模型。"
                        )
                    ),
                    "legacy_preset_name": str(entry.get("legacy_preset_name") or "").strip(),
                    "default_model": str(entry.get("default_model") or "").strip(),
                    "default_base_url": str(entry.get("default_base_url") or "").strip(),
                    "alias": str(entry.get("alias") or "").strip(),
                    **{
                        field_name: str(value or "").strip()
                        for field_name, value in _collect_runtime_metadata_values(entry, provider_id=provider_id).items()
                    },
                    **{
                        field_name: ""
                        for field_name in get_provider_required_fields(provider_id)
                        if field_name not in _collect_runtime_metadata_values(entry, provider_id=provider_id)
                    },
                    "provider_counts": provider_counts,
                    "provider_sync": provider_sync,
                    "provider_health": provider_health,
                },
            )
        )
    return sorted(cards, key=lambda item: (item.sort_order, item.provider.label.lower()))
