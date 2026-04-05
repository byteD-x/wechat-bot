"""Centralized shared-config snapshots for runtime reads and hot reload."""

from __future__ import annotations

import logging
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from backend.model_catalog import merge_provider_defaults
from backend.shared_config import (
    atomic_write_json,
    backup_shared_config_file,
    build_default_config,
    get_app_config_path,
    migrate_legacy_config,
    validate_shared_config,
)
from backend.utils.config import load_config

logger = logging.getLogger(__name__)

_REMOVED_CONFIG_PATHS = {
    "agent.history_strategy",
    "agent.streaming_enabled",
    "bot.capability_strict",
    "bot.compat_ui_enabled",
    "bot.transport_backend",
    "bot.history_log_interval_sec",
    "bot.memory_seed_group",
    "bot.memory_seed_limit",
    "bot.memory_seed_load_more",
    "bot.memory_seed_load_more_interval_sec",
    "bot.memory_seed_on_first_reply",
    "bot.poll_interval_sec",
    "bot.reply_empty_fallback_text",
    "bot.reply_error_fallback_text",
    "bot.reply_timeout_fallback_text",
    "bot.stream_buffer_chars",
    "bot.stream_chunk_max_chars",
    "bot.stream_reply",
    "bot.vector_memory_risk_acknowledged",
}


def _default_config_path() -> str:
    return get_app_config_path()


@dataclass(frozen=True)
class ConfigSnapshot:
    version: int
    loaded_at: float
    config_path: str
    source: str
    config: Dict[str, Any]
    valid: bool = True

    @property
    def api(self) -> Dict[str, Any]:
        return self.config.get("api", {})

    @property
    def bot(self) -> Dict[str, Any]:
        return self.config.get("bot", {})

    @property
    def logging(self) -> Dict[str, Any]:
        return self.config.get("logging", {})

    @property
    def agent(self) -> Dict[str, Any]:
        return self.config.get("agent", {})

    @property
    def services(self) -> Dict[str, Any]:
        return self.config.get("services", {})

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self.config)


