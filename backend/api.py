"""
Quart API service for the desktop app.

This module exposes bot control, runtime status, configuration management,
and operational endpoints used by the Electron renderer process.
"""

from quart import Quart, jsonify, request, make_response
import json
import logging
import os
import asyncio
import ipaddress
import re
import secrets
import hashlib
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from werkzeug.exceptions import HTTPException

from .bot_manager import get_bot_manager
from .growth_manager import get_growth_manager
from backend.core.config_audit import (
    build_config_audit,
    build_reload_plan,
    diff_config_paths,
    get_effect_for_path,
)
from backend.core.config_probe import probe_config
from backend.core.config_service import get_config_service
from backend.core.cost_analytics import CostAnalyticsService
from backend.core.data_controls import DataControlService
from backend.core.oauth_support import (
    OAuthSupportError,
    cancel_auth_flow,
    get_cached_oauth_provider_statuses,
    get_oauth_provider_statuses,
    get_preset_auth_summary,
    infer_oauth_provider_id,
    launch_oauth_login,
    logout_oauth_provider,
    submit_auth_callback,
)
from backend.core.readiness import readiness_service
from backend.core.reply_quality_tracker import close_reply_quality_tracker
from backend.core.reply_policy import normalize_reply_policy, update_per_chat_override
from backend.core.workspace_backup import (
    DEFAULT_KEEP_FULL_BACKUPS,
    DEFAULT_KEEP_QUICK_BACKUPS,
    WorkspaceBackupService,
)
from backend.core.wechat_export_service import WechatExportService
from backend.model_catalog import (
    get_model_catalog,
    infer_provider_id,
    merge_provider_defaults,
)
from backend.model_auth.services import get_model_auth_center_service
from backend.shared_config import ensure_data_root, get_app_config_path, get_project_root
from backend.utils.logging import (
    setup_logging,
    get_logging_settings,
    configure_http_access_log_filters,
)
from backend.utils.config import extract_editable_system_prompt, resolve_system_prompt

# runtime config service
config_service = get_config_service()
_initial_snapshot = config_service.get_snapshot()
level, log_file, max_bytes, backup_count, format_type = get_logging_settings(
    _initial_snapshot.config
)
setup_logging(level, log_file, max_bytes, backup_count, format_type)

logger = logging.getLogger(__name__)

API_TOKEN = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()
SSE_TICKET = str(os.environ.get("WECHAT_BOT_SSE_TICKET") or "").strip()
configure_http_access_log_filters()
MAX_LOG_LINES = 2000
MAX_SEND_TARGET_CHARS = 256
MAX_SEND_CONTENT_CHARS = 8000
IDEMPOTENCY_CACHE_TTL_SEC = 300
IDEMPOTENCY_CACHE_MAX_ENTRIES = 1024
IDEMPOTENCY_INFLIGHT_WAIT_SEC = 30

_REMOVED_PUBLIC_BOT_FIELDS = {
    "reply_timeout_fallback_text",
    "stream_buffer_chars",
    "stream_chunk_max_chars",
    "stream_reply",
}

_REMOVED_PUBLIC_AGENT_FIELDS = {
    "streaming_enabled",
}

_MODEL_AUTH_SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "password",
    "credential",
    "helper",
    "command",
    "api_key",
)

_IDEMPOTENT_ENDPOINTS = {
    ("POST", "/api/send"),
    ("POST", "/api/restart"),
    ("POST", "/api/backups"),
    ("POST", "/api/backups/restore"),
    ("POST", "/api/data_controls/clear"),
}

_IDEMPOTENCY_CACHE: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_INFLIGHT: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_LOCK = asyncio.Lock()

_API_METRICS_COUNTERS: dict[tuple[str, str, str], int] = {}
_API_METRICS_DURATION_SUM_MS: dict[tuple[str, str], float] = {}
_API_METRICS_DURATION_COUNT: dict[tuple[str, str], int] = {}
_API_AUTH_FAILURE_COUNTERS: dict[tuple[str, str], int] = {}
_API_METRIC_MAX_PATH_CARDINALITY = 256
_API_METRIC_TRACKED_PATHS: set[str] = set()
_API_METRIC_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/growth/tasks/[^/]+/(clear|run|pause|resume)$"), "/api/growth/tasks/{task}/{action}"),
    (re.compile(r"^/api/pending_replies/[^/]+/(approve|reject)$"), "/api/pending_replies/{id}/{action}"),
]


def _normalize_metric_path(path: str) -> str:
    normalized = str(path or "").strip() or "/"
    for pattern, replacement in _API_METRIC_PATH_PATTERNS:
        if pattern.match(normalized):
            return replacement
    return normalized


def _bound_metric_path(path: str) -> str:
    normalized = _normalize_metric_path(path)
    if normalized in _API_METRIC_TRACKED_PATHS:
        return normalized
    if len(_API_METRIC_TRACKED_PATHS) >= _API_METRIC_MAX_PATH_CARDINALITY:
        return "/api/_other"
    _API_METRIC_TRACKED_PATHS.add(normalized)
    return normalized


def _increment_api_counter(method: str, path: str, status: int) -> None:
    key = (str(method or "GET").upper(), _bound_metric_path(path), str(int(status or 0)))
    _API_METRICS_COUNTERS[key] = int(_API_METRICS_COUNTERS.get(key, 0)) + 1


def _observe_api_duration(method: str, path: str, duration_ms: float) -> None:
    metric_key = (str(method or "GET").upper(), _bound_metric_path(path))
    _API_METRICS_DURATION_SUM_MS[metric_key] = float(_API_METRICS_DURATION_SUM_MS.get(metric_key, 0.0)) + float(duration_ms)
    _API_METRICS_DURATION_COUNT[metric_key] = int(_API_METRICS_DURATION_COUNT.get(metric_key, 0)) + 1


def _record_api_auth_failure(reason: str, path: str) -> None:
    key = (str(reason or "unknown").strip() or "unknown", _bound_metric_path(path))
    _API_AUTH_FAILURE_COUNTERS[key] = int(_API_AUTH_FAILURE_COUNTERS.get(key, 0)) + 1


def _render_additional_api_metrics() -> str:
    lines: list[str] = []
    lines.append("# HELP wechat_api_requests_total Total API requests by method/path/status.")
    lines.append("# TYPE wechat_api_requests_total counter")
    for (method, path, status), count in sorted(_API_METRICS_COUNTERS.items()):
        lines.append(
            f'wechat_api_requests_total{{method="{method}",path="{path}",status="{status}"}} {int(count)}'
        )

    lines.append("# HELP wechat_api_request_duration_ms_sum Cumulative API request duration in milliseconds.")
    lines.append("# TYPE wechat_api_request_duration_ms_sum counter")
    for (method, path), total_ms in sorted(_API_METRICS_DURATION_SUM_MS.items()):
        lines.append(
            f'wechat_api_request_duration_ms_sum{{method="{method}",path="{path}"}} {float(total_ms):.3f}'
        )

    lines.append("# HELP wechat_api_request_duration_ms_count Number of API requests observed for duration.")
    lines.append("# TYPE wechat_api_request_duration_ms_count counter")
    for (method, path), count in sorted(_API_METRICS_DURATION_COUNT.items()):
        lines.append(
            f'wechat_api_request_duration_ms_count{{method="{method}",path="{path}"}} {int(count)}'
        )

    lines.append("# HELP wechat_api_auth_failures_total API auth/origin failures by reason and path.")
    lines.append("# TYPE wechat_api_auth_failures_total counter")
    for (reason, path), count in sorted(_API_AUTH_FAILURE_COUNTERS.items()):
        lines.append(
            f'wechat_api_auth_failures_total{{reason="{reason}",path="{path}"}} {int(count)}'
        )

    lines.append("# HELP wechat_api_token_missing Whether API token is currently missing (1=yes,0=no).")
    lines.append("# TYPE wechat_api_token_missing gauge")
    lines.append(f"wechat_api_token_missing {1 if not API_TOKEN else 0}")
    return "\n".join(lines)


def _extract_idempotency_key(data: dict | None) -> str:
    header_key = str(request.headers.get("Idempotency-Key") or "").strip()
    body_key = ""
    if isinstance(data, dict):
        body_key = str(data.get("_idempotency_key") or "").strip()
    key = header_key or body_key
    if not key:
        return ""
    if len(key) > 128:
        raise ValueError("idempotency key is too long")
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
        raise ValueError("idempotency key format is invalid")
    return key


def _strip_internal_idempotency_key(data: dict | None) -> dict:
    payload = dict(data or {})
    payload.pop("_idempotency_key", None)
    return payload


def _build_idempotency_fingerprint(method: str, path: str, payload: dict | None) -> str:
    canonical = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{method.upper()}|{path}|{canonical}".encode("utf-8")).hexdigest()


def _build_idempotency_cache_key(method: str, path: str, idempotency_key: str) -> str:
    return f"{method.upper()}|{path}|{idempotency_key}"


def _purge_expired_idempotency_cache(now_ts: float) -> None:
    expired_keys = [
        key
        for key, value in _IDEMPOTENCY_CACHE.items()
        if float(value.get("created_at", 0.0)) + IDEMPOTENCY_CACHE_TTL_SEC < now_ts
    ]
    for key in expired_keys:
        _IDEMPOTENCY_CACHE.pop(key, None)

    if len(_IDEMPOTENCY_CACHE) <= IDEMPOTENCY_CACHE_MAX_ENTRIES:
        return
    overflow = len(_IDEMPOTENCY_CACHE) - IDEMPOTENCY_CACHE_MAX_ENTRIES
    for key, _value in sorted(
        _IDEMPOTENCY_CACHE.items(),
        key=lambda item: float(item[1].get("created_at", 0.0)),
    )[:overflow]:
        _IDEMPOTENCY_CACHE.pop(key, None)


