from __future__ import annotations

import atexit
import hashlib
import json
import logging
import threading
import time
from copy import deepcopy
from typing import Any, Dict, Iterable

from backend.core.auth.service import get_auth_provider_statuses
from backend.utils.config_watcher import ConfigReloadWatcher

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 8.0
_DEFAULT_STALE_AFTER_SEC = 20.0
_DEFAULT_WATCH_DEBOUNCE_MS = 1200
_SYNC_SINGLETON: "LocalAuthSyncOrchestrator | None" = None


def _now() -> int:
    return int(time.time())


def _normalize_account_key(local_status: Dict[str, Any], binding: Dict[str, Any]) -> str:
    for value in (
        local_status.get("account_email"),
        local_status.get("account_id"),
        local_status.get("account_label"),
        binding.get("account_id"),
        binding.get("account_label"),
    ):
        normalized = str(value or "").strip().lower()
        if normalized:
            return normalized
    return ""


def _status_fingerprint(local_status: Dict[str, Any], binding: Dict[str, Any]) -> str:
    payload = {
        "configured": bool(local_status.get("configured")),
        "detected": bool(local_status.get("detected")),
        "account_label": str(local_status.get("account_label") or binding.get("account_label") or "").strip(),
        "account_email": str(local_status.get("account_email") or "").strip(),
        "locator_path": str(
            local_status.get("auth_path")
            or local_status.get("oauth_creds_path")
            or local_status.get("google_accounts_path")
            or local_status.get("config_path")
            or local_status.get("managed_settings_path")
            or local_status.get("keychain_locator")
            or local_status.get("private_storage_path")
            or local_status.get("session_path")
            or local_status.get("cookie_path")
            or local_status.get("indexeddb_path")
            or local_status.get("local_storage_path")
            or binding.get("locator_path")
            or ""
        ).strip(),
        "keychain_provider": str(local_status.get("keychain_provider") or "").strip(),
        "keychain_targets": [
            str(item).strip()
            for item in (local_status.get("keychain_targets") or [])
            if str(item).strip()
        ],
        "watch_paths": [
            str(item).strip()
            for item in (local_status.get("watch_paths") or [])
            if str(item).strip()
        ],
        "error": str(local_status.get("error") or "").strip(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _provider_status_fingerprint(status: Dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in dict(status or {}).items()
        if not str(key).startswith("_sync_")
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


class LocalAuthSyncOrchestrator:
    def __init__(
        self,
        *,
        poll_interval_sec: float = _DEFAULT_POLL_INTERVAL_SEC,
        stale_after_sec: float = _DEFAULT_STALE_AFTER_SEC,
    ) -> None:
        self._poll_interval_sec = max(2.0, float(poll_interval_sec or _DEFAULT_POLL_INTERVAL_SEC))
        self._stale_after_sec = max(self._poll_interval_sec, float(stale_after_sec or _DEFAULT_STALE_AFTER_SEC))
        self._lock = threading.RLock()
        self._refresh_run_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None
        self._watcher = ConfigReloadWatcher(
            [],
            debounce_ms=_DEFAULT_WATCH_DEBOUNCE_MS,
            preferred_mode="auto",
        )
        self._snapshot: Dict[str, Any] = {
            "success": True,
            "providers": {},
            "refreshed_at": 0,
            "revision": 0,
            "changed_provider_ids": [],
            "message": "",
            "refreshing": False,
            "pending_reason": "",
            "watcher": self._watcher.get_status(),
        }

    def start(self) -> None:
        with self._lock:
            self._stop_event.clear()
            if not (self._thread and self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name="model-auth-local-sync",
                    daemon=True,
                )
                self._thread.start()
            if not int(self._snapshot.get("refreshed_at") or 0):
                self._schedule_refresh_locked(reason="startup")

    def stop(self) -> None:
        thread = None
        refresh_thread = None
        with self._lock:
            thread = self._thread
            self._thread = None
            refresh_thread = self._refresh_thread
            self._refresh_thread = None
            self._stop_event.set()
            self._watcher.stop()
        if refresh_thread and refresh_thread.is_alive():
            refresh_thread.join(timeout=1.0)
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def get_snapshot(self, *, force_refresh: bool = False, reason: str = "read") -> Dict[str, Any]:
        if force_refresh:
            return self.force_refresh(reason=reason)
        with self._lock:
            snapshot = deepcopy(self._snapshot)
            refreshed_at = int(snapshot.get("refreshed_at") or 0)
            refreshing = bool(snapshot.get("refreshing"))
            if not refreshed_at:
                if not refreshing:
                    self._schedule_refresh_locked(reason=f"lazy_{reason}")
                    snapshot = deepcopy(self._snapshot)
                return snapshot
            if (_now() - refreshed_at) >= int(self._stale_after_sec):
                if not refreshing:
                    self._schedule_refresh_locked(reason=f"stale_{reason}")
                    snapshot = deepcopy(self._snapshot)
                return snapshot
            return snapshot

    def force_refresh(self, *, reason: str = "manual") -> Dict[str, Any]:
        with self._refresh_run_lock:
            with self._lock:
                previous_snapshot = deepcopy(self._snapshot)
            return self._refresh_locked(previous_snapshot=previous_snapshot, reason=reason)

    def _schedule_refresh_locked(self, *, reason: str) -> None:
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
        self._snapshot = {
            **self._snapshot,
            "refreshing": True,
            "pending_reason": str(reason or "").strip(),
        }
        self._refresh_thread = threading.Thread(
            target=self._run_refresh_once,
            args=(str(reason or "").strip() or "background",),
            name="model-auth-local-sync-refresh",
            daemon=True,
        )
        self._refresh_thread.start()

    def _run_refresh_once(self, reason: str) -> None:
        try:
            self.force_refresh(reason=reason)
        except Exception as exc:  # pragma: no cover - background worker should not break callers
            logger.warning("Local auth background refresh failed: %s", exc)
            with self._lock:
                self._snapshot = {
                    **self._snapshot,
                    "success": False,
                    "message": str(exc),
                    "refreshing": False,
                    "pending_reason": "",
                }
        finally:
            with self._lock:
                self._refresh_thread = None

    def _run_loop(self) -> None:
        next_poll_at = time.monotonic() + self._poll_interval_sec
        sleep_interval = min(self._poll_interval_sec, 0.5)
        while not self._stop_event.wait(sleep_interval):
            try:
                reason = ""
                if self._watcher.consume_change():
                    reason = "watchdog_change"
                elif time.monotonic() >= next_poll_at:
                    reason = "poll"
                if not reason:
                    continue
                with self._lock:
                    self._schedule_refresh_locked(reason=reason)
                next_poll_at = time.monotonic() + self._poll_interval_sec
            except Exception as exc:  # pragma: no cover - 守护线程异常仅记录日志
                logger.warning("Local auth sync poll failed: %s", exc)

    def _refresh_locked(self, *, previous_snapshot: Dict[str, Any], reason: str) -> Dict[str, Any]:
        previous_providers = dict(previous_snapshot.get("providers") or {})
        refreshed_at = _now()
        try:
            payload = get_auth_provider_statuses()
        except Exception as exc:
            logger.warning("Failed to refresh local auth snapshot: %s", exc)
            with self._lock:
                self._snapshot = {
                    **self._snapshot,
                    "success": False,
                    "message": str(exc),
                    "refreshed_at": refreshed_at,
                    "changed_provider_ids": [],
                    "refreshing": False,
                    "pending_reason": "",
                }
                return deepcopy(self._snapshot)

        raw_providers = payload.get("providers") if isinstance(payload, dict) else {}
        next_providers: Dict[str, Dict[str, Any]] = {}
        changed_provider_ids: list[str] = []
        previous_revision = int(previous_snapshot.get("revision") or 0)
        next_revision = previous_revision + 1
        all_provider_ids = set(previous_providers.keys())
        if isinstance(raw_providers, dict):
            all_provider_ids.update(str(key) for key in raw_providers.keys())

        for provider_id in sorted(all_provider_ids):
            raw_status = raw_providers.get(provider_id) if isinstance(raw_providers, dict) else None
            current_status = dict(raw_status or {})
            current_fingerprint = _provider_status_fingerprint(current_status)
            previous_status = dict(previous_providers.get(provider_id) or {})
            previous_fingerprint = str(previous_status.get("_sync_fingerprint") or "").strip()
            changed_at = int(previous_status.get("_sync_changed_at") or refreshed_at)
            if current_fingerprint != previous_fingerprint:
                changed_at = refreshed_at
                changed_provider_ids.append(provider_id)
            next_providers[provider_id] = {
                **current_status,
                "_sync_fingerprint": current_fingerprint,
                "_sync_refreshed_at": refreshed_at,
                "_sync_changed_at": changed_at,
                "_sync_revision": next_revision,
                "_sync_reason": reason,
            }

        watch_paths = self._collect_watch_paths(next_providers.values())
        self._watcher.update(paths=watch_paths)
        watcher_status = self._watcher.get_status()
        watch_mode = str(watcher_status.get("mode") or "").strip()
        for status in next_providers.values():
            status["_sync_watch_mode"] = watch_mode

        with self._lock:
            self._snapshot = {
                "success": bool(payload.get("success", True)) if isinstance(payload, dict) else True,
                "providers": next_providers,
                "refreshed_at": refreshed_at,
                "revision": next_revision,
                "changed_provider_ids": changed_provider_ids,
                "message": str(payload.get("message") or "").strip() if isinstance(payload, dict) else "",
                "refreshing": False,
                "pending_reason": "",
                "watcher": {
                    **watcher_status,
                    "watch_path_count": len(watch_paths),
                },
            }
            return deepcopy(self._snapshot)

    @staticmethod
    def _collect_watch_paths(provider_statuses: Iterable[Dict[str, Any]]) -> list[str]:
        watch_paths: set[str] = set()
        for status in provider_statuses:
            for key in (
                "auth_path",
                "oauth_creds_path",
                "google_accounts_path",
                "config_path",
                "managed_settings_path",
                "private_storage_path",
                "session_path",
                "cookie_path",
                "indexeddb_path",
                "local_storage_path",
            ):
                value = str((status or {}).get(key) or "").strip()
                if value:
                    watch_paths.add(value)
            for value in (status or {}).get("watch_paths") or []:
                normalized = str(value or "").strip()
                if normalized:
                    watch_paths.add(normalized)
        return sorted(watch_paths)


def get_local_auth_sync_orchestrator() -> LocalAuthSyncOrchestrator:
    global _SYNC_SINGLETON
    if _SYNC_SINGLETON is None:
        _SYNC_SINGLETON = LocalAuthSyncOrchestrator()
    return _SYNC_SINGLETON


def _shutdown_local_auth_sync_orchestrator() -> None:
    if _SYNC_SINGLETON is not None:
        _SYNC_SINGLETON.stop()


atexit.register(_shutdown_local_auth_sync_orchestrator)


def build_local_sync_state(profile: Dict[str, Any], local_status: Dict[str, Any]) -> Dict[str, Any]:
    binding = dict(profile.get("binding") or {})
    binding_meta = dict(binding.get("metadata") or {})
    previous = dict(binding_meta.get("local_sync") or {})
    current_account_key = _normalize_account_key(local_status, binding)
    previous_account_key = str(previous.get("account_key") or "").strip().lower()
    detected = bool(local_status.get("detected"))
    configured = bool(local_status.get("configured"))
    source_error = str(local_status.get("error") or "").strip()
    source_message = str(local_status.get("message") or source_error or "").strip()
    refreshed_at = int(local_status.get("_sync_refreshed_at") or _now())
    return {
        "fingerprint": str(local_status.get("_sync_fingerprint") or _status_fingerprint(local_status, binding)).strip(),
        "account_key": current_account_key,
        "account_label": str(local_status.get("account_label") or binding.get("account_label") or "").strip(),
        "account_email": str(local_status.get("account_email") or "").strip(),
        "account_switched": bool(
            current_account_key and previous_account_key and current_account_key != previous_account_key
        ),
        "detected": detected,
        "configured": configured,
        "source_missing": not (detected or configured),
        "source_error": source_error,
        "source_message": source_message,
        "last_seen_at": refreshed_at if detected or configured else int(previous.get("last_seen_at") or 0),
        "last_checked_at": refreshed_at,
        "changed_at": int(local_status.get("_sync_changed_at") or refreshed_at),
        "revision": int(local_status.get("_sync_revision") or 0),
        "sync_reason": str(local_status.get("_sync_reason") or "").strip(),
        "watch_mode": str(local_status.get("_sync_watch_mode") or "").strip(),
    }