class ConfigService:
    """Build, cache, merge, and publish shared configuration snapshots."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._version = 0
        self._snapshots: Dict[str, ConfigSnapshot] = {}

    def get_snapshot(
        self,
        *,
        config_path: Optional[str] = None,
        force_reload: bool = False,
    ) -> ConfigSnapshot:
        resolved = os.path.abspath(config_path or _default_config_path())
        with self._lock:
            if force_reload or resolved not in self._snapshots:
                return self._reload_locked(resolved)
            return self._snapshots[resolved]

    def reload(self, *, config_path: Optional[str] = None) -> ConfigSnapshot:
        resolved = os.path.abspath(config_path or _default_config_path())
        with self._lock:
            return self._reload_locked(resolved)

    def update_override(
        self,
        patch: Dict[str, Any],
        *,
        config_path: Optional[str] = None,
        override_path: Optional[str] = None,
        source: str = "override_update",
    ) -> ConfigSnapshot:
        return self.save_effective_config(
            patch,
            config_path=config_path,
            source=source,
        )

    def save_effective_config(
        self,
        patch: Dict[str, Any],
        *,
        config_path: Optional[str] = None,
        override_path: Optional[str] = None,
        api_keys_path: Optional[str] = None,
        source: str = "save_effective_config",
    ) -> ConfigSnapshot:
        if not isinstance(patch, dict):
            raise TypeError("Config patch must be a dict")

        resolved = os.path.abspath(config_path or _default_config_path())
        with self._lock:
            # Rebase persisted writes on the latest on-disk config so small patches
            # do not resurrect stale cached presets or other outdated fields.
            current_snapshot = self._reload_locked(resolved)
            current_config = current_snapshot.to_dict()
            merged = self._merge_patch(current_config, deepcopy(patch))
            self._prune_removed_paths(merged)
            validated = self._validate_config_dict(merged)
            atomic_write_json(resolved, validated)
            snapshot = self._build_snapshot(
                resolved,
                validated,
                source=source,
                valid=True,
            )
            self._snapshots[resolved] = snapshot
            return snapshot

    def publish(
        self,
        config: Dict[str, Any],
        *,
        config_path: Optional[str] = None,
        source: str = "runtime_publish",
    ) -> ConfigSnapshot:
        resolved = os.path.abspath(config_path or _default_config_path())
        with self._lock:
            normalized = self._validate_config_dict(deepcopy(config))
            snapshot = self._build_snapshot(
                resolved,
                normalized,
                source=source,
                valid=True,
            )
            self._snapshots[resolved] = snapshot
            return snapshot

    def sync_default_config_snapshot(
        self,
        config: Dict[str, Any],
        *,
        config_path: Optional[str] = None,
    ) -> bool:
        # Shared JSON config is already the source of truth.
        return False

    def _reload_locked(self, resolved_path: str) -> ConfigSnapshot:
        try:
            config = self._load_effective_config(resolved_path)
        except Exception as exc:
            logger.exception("Config reload failed for %s: %s", resolved_path, exc)
            existing = self._snapshots.get(resolved_path)
            if existing is not None:
                return existing
            raise

        snapshot = self._build_snapshot(
            resolved_path,
            config,
            source="file_reload",
            valid=True,
        )
        self._snapshots[resolved_path] = snapshot
        return snapshot

    def _build_snapshot(
        self,
        resolved_path: str,
        config: Dict[str, Any],
        *,
        source: str,
        valid: bool,
    ) -> ConfigSnapshot:
        self._version += 1
        return ConfigSnapshot(
            version=self._version,
            loaded_at=time.time(),
            config_path=resolved_path,
            source=source,
            config=config,
            valid=valid,
        )

    def _load_effective_config(self, resolved_path: str) -> Dict[str, Any]:
        resolved = Path(resolved_path)
        if not resolved.exists():
            if resolved.name == Path(_default_config_path()).name:
                migrate_legacy_config(output_path=str(resolved), force=False, backup=True)
            else:
                atomic_write_json(resolved, build_default_config())

        loaded = load_config(str(resolved))
        cleaned = deepcopy(loaded if isinstance(loaded, dict) else {})
        self._prune_removed_paths(cleaned)
        validated = self._validate_config_dict(cleaned)
        if cleaned != loaded:
            backup_shared_config_file(resolved)
            atomic_write_json(resolved, validated)
        return validated

    def _validate_config_dict(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return validate_shared_config(config)

    def _merge_patch(self, current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(current if isinstance(current, dict) else {})
        for key, value in (patch or {}).items():
            if key == "schema_version":
                merged["schema_version"] = int(value or 1)
                continue
            if key == "api" and isinstance(value, dict) and "presets" in value:
                value = dict(value)
                value["presets"] = self._merge_presets(
                    current_presets=(merged.get("api") or {}).get("presets", []),
                    next_presets=value.get("presets"),
                )
            if key == "agent" and isinstance(value, dict):
                value = dict(value)
                value.pop("langsmith_api_key_configured", None)
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dicts(merged.get(key) or {}, value)
            else:
                merged[key] = deepcopy(value)
        return merged

    def _deep_merge_dicts(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dicts(merged.get(key) or {}, value)
            else:
                merged[key] = deepcopy(value)
        return merged

    def _merge_presets(
        self,
        *,
        current_presets: Iterable[Any],
        next_presets: Any,
    ) -> Any:
        if not isinstance(next_presets, list):
            return next_presets

        current_list = [dict(item) for item in current_presets if isinstance(item, dict)]
        merged_presets = []
        for item in next_presets:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            preset_name = str(candidate.get("name") or "").strip()
            current_match = next(
                (preset for preset in current_list if str(preset.get("name") or "").strip() == preset_name),
                None,
            )

            if not candidate.get("provider_id"):
                candidate["provider_id"] = (current_match or {}).get("provider_id")
            for field_name in (
                "credential_ref",
                "provider_auth_profile_id",
                "auth_mode",
                "oauth_provider",
                "oauth_source",
                "oauth_binding",
                "oauth_experimental_ack",
                "oauth_project_id",
                "oauth_location",
            ):
                if field_name not in candidate and current_match and field_name in current_match:
                    candidate[field_name] = deepcopy(current_match.get(field_name))

            normalized = merge_provider_defaults(candidate)
            allow_empty_key = bool(normalized.get("allow_empty_key", False))
            raw_key = str(normalized.get("api_key") or "").strip()
            keep_key = bool(normalized.pop("_keep_key", False))

            if allow_empty_key:
                normalized["api_key"] = ""
            elif keep_key or not raw_key or self._is_placeholder_or_masked(raw_key):
                restored = ""
                if current_match and current_match.get("api_key"):
                    restored = str(current_match.get("api_key") or "").strip()
                normalized["api_key"] = restored
            else:
                normalized["api_key"] = raw_key

            normalized.pop("api_key_configured", None)
            normalized.pop("api_key_masked", None)
            merged_presets.append(normalized)
        return merged_presets

    def _prune_removed_paths(self, payload: Dict[str, Any]) -> None:
        for dotted_path in _REMOVED_CONFIG_PATHS:
            self._delete_dotted_path(payload, dotted_path)

    def _delete_dotted_path(self, payload: Dict[str, Any], dotted_path: str) -> None:
        parts = [segment for segment in str(dotted_path).split(".") if segment]
        if not parts:
            return
        cursor: Any = payload
        parents: list[tuple[Dict[str, Any], str]] = []
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor:
                return
            parents.append((cursor, part))
            cursor = cursor.get(part)
        if not isinstance(cursor, dict):
            return
        cursor.pop(parts[-1], None)
        for parent, key in reversed(parents):
            child = parent.get(key)
            if isinstance(child, dict) and not child:
                parent.pop(key, None)
            else:
                break

    @staticmethod
    def _is_placeholder_or_masked(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        return text.startswith("YOUR_") or "****" in text


_CONFIG_SERVICE = ConfigService()


def get_config_service() -> ConfigService:
    return _CONFIG_SERVICE