async def _get_cached_idempotent_response(
    method: str,
    path: str,
    idempotency_key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None

    cache_key = _build_idempotency_cache_key(method, path, idempotency_key)
    now_ts = time.time()
    async with _IDEMPOTENCY_LOCK:
        _purge_expired_idempotency_cache(now_ts)
        cached = _IDEMPOTENCY_CACHE.get(cache_key)
        if not cached:
            return None
        if str(cached.get("fingerprint") or "") != str(fingerprint or ""):
            raise ValueError("idempotency key was reused with a different request payload")
        return {
            "status": int(cached.get("status") or 200),
            "payload": dict(cached.get("payload") or {}),
        }


async def _store_idempotent_response(
    method: str,
    path: str,
    idempotency_key: str,
    fingerprint: str,
    status_code: int,
    payload: dict[str, Any],
) -> None:
    if not idempotency_key:
        return
    if int(status_code or 500) >= 500:
        return
    cache_key = _build_idempotency_cache_key(method, path, idempotency_key)
    now_ts = time.time()
    async with _IDEMPOTENCY_LOCK:
        _purge_expired_idempotency_cache(now_ts)
        _IDEMPOTENCY_CACHE[cache_key] = {
            "fingerprint": str(fingerprint or ""),
            "status": int(status_code or 200),
            "payload": dict(payload or {}),
            "created_at": now_ts,
        }


async def _reserve_or_wait_idempotency_flow(
    method: str,
    path: str,
    idempotency_key: str,
    fingerprint: str,
) -> dict[str, Any]:
    cache_key = _build_idempotency_cache_key(method, path, idempotency_key)
    wait_event = None
    now_ts = time.time()
    async with _IDEMPOTENCY_LOCK:
        _purge_expired_idempotency_cache(now_ts)
        cached = _IDEMPOTENCY_CACHE.get(cache_key)
        if cached:
            if str(cached.get("fingerprint") or "") != str(fingerprint or ""):
                raise ValueError("idempotency key was reused with a different request payload")
            return {
                "cached": {
                    "status": int(cached.get("status") or 200),
                    "payload": dict(cached.get("payload") or {}),
                }
            }

        inflight = _IDEMPOTENCY_INFLIGHT.get(cache_key)
        if inflight:
            if str(inflight.get("fingerprint") or "") != str(fingerprint or ""):
                raise ValueError("idempotency key was reused with a different request payload")
            wait_event = inflight.get("event")
        else:
            _IDEMPOTENCY_INFLIGHT[cache_key] = {
                "fingerprint": str(fingerprint or ""),
                "event": asyncio.Event(),
            }
            return {"owner": True, "cache_key": cache_key}

    if isinstance(wait_event, asyncio.Event):
        try:
            await asyncio.wait_for(wait_event.wait(), timeout=IDEMPOTENCY_INFLIGHT_WAIT_SEC)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("idempotency request is still in progress") from exc
    cached = await _get_cached_idempotent_response(
        method=method,
        path=path,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if cached is None:
        raise RuntimeError("idempotency replay result unavailable")
    return {"cached": cached}


async def _finish_idempotency_flow(cache_key: str, fingerprint: str) -> None:
    if not cache_key:
        return
    event = None
    async with _IDEMPOTENCY_LOCK:
        inflight = _IDEMPOTENCY_INFLIGHT.get(cache_key)
        if inflight and str(inflight.get("fingerprint") or "") == str(fingerprint or ""):
            event = inflight.get("event")
            _IDEMPOTENCY_INFLIGHT.pop(cache_key, None)
    if isinstance(event, asyncio.Event):
        event.set()


def _json_internal_error(message: str, *, code: str) -> tuple[Any, int]:
    return jsonify({"success": False, "message": message, "code": code}), 500


def _json_operation_result(result: Any, *, failure_status: int = 400):
    payload = result if isinstance(result, dict) else {"success": False, "message": "invalid_result"}
    status = 200
    if payload.get("success") is False:
        status = int(failure_status)
    return jsonify(payload), status


def _token_matches(expected_token: str, provided_token: str) -> bool:
    expected = str(expected_token or "")
    provided = str(provided_token or "")
    if not expected or not provided:
        return False
    return bool(secrets.compare_digest(expected, provided))

def _extract_hostname(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        parsed = urlsplit(candidate)
    except Exception:
        return ""
    return str(parsed.hostname or "").strip().lower().rstrip(".")


def _is_trusted_local_hostname(hostname: str) -> bool:
    normalized = str(hostname or "").strip().lower().rstrip(".")
    if not normalized:
        return False
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_loopback_ip(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_local_request() -> bool:
    try:
        if bool(getattr(app, "config", {}).get("TESTING")):
            return True
    except Exception:
        pass
    try:
        remote_addr = str(getattr(request, "remote_addr", "") or "").strip()
    except Exception:
        remote_addr = ""
    if not remote_addr:
        # Fail closed when transport metadata is unavailable.
        return False
    return _is_loopback_ip(remote_addr)


def _is_trusted_local_origin(origin: str) -> bool:
    normalized = str(origin or "").strip()
    if not normalized:
        return True
    lower = normalized.lower()
    if lower == "null":
        return _is_electron_user_agent()
    try:
        parsed = urlsplit(normalized)
    except Exception:
        return False
    if parsed.scheme == "file":
        return _is_electron_user_agent()
    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_trusted_local_hostname(_extract_hostname(normalized))


def _is_electron_user_agent() -> bool:
    user_agent = str(request.headers.get("User-Agent") or "").strip().lower()
    if not user_agent:
        return False
    return " electron/" in f" {user_agent}" or "electron/" in user_agent


def _is_cross_site_browser_request() -> bool:
    origin = str(request.headers.get("Origin") or "").strip()
    if origin and not _is_trusted_local_origin(origin):
        return True
    fetch_site = str(request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if fetch_site == "cross-site":
        # Electron EventSource requests from local file:// renderer may be marked as
        # cross-site without an Origin header. Treat local Electron requests as trusted.
        if _is_electron_user_agent() and _is_local_request():
            return False
        if origin:
            return not _is_trusted_local_origin(origin)
        return True
    return False


def _extract_request_token() -> str:
    header_token = str(request.headers.get("X-Api-Token") or "").strip()
    if header_token:
        return header_token

    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header:
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            bearer = value.strip()
            if bearer:
                return bearer

    return ""


def _is_idempotent_endpoint(method: str, path: str) -> bool:
    return (str(method or "GET").upper(), str(path or "")) in _IDEMPOTENT_ENDPOINTS


def _is_idempotency_key_required(method: str, path: str) -> bool:
    if not _is_idempotent_endpoint(method, path):
        return False
    return not bool(getattr(app, "config", {}).get("TESTING"))


async def _apply_idempotency_guard(method: str, path: str):
    if not _is_idempotent_endpoint(method, path):
        return None

    data = await request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "request body must be a JSON object"}), 400

    idempotency_key = _extract_idempotency_key(data)
    if not idempotency_key:
        if _is_idempotency_key_required(method, path):
            return jsonify({"success": False, "message": "idempotency_key_required"}), 400
        return None

    payload = _strip_internal_idempotency_key(data)
    fingerprint = _build_idempotency_fingerprint(method, path, payload)
    reservation = await _reserve_or_wait_idempotency_flow(
        method=method,
        path=path,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    cached = reservation.get("cached") if isinstance(reservation, dict) else None
    if cached is not None:
        response = jsonify(cached.get("payload") or {})
        response.status_code = int(cached.get("status") or 200)
        response.headers["X-Idempotency-Replayed"] = "1"
        setattr(request, "_idempotency_replayed", True)
        return response

    setattr(request, "_idempotency_key", idempotency_key)
    setattr(request, "_idempotency_fingerprint", fingerprint)
    if isinstance(reservation, dict) and reservation.get("owner"):
        setattr(request, "_idempotency_owner", True)
        setattr(request, "_idempotency_cache_key", str(reservation.get("cache_key") or ""))
    return None


def _append_vary_header(response, value: str) -> None:
    existing = str(response.headers.get("Vary") or "").strip()
    if not existing:
        response.headers["Vary"] = value
        return
    values = [item.strip() for item in existing.split(",") if item.strip()]
    if value not in values:
        values.append(value)
    response.headers["Vary"] = ", ".join(values)


def _apply_local_api_cors_headers(response, path: str) -> None:
    if not str(path or "").startswith("/api/"):
        return
    for header_name in (
        "Access-Control-Allow-Origin",
        "Access-Control-Allow-Credentials",
        "Access-Control-Allow-Headers",
        "Access-Control-Allow-Methods",
        "Access-Control-Expose-Headers",
    ):
        response.headers.pop(header_name, None)

    origin = str(request.headers.get("Origin") or "").strip()
    if not origin:
        return
    if not _is_trusted_local_origin(origin):
        return
    response.headers["Access-Control-Allow-Origin"] = "null" if origin.lower() == "null" else origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Api-Token, Authorization, Idempotency-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "X-Idempotency-Replayed"
    _append_vary_header(response, "Origin")



# Security note: API is intended for local Electron clients only.
# - Run server defaults bind to 127.0.0.1.
# - When WECHAT_BOT_API_TOKEN is set, all /api/* endpoints require it.


# quart app
app = Quart(__name__)

@app.before_request
async def _refresh_and_enforce_local_api_token():
    # Keep token in sync for long-running debug reloader sessions.
    global API_TOKEN, SSE_TICKET
    API_TOKEN = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()
    SSE_TICKET = str(os.environ.get("WECHAT_BOT_SSE_TICKET") or "").strip()

    path = str(getattr(request, "path", "") or "")
    if not path.startswith("/api/"):
        return None
    try:
        setattr(request, "_api_request_started_at", time.perf_counter())
    except Exception:
        pass

    if not _is_local_request():
        _record_api_auth_failure("forbidden_non_local", path)
        return jsonify({"success": False, "message": "forbidden"}), 403

    if _is_cross_site_browser_request():
        _record_api_auth_failure("forbidden_origin", path)
        return jsonify({"success": False, "message": "forbidden_origin"}), 403

    method = str(getattr(request, "method", "GET") or "GET").upper()
    if method == "OPTIONS":
        return app.response_class("", status=204)
    if not API_TOKEN and not app.config.get("TESTING"):
        _record_api_auth_failure("token_missing", path)
        return jsonify({"success": False, "message": "api_token_not_configured"}), 503

    if path == "/api/events":
        if API_TOKEN:
            if not SSE_TICKET:
                _record_api_auth_failure("sse_ticket_missing", path)
                return jsonify({"success": False, "message": "unauthorized"}), 401
            ticket = str(request.args.get("ticket") or "").strip()
            if not (ticket and secrets.compare_digest(ticket, SSE_TICKET)):
                _record_api_auth_failure("sse_ticket_invalid", path)
                return jsonify({"success": False, "message": "unauthorized"}), 401
    elif path == "/api/events_ticket":
        if API_TOKEN:
            if not SSE_TICKET:
                _record_api_auth_failure("sse_ticket_missing", path)
                return jsonify({"success": False, "message": "unauthorized"}), 401
            if not _token_matches(API_TOKEN, _extract_request_token()):
                _record_api_auth_failure("unauthorized", path)
                return jsonify({"success": False, "message": "unauthorized"}), 401
    else:
        if API_TOKEN and not _token_matches(API_TOKEN, _extract_request_token()):
            _record_api_auth_failure("unauthorized", path)
            return jsonify({"success": False, "message": "unauthorized"}), 401

    try:
        idempotency_response = await _apply_idempotency_guard(method, path)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"success": False, "message": str(e)}), 409
    if idempotency_response is not None:
        return idempotency_response
    return None


@app.after_request
async def _collect_api_metrics(response):
    path = str(getattr(request, "path", "") or "")
    if not path.startswith("/api/"):
        return response
    _apply_local_api_cors_headers(response, path)

    method = str(getattr(request, "method", "GET") or "GET").upper()
    status_code = int(getattr(response, "status_code", 0) or 0)
    _increment_api_counter(method, path, status_code)

    started_at = getattr(request, "_api_request_started_at", None)
    if isinstance(started_at, (int, float)):
        elapsed_ms = max(0.0, (time.perf_counter() - float(started_at)) * 1000.0)
        _observe_api_duration(method, path, elapsed_ms)

    idempotency_owner = bool(getattr(request, "_idempotency_owner", False))
    idempotency_key = str(getattr(request, "_idempotency_key", "") or "").strip()
    fingerprint = str(getattr(request, "_idempotency_fingerprint", "") or "").strip()
    cache_key = str(getattr(request, "_idempotency_cache_key", "") or "").strip()
    try:
        if (
            idempotency_owner
            and _is_idempotent_endpoint(method, path)
            and not bool(getattr(request, "_idempotency_replayed", False))
            and idempotency_key
            and fingerprint
        ):
            try:
                payload = await response.get_json(silent=True)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                await _store_idempotent_response(
                    method=method,
                    path=path,
                    idempotency_key=idempotency_key,
                    fingerprint=fingerprint,
                    status_code=status_code,
                    payload=payload,
                )
    finally:
        if idempotency_owner and cache_key:
            await _finish_idempotency_flow(cache_key, fingerprint)
    return response


@app.errorhandler(404)
async def _handle_api_not_found(error):
    path = str(getattr(request, "path", "") or "")
    if path.startswith("/api/"):
        return jsonify({"success": False, "message": "not_found"}), 404
    return error


@app.errorhandler(405)
async def _handle_api_method_not_allowed(error):
    path = str(getattr(request, "path", "") or "")
    if path.startswith("/api/"):
        return jsonify({"success": False, "message": "method_not_allowed"}), 405
    return error


@app.errorhandler(Exception)
async def _handle_api_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    path = str(getattr(request, "path", "") or "")
    if path.startswith("/api/"):
        logger.exception("Unhandled API error on %s", path)
        return jsonify({"success": False, "message": "internal_server_error"}), 500
    raise error


manager = get_bot_manager()
cost_service = CostAnalyticsService()
backup_service = WorkspaceBackupService()
data_control_service = DataControlService()
wechat_export_service = WechatExportService()
model_auth_center_service = get_model_auth_center_service()
maintenance_lock = asyncio.Lock()


def _mask_preset(
    preset: dict,
    *,
    is_active: bool = False,
    provider_statuses: dict | None = None,
) -> dict:
    masked = merge_provider_defaults(preset)
    masked["provider_id"] = infer_provider_id(
        provider_id=masked.get("provider_id"),
        preset_name=masked.get("name"),
        base_url=masked.get("base_url"),
        model=masked.get("model"),
    )

    key = masked.get("api_key", "")
    credential_ref = str(masked.get("credential_ref") or "").strip()
    allow_empty = bool(masked.get("allow_empty_key", False))
    if allow_empty:
        masked["api_key_configured"] = False
        masked["api_key_masked"] = ""
    elif (key and not key.startswith("YOUR_")) or credential_ref:
        masked["api_key_configured"] = True
        masked["api_key_masked"] = (
            key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        )
    else:
        masked["api_key_configured"] = False
        masked["api_key_masked"] = ""
    masked["api_key_required"] = not allow_empty
    masked["_is_active"] = bool(is_active)
    masked["auth_mode"] = str(masked.get("auth_mode") or "api_key").strip().lower() or "api_key"
    masked["oauth_provider"] = infer_oauth_provider_id(masked)
    auth_summary = get_preset_auth_summary(masked, provider_statuses=provider_statuses)
    masked.update(
        {
            "oauth_supported": bool(auth_summary.get("oauth_supported")),
            "oauth_ready": bool(auth_summary.get("oauth_ready")),
            "api_key_ready": bool(auth_summary.get("api_key_ready")),
            "auth_ready": bool(auth_summary.get("auth_ready")),
            "oauth_status": auth_summary.get("oauth_status"),
            "oauth_source": auth_summary.get("oauth_source") or "",
            "oauth_bound": bool(auth_summary.get("oauth_bound")),
            "oauth_missing_fields": auth_summary.get("oauth_missing_fields") or [],
            "oauth_detected_local": bool(auth_summary.get("oauth_detected_local")),
            "oauth_experimental": bool(auth_summary.get("oauth_experimental")),
            "oauth_requires_ack": bool(auth_summary.get("oauth_requires_ack")),
            "oauth_experimental_ack": bool(auth_summary.get("oauth_experimental_ack")),
            "auth_status_summary": str(auth_summary.get("auth_status_summary") or ""),
            "card_state": str(auth_summary.get("card_state") or ""),
            "card_rank": int(auth_summary.get("card_rank") or 0),
            "card_group": str(auth_summary.get("card_group") or "secondary"),
        }
    )

    masked.pop("api_key", None)
    masked.pop("_is_active", None)
    return masked


def _build_local_auth_sync_state(payload: dict | None) -> dict:
    status = dict(payload or {})
    return {
        "refreshing": bool(status.get("refreshing")),
        "refreshed_at": int(status.get("refreshed_at") or 0),
        "revision": int(status.get("revision") or 0),
        "changed_provider_ids": [
            str(provider_id).strip()
            for provider_id in (status.get("changed_provider_ids") or [])
            if str(provider_id).strip()
        ],
        "message": str(status.get("message") or "").strip(),
    }


def _build_config_payload(snapshot=None) -> dict:
    active_snapshot = snapshot or config_service.get_snapshot()
    config_dict = active_snapshot.config

    api_cfg = config_dict.get("api", {})
    bot_cfg = dict(config_dict.get("bot", {}))
    agent_cfg = dict(config_dict.get("agent", {}))
    active_preset = str(api_cfg.get("active_preset") or "").strip()
    oauth_status = get_cached_oauth_provider_statuses()
    provider_statuses = dict(oauth_status.get("providers") or {})
    presets = []
    for preset in api_cfg.get("presets", []):
        preset_name = str((preset or {}).get("name") or "").strip()
        presets.append(
            _mask_preset(
                preset,
                is_active=(preset_name == active_preset),
                provider_statuses=provider_statuses,
            )
        )

    api_cfg_safe = api_cfg.copy()
    api_cfg_safe["presets"] = presets
    api_cfg_safe["auth_mode"] = str(api_cfg_safe.get("auth_mode") or "api_key").strip().lower() or "api_key"
    api_cfg_safe["oauth_provider"] = infer_oauth_provider_id(api_cfg_safe)
    api_cfg_safe.pop("api_key", None)
    for field in _REMOVED_PUBLIC_BOT_FIELDS:
        bot_cfg.pop(field, None)
    for field in _REMOVED_PUBLIC_AGENT_FIELDS:
        agent_cfg.pop(field, None)
    langsmith_key = str(agent_cfg.get("langsmith_api_key") or "").strip()
    agent_cfg["langsmith_api_key_configured"] = bool(langsmith_key)
    agent_cfg.pop("langsmith_api_key", None)
    return {
        "api": api_cfg_safe,
        "bot": bot_cfg,
        "logging": config_dict.get("logging", {}),
        "agent": agent_cfg,
        "services": config_dict.get("services", {}),
        "local_auth_sync": _build_local_auth_sync_state(oauth_status),
        "oauth": _sanitize_model_auth_overview_payload(oauth_status),
    }


def _resolve_auth_request_settings(payload: dict | None) -> dict:
    body = payload if isinstance(payload, dict) else {}
    explicit_settings = body.get("settings")
    if isinstance(explicit_settings, dict):
        return dict(explicit_settings)

    preset_name = str(body.get("preset_name") or "").strip()
    snapshot = config_service.get_snapshot()
    api_cfg = dict(snapshot.api)
    if preset_name == "root_config":
        return dict(api_cfg)
    if preset_name:
        for preset in api_cfg.get("presets", []) or []:
            if isinstance(preset, dict) and str(preset.get("name") or "").strip() == preset_name:
                return dict(preset)
    return {}


def _normalize_ollama_tags_url(base_url: str) -> str:
    raw = str(base_url or "http://127.0.0.1:11434/v1").strip()
    if not raw:
        raw = "http://127.0.0.1:11434/v1"

    parsed = urlsplit(raw)
    scheme = (parsed.scheme or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url must use http or https scheme")
    netloc = parsed.netloc or parsed.path
    if not netloc:
        raise ValueError("base_url is invalid")
    hostname = _extract_hostname(urlunsplit((scheme, netloc, "", "", "")))
    if not _is_trusted_local_hostname(hostname):
        raise ValueError("base_url must point to localhost or loopback address")
    path = parsed.path if parsed.netloc else ""
    path = path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    path = f"{path}/api/tags" if path else "/api/tags"
    return urlunsplit((scheme, netloc, path, "", ""))


def _resolve_log_file_path(logging_config: dict | None) -> Path:
    logging_cfg = logging_config if isinstance(logging_config, dict) else {}
    configured = str(logging_cfg.get("file") or "data/logs/bot.log").strip()
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = (get_project_root() / candidate).resolve()
    else:
        candidate = candidate.resolve()

    data_root = ensure_data_root().resolve()
    allowed_roots = [(data_root / "logs").resolve(), data_root]
    for root in allowed_roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise ValueError("log file path must stay under data directory")


def _fetch_ollama_models_sync(base_url: str) -> list[str]:
    tags_url = _normalize_ollama_tags_url(base_url)
    resp = httpx.get(tags_url, timeout=3.0)
    resp.raise_for_status()
    data = resp.json()
    models = data.get("models") or []
    names: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        name = str(model.get("model") or model.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _get_cost_filters() -> dict:
    return {
        "period": request.args.get("period", "30d", type=str),
        "provider_id": request.args.get("provider_id", "", type=str),
        "model": request.args.get("model", "", type=str),
        "preset": request.args.get("preset", "", type=str),
        "review_reason": request.args.get("review_reason", "", type=str),
        "suggested_action": request.args.get("suggested_action", "", type=str),
        "only_priced": str(request.args.get("only_priced", "false")).strip().lower() in {"1", "true", "yes", "on"},
        "include_estimated": str(request.args.get("include_estimated", "true")).strip().lower() in {"1", "true", "yes", "on"},
    }


async def _reload_runtime_config_if_needed(
    *,
    current_config: dict,
    snapshot: Any,
) -> dict | None:
    effective_config = snapshot.to_dict()
    changed_paths = diff_config_paths(current_config, effective_config)
    if manager.is_running and manager.bot and changed_paths:
        return await manager.reload_runtime_config(
            new_config=effective_config,
            changed_paths=changed_paths,
            force_ai_reload=False,
            strict_active_preset=False,
        )
    return None


async def _expire_pending_replies(mem_mgr: Any, reply_policy: dict) -> None:
    ttl_hours = int((reply_policy or {}).get("pending_ttl_hours", 24) or 24)
    cutoff = int(datetime.now().timestamp()) - (ttl_hours * 3600)
    await mem_mgr.expire_pending_replies(created_before=cutoff)
    if manager.bot and hasattr(manager.bot, "refresh_pending_reply_stats"):
        await manager.bot.refresh_pending_reply_stats(notify=False)


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _operation_failed(result: Any) -> bool:
    return isinstance(result, dict) and result.get("success") is False


_MODEL_AUTH_SENSITIVE_PATH_KEYS = {
    "auth_path",
    "oauth_creds_path",
    "google_accounts_path",
    "config_path",
    "managed_settings_path",
    "credentials_path",
    "session_path",
    "cookie_path",
    "indexeddb_path",
    "local_storage_path",
    "private_storage_path",
    "private_auth_file_path",
    "source_auth_path",
    "locator_path",
    "keychain_locator",
}


def _redact_path_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1].strip()
    return f".../{leaf}" if leaf else "..."


def _redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    sanitized = re.sub(
        r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+",
        "Authorization: Bearer [REDACTED]",
        text,
    )
    sanitized = re.sub(
        r"(?i)\bx-api-token\s*:\s*[^\s,;]+",
        "X-Api-Token: [REDACTED]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\bsk-[a-z0-9]{12,}\b",
        "[REDACTED_SK]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b(token|secret|password|api[_-]?key)\s*[:=]\s*([^\s,;]+)",
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
    )
    return sanitized


def _sanitize_model_auth_overview_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_model_auth_overview_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            key_lower = key_text.lower()
            if key_lower == "watch_paths":
                sanitized[key_text] = []
                continue
            if key_lower in _MODEL_AUTH_SENSITIVE_PATH_KEYS or key_lower.endswith("_path"):
                sanitized[key_text] = _redact_path_value(item)
                continue
            if any(keyword in key_lower for keyword in _MODEL_AUTH_SENSITIVE_KEYWORDS):
                sanitized[key_text] = "[REDACTED]"
                continue
            sanitized[key_text] = _sanitize_model_auth_overview_payload(item)
        return sanitized
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _collect_restore_auth_checks() -> dict:
    checked_at = int(datetime.now().timestamp())
    try:
        overview_payload = model_auth_center_service.get_overview()
        overview = overview_payload.get("overview") if isinstance(overview_payload, dict) else {}
        cards = overview.get("cards") if isinstance(overview, dict) else []
        warnings: list[dict] = []
        for card in cards or []:
            provider = card.get("provider") if isinstance(card, dict) else {}
            provider_id = str((provider or {}).get("id") or "").strip()
            auth_states = card.get("auth_states") if isinstance(card, dict) else []
            for state in auth_states or []:
                if not isinstance(state, dict):
                    continue
                status = str(state.get("status") or "").strip().lower()
                health = state.get("health") if isinstance(state.get("health"), dict) else {}
                requires_attention = bool(state.get("requires_attention"))
                unhealthy_health = bool(health) and health.get("checked_at") and not bool(health.get("ok"))
                if not (requires_attention or unhealthy_health or status in {"missing", "invalid", "expired"}):
                    continue
                warnings.append(
                    {
                        "provider_id": provider_id,
                        "method_id": str(state.get("method_id") or "").strip(),
                        "status": status,
                        "summary": str(state.get("summary") or "").strip(),
                        "detail": str(state.get("detail") or "").strip(),
                        "health_state": str(health.get("state") or "").strip(),
                        "health_error_code": str(health.get("error_code") or "").strip(),
                    }
                )

        return {
            "success": True,
            "checked_at": checked_at,
            "warning_count": len(warnings),
            "warnings": warnings[:50],
            "local_auth_sync": (overview or {}).get("local_auth_sync") if isinstance(overview, dict) else {},
        }
    except Exception as exc:
        return {
            "success": False,
            "checked_at": checked_at,
            "warning_count": 0,
            "warnings": [],
            "message": str(exc),
        }




@app.route("/api/status", methods=["GET"])
async def get_status():
    """Endpoint handler."""
    return jsonify(manager.get_status())


@app.route("/api/ping", methods=["GET"])
async def ping():
    """Endpoint handler."""
    return jsonify({"success": True, "service_running": True})


@app.route("/api/readiness", methods=["GET"])
async def get_readiness():
    """Endpoint handler."""
    force_refresh = str(request.args.get("refresh", "false") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    report = await asyncio.to_thread(
        readiness_service.get_report,
        force_refresh=force_refresh,
    )
    return jsonify(report)


@app.route("/api/metrics", methods=["GET"])
async def get_metrics():
    """Export Prometheus-style runtime metrics."""
    runtime_metrics = manager.export_metrics().rstrip()
    extra_metrics = _render_additional_api_metrics().strip()
    payload = runtime_metrics
    if extra_metrics:
        payload = f"{runtime_metrics}\n{extra_metrics}\n" if runtime_metrics else f"{extra_metrics}\n"
    return app.response_class(
        payload,
        mimetype="text/plain; version=0.0.4; charset=utf-8",
    )


@app.route("/api/events")
async def sse_events():
    """Endpoint handler."""
    response = await make_response(
        manager.event_generator(),
        {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    response.timeout = None
    return response


@app.route("/api/events_ticket", methods=["GET"])
async def get_events_ticket():
    """Return the SSE ticket for local trusted clients."""
    if not SSE_TICKET:
        return jsonify({"success": False, "message": "sse_ticket_unavailable"}), 503
    return jsonify({"success": True, "ticket": SSE_TICKET})


@app.route("/api/start", methods=["POST"])
async def start_bot():
    """Endpoint handler."""
    result = await manager.start()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/stop", methods=["POST"])
async def stop_bot():
    """Endpoint handler."""
    result = await manager.stop()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/growth/start", methods=["POST"])
async def start_growth():
    """Endpoint handler."""
    result = await manager.start_growth()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/growth/stop", methods=["POST"])
async def stop_growth():
    """Endpoint handler."""
    result = await manager.stop_growth()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/growth/tasks", methods=["GET"])
async def list_growth_tasks():
    """Endpoint handler."""
    result = await manager.list_growth_tasks()
    return jsonify(result)


@app.route("/api/growth/tasks/<task_type>/clear", methods=["POST"])
async def clear_growth_task(task_type: str):
    """Endpoint handler."""
    result = await manager.clear_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/run", methods=["POST"])
async def run_growth_task(task_type: str):
    """Endpoint handler."""
    result = await manager.run_growth_task_now(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/pause", methods=["POST"])
async def pause_growth_task(task_type: str):
    """Endpoint handler."""
    result = await manager.pause_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/resume", methods=["POST"])
async def resume_growth_task(task_type: str):
    """Endpoint handler."""
    result = await manager.resume_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/wechat_export/probe", methods=["POST"])
async def wechat_export_probe():
    """Probe local WeChat sessions and decrypt prerequisites."""
    try:
        result = await wechat_export_service.probe()
        return jsonify(result)
    except Exception as e:
        logger.error(f"wechat_export probe failed: {e}")
        return _json_internal_error("wechat_export_probe_failed", code="wechat_export_probe_failed")


@app.route("/api/wechat_export/decrypt/start", methods=["POST"])
async def wechat_export_start_decrypt():
    """Start a background decrypt job."""
    try:
        payload = await request.get_json(silent=True) or {}
        result = await wechat_export_service.start_decrypt(payload)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export start decrypt failed: {e}")
        return _json_internal_error("wechat_export_decrypt_start_failed", code="wechat_export_decrypt_start_failed")


@app.route("/api/wechat_export/decrypt/jobs/<job_id>", methods=["GET"])
async def wechat_export_decrypt_job(job_id: str):
    """Fetch decrypt job status."""
    try:
        result = await wechat_export_service.get_decrypt_job(job_id)
        return jsonify(result), (200 if result.get("success", True) else 404)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export decrypt job query failed: {e}")
        return _json_internal_error("wechat_export_decrypt_job_failed", code="wechat_export_decrypt_job_failed")


@app.route("/api/wechat_export/contacts", methods=["POST"])
async def wechat_export_contacts():
    """List contacts from a decrypted Msg directory."""
    try:
        payload = await request.get_json(silent=True) or {}
        result = await wechat_export_service.list_contacts(payload)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export contacts failed: {e}")
        return _json_internal_error("wechat_export_contacts_failed", code="wechat_export_contacts_failed")


@app.route("/api/wechat_export/export", methods=["POST"])
async def wechat_export_run_export():
    """Export selected contacts to CSV files."""
    try:
        payload = await request.get_json(silent=True) or {}
        result = await wechat_export_service.export_contacts(payload)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export export failed: {e}")
        return _json_internal_error("wechat_export_export_failed", code="wechat_export_export_failed")


@app.route("/api/wechat_export/apply/preview", methods=["POST"])
async def wechat_export_preview_apply():
    """Preview config changes for export-rag application."""
    try:
        payload = await request.get_json(silent=True) or {}
        result = await wechat_export_service.preview_apply(
            payload,
            config_service=config_service,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export apply preview failed: {e}")
        return _json_internal_error("wechat_export_apply_preview_failed", code="wechat_export_apply_preview_failed")


@app.route("/api/wechat_export/apply", methods=["POST"])
async def wechat_export_apply():
    """Persist export-rag settings and trigger sync."""
    try:
        payload = await request.get_json(silent=True) or {}
        result = await wechat_export_service.apply(
            payload,
            config_service=config_service,
            manager=manager,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as e:
        logger.error(f"wechat_export apply failed: {e}")
        return _json_internal_error("wechat_export_apply_failed", code="wechat_export_apply_failed")


@app.route("/api/pause", methods=["POST"])
async def pause_bot():
    """Endpoint handler."""
    data = await request.get_json(silent=True) or {}
    reason = str(data.get("reason") or "manual_pause").strip() or "manual_pause"
    result = await manager.pause(reason)
    return _json_operation_result(result, failure_status=409)


@app.route("/api/resume", methods=["POST"])
async def resume_bot():
    """Endpoint handler."""
    result = await manager.resume()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/restart", methods=["POST"])
async def restart_bot():
    """Endpoint handler."""
    result = await manager.restart()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/recover", methods=["POST"])
async def recover_bot():
    """Endpoint handler."""
    result = await manager.recover()
    return _json_operation_result(result, failure_status=409)


@app.route("/api/messages", methods=["GET"])
async def get_messages():
    """Endpoint handler."""
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        chat_id = request.args.get("chat_id", "", type=str)
        keyword = request.args.get("keyword", "", type=str)

        mem_mgr = manager.get_memory_manager()

        page = await mem_mgr.get_message_page(
            limit=limit,
            offset=offset,
            chat_id=chat_id,
            keyword=keyword,
        )
        chats = await mem_mgr.list_chat_summaries()

        return jsonify(
            {
                "success": True,
                "messages": page["messages"],
                "total": page["total"],
                "limit": page["limit"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "chats": chats,
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/contact_profile", methods=["GET"])
async def get_contact_profile():
    """Endpoint handler."""
    try:
        chat_id = str(request.args.get("chat_id", "", type=str) or "").strip()
        if not chat_id:
            return jsonify({"success": False, "message": "chat_id is required"}), 400

        mem_mgr = manager.get_memory_manager()
        profile = await mem_mgr.get_contact_profile(chat_id)
        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/contact_prompt", methods=["POST"])
async def save_contact_prompt():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        chat_id = str(data.get("chat_id") or "").strip()
        contact_prompt = extract_editable_system_prompt(
            str(data.get("contact_prompt") or "").strip()
        )
        if not chat_id:
            return jsonify({"success": False, "message": "chat_id is required"}), 400
        if not contact_prompt:
            return jsonify({"success": False, "message": "contact_prompt is required"}), 400

        mem_mgr = manager.get_memory_manager()
        profile = await mem_mgr.save_contact_prompt(
            chat_id,
            contact_prompt,
            source="user_edit",
        )
        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/message_feedback", methods=["POST"])
async def save_message_feedback():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        message_id = data.get("message_id")
        feedback = str(data.get("feedback") or "").strip().lower()
        if message_id in (None, ""):
            return jsonify({"success": False, "message": "message_id is required"}), 400
        if feedback not in {"helpful", "unhelpful", ""}:
            return jsonify({"success": False, "message": "feedback must be 'helpful' or 'unhelpful'"}), 400

        mem_mgr = manager.get_memory_manager()
        result = await mem_mgr.update_message_feedback(message_id, feedback)
        if result is None:
            return jsonify({"success": False, "message": "message not found"}), 404
        if str(result.get("role") or "").strip().lower() != "assistant":
            return jsonify({"success": False, "message": "feedback is only allowed on assistant messages"}), 400

        if manager.bot and hasattr(manager.bot, "reply_quality_tracker"):
            manager.bot.reply_quality_tracker.log_feedback(
                message_id=int(result.get("id") or 0),
                feedback=str(result.get("feedback") or ""),
            )
        if manager.bot and hasattr(manager.bot, "apply_reply_feedback_change"):
            manager.bot.apply_reply_feedback_change(
                str(result.get("previous_feedback") or ""),
                str(result.get("feedback") or ""),
            )

        return jsonify(
            {
                "success": True,
                "message_id": int(result.get("id") or 0),
                "feedback": str(result.get("feedback") or ""),
                "metadata": dict(result.get("metadata") or {}),
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/send", methods=["POST"])
async def send_message():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        target = str(data.get("target") or "").strip()
        content = str(data.get("content") or "")

        if not target or not content.strip():
            return jsonify({"success": False, "message": "target and content are required"}), 400

        if len(target) > MAX_SEND_TARGET_CHARS:
            return jsonify({"success": False, "message": "target is too long"}), 400
        if len(content) > MAX_SEND_CONTENT_CHARS:
            return jsonify({"success": False, "message": "content is too long"}), 400

        result = await manager.send_message(target, content)
        return jsonify(result)
    except Exception as e:
        logger.exception("send message failed: %s", e)
        return _json_internal_error("send_failed", code="send_failed")
@app.route("/api/reply_policies", methods=["GET"])
async def get_reply_policies():
    """Return the current reply policy and pending queue summary."""
    try:
        snapshot = config_service.get_snapshot()
        reply_policy = normalize_reply_policy(snapshot.bot.get("reply_policy"))
        mem_mgr = manager.get_memory_manager()
        await _expire_pending_replies(mem_mgr, reply_policy)
        pending_stats = await mem_mgr.get_pending_reply_stats()
        return jsonify(
            {
                "success": True,
                "reply_policy": reply_policy,
                "pending_stats": pending_stats,
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/reply_policies", methods=["POST"])
async def save_reply_policies():
    """Persist reply policy updates and hot-reload them when possible."""
    try:
        data = await request.get_json(silent=True) or {}
        current_snapshot = config_service.get_snapshot()
        current_config = current_snapshot.to_dict()
        current_policy = normalize_reply_policy(current_snapshot.bot.get("reply_policy"))

        if isinstance(data.get("reply_policy"), dict):
            next_policy = normalize_reply_policy(data.get("reply_policy"))
        else:
            next_policy = current_policy

        if "chat_id" in data or "mode" in data:
            next_policy = update_per_chat_override(
                next_policy,
                chat_id=str(data.get("chat_id") or "").strip(),
                mode=str(data.get("mode") or "").strip(),
            )

        config_path = getattr(manager, "config_path", None)
        if not isinstance(config_path, str) or not config_path.strip():
            config_path = None

        snapshot = await asyncio.to_thread(
            config_service.save_effective_config,
            {"bot": {"reply_policy": next_policy}},
            config_path=config_path,
            source="api_reply_policy",
        )
        changed_paths = diff_config_paths(current_config, snapshot.to_dict())
        runtime_apply = await _reload_runtime_config_if_needed(
            current_config=current_config,
            snapshot=snapshot,
        )
        mem_mgr = manager.get_memory_manager()
        await _expire_pending_replies(mem_mgr, next_policy)
        pending_stats = await mem_mgr.get_pending_reply_stats()
        return jsonify(
            {
                "success": True,
                "reply_policy": normalize_reply_policy(snapshot.bot.get("reply_policy")),
                "changed_paths": changed_paths,
                "runtime_apply": runtime_apply,
                "pending_stats": pending_stats,
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/pending_replies", methods=["GET"])
async def list_pending_replies():
    """Return queued replies awaiting manual review."""
    try:
        chat_id = str(request.args.get("chat_id", "", type=str) or "").strip()
        status = str(request.args.get("status", "pending", type=str) or "pending").strip().lower()
        limit = max(1, min(int(request.args.get("limit", 50, type=int) or 50), 200))

        snapshot = config_service.get_snapshot()
        reply_policy = normalize_reply_policy(snapshot.bot.get("reply_policy"))
        mem_mgr = manager.get_memory_manager()
        await _expire_pending_replies(mem_mgr, reply_policy)
        items = await mem_mgr.list_pending_replies(
            chat_id=chat_id,
            status=None if status == "all" else status,
            limit=limit,
        )
        stats = await mem_mgr.get_pending_reply_stats()
        return jsonify({"success": True, "items": items, "stats": stats})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/pending_replies/<int:pending_id>/approve", methods=["POST"])
async def approve_pending_reply(pending_id: int):
    """Approve and send a queued reply."""
    try:
        data = await request.get_json(silent=True) or {}
        edited_reply = str(data.get("edited_reply") or "")

        if not manager.is_running or not manager.bot or not hasattr(manager.bot, "approve_pending_reply"):
            return jsonify({"success": False, "message": "bot is not running"}), 409

        result = await manager.bot.approve_pending_reply(
            pending_id,
            edited_reply=edited_reply,
        )
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/pending_replies/<int:pending_id>/reject", methods=["POST"])
async def reject_pending_reply(pending_id: int):
    """Reject a queued reply without sending it."""
    try:
        if manager.bot and manager.is_running and hasattr(manager.bot, "reject_pending_reply"):
            result = await manager.bot.reject_pending_reply(pending_id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code

        snapshot = config_service.get_snapshot()
        reply_policy = normalize_reply_policy(snapshot.bot.get("reply_policy"))
        mem_mgr = manager.get_memory_manager()
        await _expire_pending_replies(mem_mgr, reply_policy)
        pending_reply = await mem_mgr.get_pending_reply(pending_id)
        if pending_reply is None:
            return jsonify({"success": False, "message": "pending reply not found"}), 404
        if str(pending_reply.get("status") or "") != "pending":
            return jsonify({"success": False, "message": "pending reply already resolved"}), 409

        resolved = await mem_mgr.resolve_pending_reply(
            pending_id,
            status="rejected",
            metadata={"rejected_at": int(datetime.now().timestamp())},
        )
        return jsonify({"success": True, "pending_reply": resolved})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/backups", methods=["GET"])
async def list_backups():
    """List workspace backups and summary information."""
    try:
        limit = max(1, min(int(request.args.get("limit", 20, type=int) or 20), 100))
        payload = await asyncio.to_thread(backup_service.list_backups, limit=limit)
        return jsonify(payload)
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/backups", methods=["POST"])
async def create_backup():
    """Create a quick or full workspace backup."""
    try:
        data = await request.get_json(silent=True) or {}
        mode = str(data.get("mode") or "").strip().lower()
        label = str(data.get("label") or "").strip()
        if mode not in {"quick", "full"}:
            return jsonify({"success": False, "message": "mode must be quick or full"}), 400

        growth_manager = get_growth_manager()
        growth_running = bool(getattr(growth_manager, "is_running", False))
        bot_running = bool(getattr(manager, "is_running", False))
        if bot_running or growth_running:
            return jsonify(
                {
                    "success": False,
                    "message": "stop bot and growth tasks before creating backup snapshots",
                    "running": {
                        "bot": bot_running,
                        "growth": growth_running,
                    },
                }
            ), 409

        if maintenance_lock.locked():
            return jsonify({"success": False, "message": "maintenance_in_progress"}), 409

        async with maintenance_lock:
            backup_service.update_config(config_service.get_snapshot().bot)
            backup = await asyncio.to_thread(backup_service.create_backup, mode, label=label)
            summary = await asyncio.to_thread(backup_service.list_backups, limit=20)
            return jsonify(
                {
                    "success": True,
                    "backup": backup,
                    "summary": summary.get("summary"),
                    "backups": summary.get("backups"),
                }
            )
    except Exception as e:
        logger.exception("create backup failed: %s", e)
        return _json_internal_error("create_backup_failed", code="create_backup_failed")


@app.route("/api/backups/cleanup", methods=["POST"])
async def cleanup_backups():
    """Preview or apply backup cleanup retention policy."""
    try:
        data = await request.get_json(silent=True) or {}
        dry_run = _parse_bool(data.get("dry_run"), default=True)
        keep_quick = data.get("keep_quick", DEFAULT_KEEP_QUICK_BACKUPS)
        keep_full = data.get("keep_full", DEFAULT_KEEP_FULL_BACKUPS)
        if not dry_run and maintenance_lock.locked():
            return jsonify({"success": False, "message": "maintenance_in_progress"}), 409
        if not dry_run:
            async with maintenance_lock:
                payload = await asyncio.to_thread(
                    backup_service.cleanup_backups,
                    keep_quick=keep_quick,
                    keep_full=keep_full,
                    apply=True,
                )
                return jsonify(payload)
        payload = await asyncio.to_thread(
            backup_service.cleanup_backups,
            keep_quick=keep_quick,
            keep_full=keep_full,
            apply=False,
        )
        return jsonify(payload)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.exception("backup cleanup failed: %s", e)
        return _json_internal_error("backup_cleanup_failed", code="backup_cleanup_failed")


@app.route("/api/backups/restore", methods=["POST"])
async def restore_backup():
    """Dry-run or apply a workspace restore from a backup snapshot."""
    try:
        data = await request.get_json(silent=True) or {}
        backup_ref = str(data.get("backup_id") or "").strip()
        allow_legacy_unverified = _parse_bool(data.get("allow_legacy_unverified"), default=False)
        if not backup_ref:
            return jsonify({"success": False, "message": "backup_id is required"}), 400

        backup_service.update_config(config_service.get_snapshot().bot)
        plan = await asyncio.to_thread(
            backup_service.build_restore_plan,
            backup_ref,
            allow_legacy_unverified=allow_legacy_unverified,
        )
        if _parse_bool(data.get("dry_run"), default=True):
            return jsonify(
                {
                    "success": bool(plan.get("valid")),
                    "dry_run": True,
                    "plan": plan,
                }
            ), (200 if plan.get("valid") else 400)

        if maintenance_lock.locked():
            return jsonify({"success": False, "message": "maintenance_in_progress"}), 409

        async with maintenance_lock:
            if not plan.get("valid"):
                message = "backup files are incomplete"
                if list(plan.get("invalid_files") or []):
                    message = "backup files contain unsupported paths"
                elif plan.get("legacy_unverified") and not allow_legacy_unverified:
                    message = "legacy backup is missing checksum summary; set allow_legacy_unverified=true to continue"
                elif list(plan.get("checksum_mismatches") or []) or list(plan.get("checksum_missing_files") or []):
                    message = "backup checksum verification failed"
                return jsonify(
                    {
                        "success": False,
                        "message": message,
                        "plan": plan,
                    }
                ), 400

            growth_manager = get_growth_manager()
            growth_was_running = bool(getattr(growth_manager, "is_running", False))
            bot_was_running = bool(manager.is_running)
            stop_results = {}
            restart_results = {}
            pre_restore_backup = None
            apply_result = None
            restore_applied = False
            apply_attempted = False
            bot_stopped = False
            growth_stopped = False

            try:
                if growth_was_running:
                    stop_results["growth"] = await growth_manager.stop(
                        persist=False,
                        source="backup_restore",
                    )
                    growth_stopped = not _operation_failed(stop_results["growth"])
                if bot_was_running:
                    stop_results["bot"] = await manager.stop()
                    bot_stopped = not _operation_failed(stop_results["bot"])
                stop_failed_components = [
                    component for component, result in stop_results.items() if _operation_failed(result)
                ]
                if stop_failed_components:
                    raise RuntimeError(
                        "failed to stop runtime before restore: "
                        + ", ".join(stop_failed_components)
                    )

                if getattr(manager, "memory_manager", None) is not None:
                    await manager.memory_manager.close()
                    manager.memory_manager = None
                close_reply_quality_tracker()

                pre_restore_backup = await asyncio.to_thread(
                    backup_service.create_backup,
                    "quick",
                    label="pre-restore",
                )
                apply_attempted = True
                apply_result = await asyncio.to_thread(
                    backup_service.apply_restore,
                    backup_ref,
                    allow_legacy_unverified=allow_legacy_unverified,
                )
                if isinstance(apply_result, dict) and apply_result.get("success") is False:
                    raise RuntimeError(str(apply_result.get("message") or "backup restore apply failed"))
                restore_applied = True
                snapshot = config_service.reload(config_path=getattr(manager, "config_path", None))
                auth_restore_checks = _collect_restore_auth_checks()

                if bot_stopped:
                    restart_results["bot"] = await manager.start()
                if growth_stopped:
                    restart_results["growth"] = await growth_manager.start(
                        persist=False,
                        source="backup_restore",
                    )
                restart_failed_components = [
                    component for component, result in restart_results.items() if _operation_failed(result)
                ]
                if restart_failed_components:
                    raise RuntimeError(
                        "failed to restart runtime after restore: "
                        + ", ".join(restart_failed_components)
                    )

                payload = {
                    "success": True,
                    "dry_run": False,
                    "plan": plan,
                    "pre_restore_backup": pre_restore_backup,
                    "apply_result": apply_result,
                    "stop_results": stop_results,
                    "restart_results": restart_results,
                    "auth_restore_checks": auth_restore_checks,
                    "restored_at": int(datetime.now().timestamp()),
                    "config_version": getattr(snapshot, "version", None),
                }
                await asyncio.to_thread(backup_service.save_restore_result, payload)
                return jsonify(payload)
            except Exception:
                rollback_result = None
                rollback_id = str((pre_restore_backup or {}).get("id") or "").strip()
                should_attempt_rollback = bool(
                    rollback_id and (restore_applied or apply_result is not None or apply_attempted)
                )
                if should_attempt_rollback:
                    if rollback_id:
                        try:
                            rollback_result = await asyncio.to_thread(
                                backup_service.apply_restore,
                                rollback_id,
                            )
                            config_service.reload(config_path=getattr(manager, "config_path", None))
                        except Exception as rollback_error:
                            logger.exception("restore backup rollback failed: %s", rollback_error)
                            rollback_result = {
                                "success": False,
                                "message": "rollback_failed",
                                "code": "rollback_failed",
                            }
                if bot_stopped:
                    try:
                        restart_results["bot"] = await manager.start()
                    except Exception as restart_error:
                        logger.exception("restore recover bot restart failed: %s", restart_error)
                        restart_results["bot"] = {
                            "success": False,
                            "message": "restart_failed",
                            "code": "restart_failed",
                        }
                if growth_stopped:
                    try:
                        restart_results["growth"] = await growth_manager.start(
                            persist=False,
                            source="backup_restore_recover",
                        )
                    except Exception as restart_error:
                        logger.exception("restore recover growth restart failed: %s", restart_error)
                        restart_results["growth"] = {
                            "success": False,
                            "message": "restart_failed",
                            "code": "restart_failed",
                        }

                payload = {
                    "success": False,
                    "dry_run": False,
                    "plan": plan,
                    "pre_restore_backup": pre_restore_backup,
                    "apply_result": apply_result,
                    "rollback_result": rollback_result,
                    "stop_results": stop_results,
                    "restart_results": restart_results,
                    "auth_restore_checks": _collect_restore_auth_checks(),
                    "restored_at": int(datetime.now().timestamp()),
                    "message": "restore_backup_failed",
                    "code": "restore_backup_failed",
                }
                await asyncio.to_thread(backup_service.save_restore_result, payload)
                return jsonify(payload), 500
    except Exception as e:
        logger.exception("restore backup failed: %s", e)
        return _json_internal_error("restore_backup_failed", code="restore_backup_failed")


@app.route("/api/data_controls", methods=["GET"])
async def get_data_controls():
    """Return supported workspace data-control scopes and a dry-run plan."""
    try:
        data_control_service.update_config(config_service.get_snapshot().bot)
        plan = await asyncio.to_thread(data_control_service.build_clear_plan, None)
        return jsonify(
            {
                "success": True,
                "supported_scopes": data_control_service.list_supported_scopes(),
                "plan": plan,
            }
        )
    except Exception as e:
        logger.error(f"load data controls failed: {e}")
        return jsonify({"success": False, "message": f"load data controls failed: {str(e)}"}), 500


@app.route("/api/data_controls/clear", methods=["POST"])
async def clear_data_controls():
    """Preview or clear selected local runtime/workspace data artifacts."""
    try:
        data = await request.get_json(silent=True) or {}
        data_control_service.update_config(config_service.get_snapshot().bot)
        raw_scopes = data.get("scopes", None)
        scopes = None
        if isinstance(raw_scopes, str):
            scopes = [raw_scopes]
        elif isinstance(raw_scopes, list):
            scopes = [str(item or "").strip() for item in raw_scopes]
        elif raw_scopes is not None:
            raise ValueError("scopes must be a string or list")
        if isinstance(scopes, list):
            scopes = [item for item in scopes if item]

        dry_run = _parse_bool(data.get("dry_run"), default=True)
        if not dry_run:
            if maintenance_lock.locked():
                return jsonify({"success": False, "message": "maintenance_in_progress"}), 409
            async with maintenance_lock:
                growth_manager = get_growth_manager()
                growth_running = bool(getattr(growth_manager, "is_running", False))
                bot_running = bool(getattr(manager, "is_running", False))
                if bot_running or growth_running:
                    return jsonify(
                        {
                            "success": False,
                            "message": "stop bot and growth tasks before applying data cleanup",
                            "running": {
                                "bot": bot_running,
                                "growth": growth_running,
                            },
                        }
                    ), 409
                if scopes is None:
                    return jsonify(
                        {
                            "success": False,
                            "message": "scopes is required when dry_run=false; use ['all'] for full cleanup",
                        }
                    ), 400
                memory_manager = getattr(manager, "memory_manager", None)
                if memory_manager is not None:
                    await memory_manager.close()
                    manager.memory_manager = None
                close_reply_quality_tracker()
                payload = await asyncio.to_thread(
                    data_control_service.clear,
                    scopes,
                    apply=True,
                )
                return jsonify(payload), (200 if payload.get("success", False) else 500)

        payload = await asyncio.to_thread(
            data_control_service.clear,
            scopes,
            apply=False,
        )
        return jsonify(payload), (200 if payload.get("success", False) else 500)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.exception("clear data controls failed: %s", e)
        return _json_internal_error("clear_data_controls_failed", code="clear_data_controls_failed")


@app.route("/api/evals/latest", methods=["GET"])
async def get_latest_eval_report():
    """Return the newest locally generated eval report if one exists."""
    try:
        eval_root = Path(get_app_config_path()).resolve().parent / "evals"
        if not eval_root.exists():
            return jsonify({"success": True, "report": None})

        candidates = sorted(
            (path for path in eval_root.glob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return jsonify({"success": True, "report": None})

        report_path = candidates[0]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return jsonify(
            {
                "success": True,
                "report": report,
                "name": report_path.name,
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/usage", methods=["GET"])
async def get_usage():
    """Endpoint handler."""
    try:
        stats = manager.get_usage()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        logger.exception("get usage failed: %s", e)
        return _json_internal_error("get_usage_failed", code="get_usage_failed")


@app.route("/api/pricing", methods=["GET"])
async def get_pricing():
    """Endpoint handler."""
    try:
        snapshot = await cost_service.get_pricing_snapshot()
        return jsonify({"success": True, **snapshot})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/pricing/refresh", methods=["POST"])
async def refresh_pricing():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        providers = data.get("providers")
        payload = await cost_service.refresh_pricing(
            providers=providers if isinstance(providers, list) else None
        )
        return jsonify(payload)
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/costs/summary", methods=["GET"])
async def get_costs_summary():
    """Endpoint handler."""
    try:
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_summary(
            manager.get_memory_manager(),
            snapshot.config,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/costs/sessions", methods=["GET"])
async def get_cost_sessions():
    """Endpoint handler."""
    try:
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_sessions(
            manager.get_memory_manager(),
            snapshot.config,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/costs/session_details", methods=["GET"])
async def get_cost_session_details():
    """Endpoint handler."""
    try:
        chat_id = str(request.args.get("chat_id", "", type=str) or "").strip()
        if not chat_id:
            return jsonify({"success": False, "message": "chat_id is required"}), 400
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_session_details(
            manager.get_memory_manager(),
            snapshot.config,
            chat_id=chat_id,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/costs/review_queue_export", methods=["GET"])
async def export_cost_review_queue():
    """Endpoint handler."""
    try:
        snapshot = config_service.get_snapshot()
        payload = await cost_service.export_review_queue(
            manager.get_memory_manager(),
            snapshot.config,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.exception("export review queue failed: %s", e)
        return _json_internal_error(
            "export_cost_review_queue_failed",
            code="export_cost_review_queue_failed",
        )


@app.route("/api/model_catalog", methods=["GET"])
async def get_model_catalog_api():
    """Endpoint handler."""
    try:
        return jsonify({"success": True, **get_model_catalog()})
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/model_auth/overview", methods=["GET"])
async def get_model_auth_overview():
    try:
        return jsonify(_sanitize_model_auth_overview_payload(model_auth_center_service.get_overview()))
    except Exception as e:
        logger.error(f"model auth overview failed: {e}")
        return _json_internal_error("model_auth_overview_failed", code="model_auth_overview_failed")


@app.route("/api/model_auth/action", methods=["POST"])
async def post_model_auth_action():
    try:
        data = await request.get_json(silent=True) or {}
        action = str(data.get("action") or "").strip()
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else dict(data)
        result = await model_auth_center_service.perform_action(action, payload)
        return jsonify(_sanitize_model_auth_overview_payload(result))
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"model auth action failed: {e}")
        return _json_internal_error("model_auth_action_failed", code="model_auth_action_failed")


@app.route("/api/auth/providers", methods=["GET"])
async def get_auth_providers_api():
    try:
        return jsonify(_sanitize_model_auth_overview_payload(get_oauth_provider_statuses()))
    except Exception as e:
        logger.error(f"oauth provider listing failed: {e}")
        return _json_internal_error("oauth_provider_list_failed", code="oauth_provider_list_failed")


@app.route("/api/auth/providers/<provider_key>/start", methods=["POST"])
async def start_auth_provider_flow(provider_key: str):
    try:
        data = await request.get_json(silent=True) or {}
        settings = _resolve_auth_request_settings(data)
        payload = launch_oauth_login(provider_key, settings=settings)
        payload["oauth"] = get_oauth_provider_statuses()
        return jsonify(_sanitize_model_auth_overview_payload(payload))
    except OAuthSupportError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"oauth start failed [{provider_key}]: {e}")
        return _json_internal_error("oauth_start_failed", code="oauth_start_failed")


@app.route("/api/auth/providers/<provider_key>/cancel", methods=["POST"])
async def cancel_auth_provider_flow(provider_key: str):
    try:
        data = await request.get_json(silent=True) or {}
        flow_id = str(data.get("flow_id") or "").strip()
        payload = cancel_auth_flow(provider_key, flow_id)
        payload["oauth"] = get_oauth_provider_statuses()
        return jsonify(_sanitize_model_auth_overview_payload(payload))
    except OAuthSupportError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"oauth cancel failed [{provider_key}]: {e}")
        return _json_internal_error("oauth_cancel_failed", code="oauth_cancel_failed")


@app.route("/api/auth/providers/<provider_key>/submit_callback", methods=["POST"])
async def submit_auth_provider_callback(provider_key: str):
    try:
        data = await request.get_json(silent=True) or {}
        flow_id = str(data.get("flow_id") or "").strip()
        callback_payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        payload = submit_auth_callback(provider_key, flow_id, callback_payload)
        payload["oauth"] = get_oauth_provider_statuses()
        return jsonify(_sanitize_model_auth_overview_payload(payload))
    except OAuthSupportError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"oauth callback submit failed [{provider_key}]: {e}")
        return _json_internal_error("oauth_callback_submit_failed", code="oauth_callback_submit_failed")


@app.route("/api/auth/providers/<provider_key>/logout_source", methods=["POST"])
async def logout_auth_provider_source(provider_key: str):
    try:
        data = await request.get_json(silent=True) or {}
        settings = _resolve_auth_request_settings(data)
        payload = logout_oauth_provider(provider_key, settings=settings)
        payload["oauth"] = get_oauth_provider_statuses()
        return jsonify(_sanitize_model_auth_overview_payload(payload))
    except OAuthSupportError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"oauth logout source failed [{provider_key}]: {e}")
        return _json_internal_error("oauth_logout_failed", code="oauth_logout_failed")


@app.route("/api/ollama/models", methods=["GET"])
async def get_ollama_models():
    """Return installed Ollama models from a local loopback endpoint."""
    try:
        base_url = request.args.get("base_url", "http://127.0.0.1:11434/v1", type=str)
        models = await asyncio.to_thread(_fetch_ollama_models_sync, base_url)
        return jsonify({"success": True, "models": models, "base_url": base_url})
    except ValueError as e:
        return jsonify(
            {
                "success": False,
                "message": str(e),
                "models": [],
            }
        ), 400
    except Exception as e:
        logger.warning("failed to fetch Ollama model list: %s", e)
        return jsonify(
            {
                "success": False,
                "message": "fetch_ollama_models_failed",
                "code": "fetch_ollama_models_failed",
                "models": [],
            }
        ), 502

@app.route("/api/config", methods=["GET"])
async def get_config():
    """Endpoint handler."""
    try:
        snapshot = config_service.get_snapshot()
        response = {"success": True, **_build_config_payload(snapshot)}
        return jsonify(response)
    except Exception as e:
        logger.error(f"get config failed: {e}")
        return _json_internal_error("get_config_failed", code="get_config_failed")


@app.route("/api/config/audit", methods=["GET"])
async def get_config_audit():
    """Endpoint handler."""
    try:
        snapshot = config_service.get_snapshot()
        loaded_at_raw = getattr(snapshot, "loaded_at", None)
        if hasattr(loaded_at_raw, "isoformat"):
            loaded_at = loaded_at_raw.isoformat()
        elif loaded_at_raw:
            loaded_at = datetime.fromtimestamp(float(loaded_at_raw)).isoformat()
        else:
            loaded_at = None
        audit = build_config_audit(
            snapshot.config,
            override_path=get_app_config_path(),
        )
        return jsonify(
            {
                "success": True,
                "version": snapshot.version,
                "loaded_at": loaded_at,
                "audit": audit,
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/config", methods=["POST"])
async def save_config():
    """Endpoint handler."""
    try:
        data = await request.get_json()
        current_snapshot = config_service.get_snapshot()
        current_config = current_snapshot.to_dict()
        requested_active = None
        force_ai_reload = False
        strict_active_preset = False
        if isinstance(data, dict):
            api_updates = data.get("api")
            if isinstance(api_updates, dict):
                force_ai_reload = True
                requested_active = (
                    str(api_updates.get("active_preset") or "").strip() or None
                )
                strict_active_preset = True

        config_path = getattr(manager, "config_path", None)
        if not isinstance(config_path, str) or not config_path.strip():
            config_path = None

        snapshot = await asyncio.to_thread(
            config_service.save_effective_config,
            data or {},
            config_path=config_path,
            source="api_override",
        )
        effective_config = snapshot.to_dict()
        changed_paths = diff_config_paths(current_config, effective_config)
        reload_plan = build_reload_plan(changed_paths)
        if changed_paths:
            force_ai_reload = force_ai_reload or any(
                get_effect_for_path(path).get("component") == "ai_client"
                for path in changed_paths
            )

        new_api_cfg = snapshot.api
        new_active = new_api_cfg.get("active_preset")

        if new_active:
            preset_info = next(
                (p for p in new_api_cfg.get("presets", []) if p["name"] == new_active),
                {},
            )
            model_name = preset_info.get("model", "Unknown")
            alias = preset_info.get("alias", "")

            logger.info("\n" + "=" * 50)
            logger.info(f"Model config updated | active preset: {new_active}")
            logger.info(f"Model: {model_name} | Alias: {alias}")
            logger.info("=" * 50 + "\n")

        runtime_apply = None
        if manager.is_running and manager.bot:
            runtime_apply = await manager.reload_runtime_config(
                new_config=effective_config,
                changed_paths=changed_paths,
                force_ai_reload=force_ai_reload,
                strict_active_preset=strict_active_preset,
            )
            if requested_active and runtime_apply.get("success"):
                runtime_apply["requested_preset"] = requested_active

        return jsonify(
            {
                "success": True,
                "config": _build_config_payload(snapshot),
                "changed_paths": changed_paths,
                "reload_plan": reload_plan,
                "runtime_apply": runtime_apply,
                "default_config_synced": True,
                "default_config_sync_message": "default config synced; sensitive values remain in secure sources",
            }
        )

    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/test_connection", methods=["POST"])
async def test_connection():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        preset_name = str(data.get("preset_name") or "").strip()
        patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
        snapshot = config_service.get_snapshot()
        candidate_config = snapshot.to_dict()
        if patch:
            candidate_config = config_service._merge_patch(candidate_config, patch)
        normalized = config_service._validate_config_dict(candidate_config)
        success, resolved_preset, message = await probe_config(normalized, preset_name)
        return jsonify(
            {
                "success": success,
                "preset_name": resolved_preset,
                "message": message,
            }
        )

    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/preview_prompt", methods=["POST"])
async def preview_prompt():
    """Endpoint handler."""
    try:
        data = await request.get_json(silent=True) or {}
        snapshot = config_service.get_snapshot()
        bot_cfg = dict(snapshot.bot)
        bot_overrides = data.get("bot")
        if isinstance(bot_overrides, dict):
            bot_cfg.update(bot_overrides)

        sample = data.get("sample") if isinstance(data.get("sample"), dict) else {}
        chat_id = str(sample.get("chat_id") or "").strip()
        event = SimpleNamespace(
            chat_name=str(sample.get("chat_name") or "preview_contact"),
            sender=str(sample.get("sender") or "preview_user"),
            content=str(sample.get("message") or ""),
            is_group=bool(sample.get("is_group", False)),
        )

        user_profile = None
        wants_contact_context = bool(chat_id or str(sample.get("contact_prompt") or "").strip())
        if bot_cfg.get("profile_inject_in_prompt") or wants_contact_context:
            user_profile = {
                "nickname": str(sample.get("nickname") or event.sender),
                "relationship": str(sample.get("relationship") or "friend"),
                "message_count": int(sample.get("message_count") or 12),
                "profile_summary": str(sample.get("profile_summary") or "").strip(),
                "contact_prompt": str(sample.get("contact_prompt") or "").strip(),
            }
            if chat_id:
                try:
                    mem_mgr = manager.get_memory_manager()
                    stored_profile = await mem_mgr.get_profile_prompt_snapshot(chat_id)
                    if isinstance(stored_profile, dict):
                        user_profile.update(
                            {
                                key: value
                                for key, value in stored_profile.items()
                                if value not in (None, "")
                            }
                        )
                except Exception:
                    pass

        emotion = None
        if bot_cfg.get("emotion_inject_in_prompt"):
            emotion = SimpleNamespace(emotion=str(sample.get("emotion") or "neutral"))

        context = []
        preview = resolve_system_prompt(event, bot_cfg, user_profile, emotion, context)
        overrides = bot_cfg.get("system_prompt_overrides") or {}

        return jsonify(
            {
                "success": True,
                "prompt": preview,
                "summary": {
                    "chars": len(preview),
                    "lines": len(
                        [line for line in preview.splitlines() if line.strip()]
                    ),
                    "override_applied": bool(
                        getattr(event, "chat_name", "") in overrides
                    ),
                    "contact_prompt_applied": bool(
                        isinstance(user_profile, dict)
                        and str(user_profile.get("contact_prompt") or "").strip()
                    ),
                    "profile_injected": bool(
                        bot_cfg.get("profile_inject_in_prompt") and user_profile
                    ),
                    "emotion_injected": emotion is not None,
                },
            }
        )
    except Exception as e:
        logger.error("Request handling failed: %s", e)
        return jsonify({"success": False, "message": f"Request handling failed: {str(e)}"}), 500


@app.route("/api/logs", methods=["GET"])
async def get_logs():
    """Read recent log lines."""
    try:
        snapshot = config_service.get_snapshot()
        log_file = _resolve_log_file_path(snapshot.logging)

        if not log_file.exists():
            return jsonify({"success": True, "logs": []})

        requested_lines = request.args.get("lines", 500, type=int)
        if requested_lines <= 0:
            return jsonify({"success": True, "logs": []})
        lines_count = min(int(requested_lines), MAX_LOG_LINES)

        def _read_logs():
            with open(log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                end = f.tell()
                buffer = b""
                lines = []
                chunk_size = 8192
                while end > 0 and len(lines) <= lines_count:
                    read_size = min(chunk_size, end)
                    end -= read_size
                    f.seek(end)
                    buffer = f.read(read_size) + buffer
                    lines = buffer.splitlines()
                decoded = [
                    line.decode("utf-8", errors="replace").strip()
                    for line in lines
                    if line.strip()
                ]
                return decoded[-lines_count:]

        logs = await asyncio.to_thread(_read_logs)
        safe_logs = [_redact_sensitive_text(line) for line in logs]
        return jsonify({"success": True, "logs": safe_logs})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"failed to read logs: {e}")
        return jsonify({"success": False, "message": "failed to read logs"}), 500

@app.route("/api/logs/clear", methods=["POST"])
async def clear_logs():
    """Truncate the current log file."""
    try:
        snapshot = config_service.get_snapshot()
        log_file = _resolve_log_file_path(snapshot.logging)

        def _clear_file():
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")

        await asyncio.to_thread(_clear_file)
        return jsonify({"success": True, "message": "logs cleared"})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.error(f"failed to clear logs: {e}")
        return jsonify({"success": False, "message": "failed to clear logs"}), 500

async def run_server_async(host="127.0.0.1", port=5000):
    """Endpoint handler."""
    logger.info("API service starting at http://%s:%s", host, port)
    await app.run_task(host=host, port=port)


def run_server(host="127.0.0.1", port=5000, debug=False):
    """Endpoint handler."""
    import asyncio

    logger.info("API service starting at http://%s:%s (debug=%s)", host, port, bool(debug))

    if debug:
        # Enable reloader in debug mode for local development convenience.
        app.run(host=host, port=port, debug=True, use_reloader=True)
    else:
        # Use asyncio runner in production mode.
        asyncio.run(app.run_task(host=host, port=port))


if __name__ == "__main__":
    run_server(debug=True)

