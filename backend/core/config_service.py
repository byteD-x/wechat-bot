"""Centralized configuration snapshots for runtime reads and hot reload."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from backend.utils.config import load_config
from backend.model_catalog import merge_provider_defaults

logger = logging.getLogger(__name__)


def _default_config_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "config.py")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_override_path() -> str:
    return str(_project_root() / "data" / "config_override.json")


_REMOVED_OVERRIDE_PATHS = {
    "agent.history_strategy",
    "bot.capability_strict",
    "bot.compat_ui_enabled",
    "bot.history_log_interval_sec",
    "bot.memory_seed_group",
    "bot.memory_seed_limit",
    "bot.memory_seed_load_more",
    "bot.memory_seed_load_more_interval_sec",
    "bot.memory_seed_on_first_reply",
    "bot.poll_interval_sec",
    "bot.vector_memory_risk_acknowledged",
}


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

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self.config)


class ConfigService:
    """Build, cache, and publish effective configuration snapshots."""

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
        if not isinstance(patch, dict):
            raise TypeError("Config override patch must be a dict")

        resolved_config = os.path.abspath(config_path or _default_config_path())
        resolved_override = os.path.abspath(override_path or _default_override_path())
        with self._lock:
            current_snapshot = self._snapshots.get(resolved_config)
            if current_snapshot is None:
                current_snapshot = self._reload_locked(resolved_config)
            current_config = current_snapshot.to_dict()
            existing_override = self._read_override_file(resolved_override)
            merged_override = self._merge_override_patch(
                existing_override,
                deepcopy(patch),
                current_config=current_config,
            )
            self._prune_removed_paths(merged_override)
            next_config = self._load_effective_config(
                resolved_config,
                override_path=resolved_override,
                override_data=merged_override,
            )
            self._write_override_file(resolved_override, merged_override)
            snapshot = self._build_snapshot(
                resolved_config,
                next_config,
                source=source,
                valid=True,
            )
            self._snapshots[resolved_config] = snapshot
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

    def _reload_locked(self, resolved_path: str) -> ConfigSnapshot:
        try:
            config = self._load_effective_config(resolved_path)
            valid = True
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
            valid=valid,
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

    def _load_effective_config(
        self,
        resolved_path: str,
        *,
        override_path: Optional[str] = None,
        override_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        default_path = os.path.abspath(_default_config_path())
        if resolved_path != default_path:
            return self._validate_config_dict(load_config(resolved_path))

        import backend.config as config_module

        config = deepcopy(config_module.DEFAULT_CONFIG)
        config_module._apply_api_keys(config)
        config_module._apply_prompt_overrides(config)
        config_module._apply_config_overrides(
            config,
            override_file=override_path,
            override_data=override_data,
        )
        config_module._auto_select_active_preset(config)
        return self._validate_config_dict(config)

    def _validate_config_dict(self, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from backend.config_schemas import AppConfig

            return AppConfig(**config).model_dump(mode="json")
        except Exception as exc:
            logger.warning("Config validation failed, keeping raw config: %s", exc)
            return config

    def _read_override_file(self, resolved_override: str) -> Dict[str, Any]:
        if not os.path.exists(resolved_override):
            return {}
        try:
            with open(resolved_override, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            logger.warning("Failed to read config override file %s: %s", resolved_override, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write_override_file(self, resolved_override: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(resolved_override), exist_ok=True)
        with open(resolved_override, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _merge_override_patch(
        self,
        existing: Dict[str, Any],
        patch: Dict[str, Any],
        *,
        current_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = deepcopy(existing if isinstance(existing, dict) else {})
        for section, settings in patch.items():
            if section not in merged:
                merged[section] = {}

            if section == "agent" and isinstance(settings, dict):
                settings = dict(settings)
                settings.pop("langsmith_api_key_configured", None)

            if section == "api" and isinstance(settings, dict) and "presets" in settings:
                settings = dict(settings)
                settings["presets"] = self._merge_override_presets(
                    settings.get("presets"),
                    current_presets=current_config.get("api", {}).get("presets", []),
                    existing_presets=(merged.get("api", {}) or {}).get("presets", []),
                )

            if isinstance(settings, dict):
                if not isinstance(merged.get(section), dict):
                    merged[section] = {}
                merged[section].update(settings)
            else:
                merged[section] = settings
        return merged

    def _merge_override_presets(
        self,
        next_presets: Any,
        *,
        current_presets: Iterable[Any],
        existing_presets: Iterable[Any],
    ) -> Any:
        if not isinstance(next_presets, list):
            return next_presets

        current_list = [dict(p) for p in current_presets if isinstance(p, dict)]
        existing_list = [dict(p) for p in existing_presets if isinstance(p, dict)]
        merged_presets = []
        for preset in next_presets:
            if not isinstance(preset, dict):
                continue
            next_preset = dict(preset)
            preset_name = next_preset.get("name")
            memory_preset = next(
                (item for item in current_list if item.get("name") == preset_name),
                None,
            )
            file_preset = next(
                (item for item in existing_list if item.get("name") == preset_name),
                None,
            )

            if not next_preset.get("provider_id"):
                next_preset["provider_id"] = (memory_preset or {}).get("provider_id") or (
                    file_preset or {}
                ).get("provider_id")

            normalized = merge_provider_defaults(next_preset)
            key = normalized.get("api_key")
            should_restore_key = (
                normalized.get("_keep_key")
                or not key
                or "****" in str(key)
            )
            if should_restore_key:
                restored_key = ""
                if memory_preset and memory_preset.get("api_key"):
                    restored_key = str(memory_preset.get("api_key") or "")
                elif file_preset and file_preset.get("api_key"):
                    restored_key = str(file_preset.get("api_key") or "")
                if restored_key and "****" not in restored_key:
                    normalized["api_key"] = restored_key
                else:
                    normalized.pop("api_key", None)

            for transient_field in ("_keep_key", "api_key_configured", "api_key_masked"):
                normalized.pop(transient_field, None)
            merged_presets.append(normalized)
        return merged_presets

    def _prune_removed_paths(self, payload: Dict[str, Any]) -> None:
        for dotted_path in _REMOVED_OVERRIDE_PATHS:
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


_CONFIG_SERVICE = ConfigService()


def get_config_service() -> ConfigService:
    return _CONFIG_SERVICE
