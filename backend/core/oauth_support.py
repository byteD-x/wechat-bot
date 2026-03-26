from __future__ import annotations

from .auth import (
    AuthSupportError as OAuthSupportError,
    ResolvedAuthSettings as ResolvedOAuthSettings,
    cancel_auth_flow,
    get_auth_provider as get_oauth_provider,
    get_auth_provider_statuses as get_oauth_provider_statuses,
    get_preset_auth_summary,
    get_supported_auth_provider_ids as get_supported_oauth_provider_ids,
    infer_auth_provider_id as infer_oauth_provider_id,
    launch_auth_flow,
    logout_auth_provider as logout_oauth_provider,
    normalize_auth_mode,
    resolve_auth_settings,
    submit_auth_callback,
)


def resolve_oauth_settings(settings):
    return resolve_auth_settings(settings)


def launch_oauth_login(provider_key, settings=None):
    return launch_auth_flow(provider_key, settings=settings)
