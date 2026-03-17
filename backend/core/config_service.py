"""Centralized configuration snapshots for runtime reads and hot reload."""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
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


def _default_api_keys_path() -> str:
    return str(_project_root() / "data" / "api_keys.py")


_REMOVED_OVERRIDE_PATHS = {
    "agent.history_strategy",
    "agent.streaming_enabled",
    "bot.capability_strict",
    "bot.compat_ui_enabled",
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

_SENSITIVE_ROOT_FIELDS = {
    "api.api_key",
    "agent.langsmith_api_key",
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
            raise TypeError("Config override patch must be a dict")

        resolved_config = os.path.abspath(config_path or _default_config_path())
        resolved_override = os.path.abspath(override_path or _default_override_path())
        resolved_api_keys = os.path.abspath(api_keys_path or _default_api_keys_path())
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
            next_api_keys = self._merge_api_keys_payload(
                current_config=current_config,
                override_payload=merged_override,
            )
            sanitized_override = self._sanitize_override_payload(merged_override)

            original_config_text = Path(resolved_config).read_text(encoding="utf-8")
            override_exists = os.path.exists(resolved_override)
            original_override_text = (
                Path(resolved_override).read_text(encoding="utf-8")
                if override_exists
                else None
            )
            api_keys_exists = os.path.exists(resolved_api_keys)
            original_api_keys_text = (
                Path(resolved_api_keys).read_text(encoding="utf-8")
                if api_keys_exists
                else None
            )

            try:
                sanitized_default = self._sanitize_default_config_payload(next_config)
                self._write_default_config_file(resolved_config, sanitized_default)
                self._write_override_file(resolved_override, sanitized_override)
                self._write_api_keys_file(resolved_api_keys, next_api_keys)
            except Exception:
                Path(resolved_config).write_text(original_config_text, encoding="utf-8")
                if override_exists and original_override_text is not None:
                    Path(resolved_override).write_text(original_override_text, encoding="utf-8")
                elif not override_exists and os.path.exists(resolved_override):
                    os.remove(resolved_override)
                if api_keys_exists and original_api_keys_text is not None:
                    Path(resolved_api_keys).write_text(original_api_keys_text, encoding="utf-8")
                elif not api_keys_exists and os.path.exists(resolved_api_keys):
                    os.remove(resolved_api_keys)
                raise

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

    def sync_default_config_snapshot(
        self,
        config: Dict[str, Any],
        *,
        config_path: Optional[str] = None,
    ) -> bool:
        """Persist the current effective config back into the default config file."""

        resolved_config = os.path.abspath(config_path or _default_config_path())
        sanitized_default = self._sanitize_default_config_payload(config)
        return self._write_default_config_file(resolved_config, sanitized_default)

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
        import backend.config as config_module

        default_path = os.path.abspath(_default_config_path())
        if resolved_path != default_path:
            config = load_config(resolved_path)
        else:
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

    def _read_api_keys_file(self, resolved_api_keys: str) -> Dict[str, Any]:
        if not os.path.exists(resolved_api_keys):
            return {}
        try:
            spec = importlib.util.spec_from_file_location("config_service_api_keys", resolved_api_keys)
            if spec is None or spec.loader is None:
                return {}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            payload = getattr(module, "API_KEYS", {})
            return deepcopy(payload) if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("Failed to read api keys file %s: %s", resolved_api_keys, exc)
            return {}

    def _write_api_keys_file(self, resolved_api_keys: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(resolved_api_keys), exist_ok=True)
        rendered = f"API_KEYS = {pformat(payload, width=100, sort_dicts=False)}\n"
        Path(resolved_api_keys).write_text(rendered, encoding="utf-8")

    def _extract_api_keys_payload(self, config: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "default": "",
            "presets": {},
        }
        api_cfg = config.get("api") if isinstance(config, dict) else {}
        if isinstance(api_cfg, dict):
            default_key = str(api_cfg.get("api_key") or "").strip()
            if default_key and not self._is_placeholder_or_masked(default_key):
                payload["default"] = default_key

            for preset in api_cfg.get("presets") or []:
                if not isinstance(preset, dict):
                    continue
                name = str(preset.get("name") or "").strip()
                if not name:
                    continue
                if bool(preset.get("allow_empty_key", False)):
                    continue
                key = str(preset.get("api_key") or "").strip()
                if key and not self._is_placeholder_or_masked(key):
                    payload["presets"][name] = key
        return payload

    def _merge_api_keys_payload(
        self,
        *,
        current_config: Dict[str, Any],
        override_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = self._extract_api_keys_payload(current_config)
        api_cfg = override_payload.get("api") if isinstance(override_payload, dict) else {}
        if not isinstance(api_cfg, dict):
            return payload

        default_key = str(api_cfg.get("api_key") or "").strip()
        if default_key and not self._is_placeholder_or_masked(default_key):
            payload["default"] = default_key

        presets = api_cfg.get("presets")
        if not isinstance(presets, list):
            return payload

        for preset in presets:
            if not isinstance(preset, dict):
                continue
            name = str(preset.get("name") or "").strip()
            if not name:
                continue
            if bool(preset.get("allow_empty_key", False)):
                payload["presets"].pop(name, None)
                continue
            key = str(preset.get("api_key") or "").strip()
            if key and not self._is_placeholder_or_masked(key):
                payload["presets"][name] = key
        return payload

    def _sanitize_override_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = deepcopy(payload if isinstance(payload, dict) else {})
        self._delete_dotted_path(sanitized, "api.api_key")
        self._delete_dotted_path(sanitized, "agent.langsmith_api_key")

        api_cfg = sanitized.get("api")
        if isinstance(api_cfg, dict):
            presets = api_cfg.get("presets")
            if isinstance(presets, list):
                for preset in presets:
                    if isinstance(preset, dict):
                        preset.pop("api_key", None)
        return sanitized

    def _sanitize_default_config_payload(self, config: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = deepcopy(config if isinstance(config, dict) else {})
        for dotted_path in _SENSITIVE_ROOT_FIELDS:
            self._set_dotted_path(
                sanitized,
                dotted_path,
                self._placeholder_for_sensitive_path(dotted_path),
            )

        api_cfg = sanitized.get("api")
        if isinstance(api_cfg, dict):
            for preset in api_cfg.get("presets") or []:
                if not isinstance(preset, dict):
                    continue
                if bool(preset.get("allow_empty_key", False)):
                    preset["api_key"] = ""
                else:
                    preset["api_key"] = self._placeholder_for_preset(preset)
        return sanitized

    def _write_default_config_file(self, resolved_config: str, payload: Dict[str, Any]) -> bool:
        if not str(resolved_config).lower().endswith(".py"):
            raise ValueError(f"default config sync only supports .py files: {resolved_config}")

        source = Path(resolved_config).read_text(encoding="utf-8")
        module = ast.parse(source)
        config_assign = next(
            (
                node for node in module.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "CONFIG" for target in node.targets)
            ),
            None,
        )
        if config_assign is None:
            raise ValueError(f"CONFIG assignment not found in {resolved_config}")

        lines = source.splitlines()
        start_index = int(config_assign.lineno) - 1
        end_index = int(getattr(config_assign, "end_lineno", config_assign.lineno)) - 1
        rendered = f"CONFIG = {pformat(payload, width=100, sort_dicts=False)}"
        updated_lines = lines[:start_index] + [rendered] + lines[end_index + 1 :]
        next_source = "\n".join(updated_lines) + "\n"
        if next_source == source:
            return False
        Path(resolved_config).write_text(next_source, encoding="utf-8")
        return True

    def _set_dotted_path(self, payload: Dict[str, Any], dotted_path: str, value: Any) -> None:
        parts = [segment for segment in str(dotted_path).split(".") if segment]
        if not parts:
            return
        cursor: Any = payload
        for part in parts[:-1]:
            if not isinstance(cursor, dict):
                return
            next_cursor = cursor.get(part)
            if not isinstance(next_cursor, dict):
                next_cursor = {}
                cursor[part] = next_cursor
            cursor = next_cursor
        if isinstance(cursor, dict):
            cursor[parts[-1]] = value

    @staticmethod
    def _placeholder_for_sensitive_path(dotted_path: str) -> str:
        if dotted_path == "agent.langsmith_api_key":
            return ""
        return "YOUR_API_KEY"

    @staticmethod
    def _placeholder_for_preset(preset: Dict[str, Any]) -> str:
        raw_name = str(
            preset.get("name")
            or preset.get("provider_id")
            or "API"
        ).upper()
        normalized = "".join(char if char.isalnum() else "_" for char in raw_name).strip("_")
        return f"YOUR_{normalized or 'API'}_KEY"

    @staticmethod
    def _is_placeholder_or_masked(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        return text.startswith("YOUR_") or "****" in text

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
