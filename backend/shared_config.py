from __future__ import annotations

import json
import os
import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from backend.config import (
    DEFAULT_CONFIG,
    _apply_api_keys,
    _apply_config_overrides,
    _apply_prompt_overrides,
    _auto_select_active_preset,
)

SCHEMA_VERSION = 1
APP_CONFIG_NAME = "app_config.json"
LEGACY_CONFIG_FILES = (
    ("backend/config.py", "backend-config.py"),
    ("data/config_override.json", "config_override.json"),
    ("data/api_keys.py", "api_keys.py"),
    ("prompt_overrides.py", "prompt_overrides.py"),
)
_PATH_FIELDS = (
    ("bot", "memory_db_path"),
    ("bot", "export_rag_dir"),
    ("logging", "file"),
)


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_data_root() -> Path:
    raw = str(os.environ.get("WECHAT_BOT_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (get_project_root() / "data").resolve()


def ensure_data_root() -> Path:
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_app_config_path(config_path: Optional[str] = None) -> str:
    if config_path:
        return str(Path(config_path).expanduser().resolve())
    return str(ensure_data_root() / APP_CONFIG_NAME)


def get_legacy_backup_root() -> Path:
    root = ensure_data_root() / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_model_catalog_path() -> Path:
    return get_project_root() / "shared" / "model_catalog.json"


def atomic_write_json(path: str | Path, payload: Dict[str, Any]) -> None:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path.write_text(rendered, encoding="utf-8")
    os.replace(temp_path, destination)


def _normalize_data_relative_path(value: Any, *, data_root: Path) -> Any:
    if not isinstance(value, str):
        return value
    text = str(value).strip()
    if not text:
        return text
    if "://" in text:
        return text
    candidate = text.replace("\\", "/")
    if os.path.isabs(text):
        return str(Path(text).expanduser().resolve())
    if candidate == "data":
        return str(data_root)
    if candidate.startswith("data/"):
        return str((data_root / candidate[5:]).resolve())
    return text


def normalize_runtime_paths(config: Dict[str, Any], *, data_root: Optional[Path] = None) -> Dict[str, Any]:
    normalized = deepcopy(config if isinstance(config, dict) else {})
    root = data_root or ensure_data_root()
    for section, key in _PATH_FIELDS:
        section_payload = normalized.get(section)
        if not isinstance(section_payload, dict):
            continue
        if key not in section_payload:
            continue
        section_payload[key] = _normalize_data_relative_path(section_payload.get(key), data_root=root)
    return normalized


def build_default_config(*, data_root: Optional[Path] = None) -> Dict[str, Any]:
    payload = deepcopy(DEFAULT_CONFIG)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("services", {"growth_tasks_enabled": False})
    payload["schema_version"] = SCHEMA_VERSION
    payload["services"] = {"growth_tasks_enabled": bool(payload.get("services", {}).get("growth_tasks_enabled", False))}
    return validate_shared_config(payload, data_root=data_root)


def validate_shared_config(config: Dict[str, Any], *, data_root: Optional[Path] = None) -> Dict[str, Any]:
    from backend.config_schemas import AppConfig

    validated = AppConfig(**deepcopy(config or {})).model_dump(mode="json")
    validated["schema_version"] = int(validated.get("schema_version") or SCHEMA_VERSION)
    validated["services"] = {
        "growth_tasks_enabled": bool((validated.get("services") or {}).get("growth_tasks_enabled", False))
    }
    return normalize_runtime_paths(validated, data_root=data_root)


def export_legacy_effective_config(*, data_root: Optional[Path] = None) -> Dict[str, Any]:
    payload = deepcopy(DEFAULT_CONFIG)
    _apply_api_keys(payload)
    _apply_prompt_overrides(payload)
    _apply_config_overrides(payload)
    _auto_select_active_preset(payload)
    payload["schema_version"] = SCHEMA_VERSION
    payload["services"] = {"growth_tasks_enabled": False}
    return validate_shared_config(payload, data_root=data_root)


def backup_legacy_config_files(*, backup_root: Optional[Path] = None) -> Optional[str]:
    project_root = get_project_root()
    existing: list[tuple[Path, str]] = []
    for source_rel, backup_name in LEGACY_CONFIG_FILES:
        source = project_root / source_rel
        if source.exists():
            existing.append((source, backup_name))
    if not existing:
        return None

    root = backup_root or get_legacy_backup_root()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination_root = root / f"legacy-config-{stamp}"
    destination_root.mkdir(parents=True, exist_ok=True)
    for source, backup_name in existing:
        shutil.copy2(source, destination_root / backup_name)
    return str(destination_root)


def migrate_legacy_config(
    *,
    output_path: Optional[str] = None,
    force: bool = False,
    backup: bool = True,
) -> Dict[str, Any]:
    resolved_output = Path(get_app_config_path(output_path))
    if resolved_output.exists() and not force:
        data = json.loads(resolved_output.read_text(encoding="utf-8"))
        return validate_shared_config(data, data_root=get_data_root())

    if backup:
        backup_legacy_config_files()

    payload = export_legacy_effective_config(data_root=get_data_root())
    atomic_write_json(resolved_output, payload)
    return payload


def load_model_catalog() -> Dict[str, Any]:
    return json.loads(get_model_catalog_path().read_text(encoding="utf-8"))
