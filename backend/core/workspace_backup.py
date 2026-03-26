from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from backend.shared_config import ensure_data_root, get_app_config_path, get_project_root


BACKUP_SCHEMA_VERSION = 1
DEFAULT_KEEP_QUICK_BACKUPS = 5
DEFAULT_KEEP_FULL_BACKUPS = 3


def get_app_version() -> str:
    package_path = get_project_root() / "package.json"
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:
        return "0.0.0"
    return str(payload.get("version") or "0.0.0")


class WorkspaceBackupService:
    QUICK_FILES: Tuple[str, ...] = (
        "app_config.json",
        "data/config_override.json",
        "data/api_keys.py",
        "prompt_overrides.py",
        "chat_memory.db",
        "reply_quality_history.db",
        "usage_history.db",
        "pricing_catalog.json",
        "export_rag_manifest.json",
    )
    FULL_DIRS: Tuple[str, ...] = ("chat_exports",)

    def __init__(self, *, data_root: Optional[Path] = None) -> None:
        self.data_root = (data_root or ensure_data_root()).resolve()
        self.backup_root = (self.data_root / "backups" / "workspace").resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.last_restore_result_path = self.backup_root / "last_restore_result.json"

    def list_backups(self, *, limit: int = 20) -> Dict[str, Any]:
        entries = self._load_backup_entries()
        visible_entries = entries[: max(1, int(limit))]
        latest_quick = next((item for item in entries if item.get("mode") == "quick"), None)
        latest_full = next((item for item in entries if item.get("mode") == "full"), None)
        return {
            "success": True,
            "backups": visible_entries,
            "summary": {
                "latest_quick_backup_at": latest_quick.get("created_at") if latest_quick else None,
                "latest_full_backup_at": latest_full.get("created_at") if latest_full else None,
                "latest_backup_size_bytes": entries[0].get("size_bytes") if entries else 0,
                "total_backups": len(entries),
                "quick_backup_count": sum(1 for item in entries if item.get("mode") == "quick"),
                "full_backup_count": sum(1 for item in entries if item.get("mode") == "full"),
                "last_restore_result": self._load_json(self.last_restore_result_path) or None,
            },
        }

    def build_cleanup_plan(
        self,
        *,
        keep_quick: int = DEFAULT_KEEP_QUICK_BACKUPS,
        keep_full: int = DEFAULT_KEEP_FULL_BACKUPS,
        protect_restore_anchor: bool = True,
    ) -> Dict[str, Any]:
        keep_quick = self._normalize_keep_count(keep_quick, field_name="keep_quick")
        keep_full = self._normalize_keep_count(keep_full, field_name="keep_full")
        entries = self._load_backup_entries()
        protected_ids = self._collect_protected_backup_ids() if protect_restore_anchor else set()
        delete_candidates: List[Dict[str, Any]] = []
        preserved_backups: List[Dict[str, Any]] = []

        groups: Dict[str, List[Dict[str, Any]]] = {"quick": [], "full": []}
        for entry in entries:
            mode = str(entry.get("mode") or "").strip().lower()
            if mode in groups:
                groups[mode].append(entry)
            else:
                preserved_backups.append(self._with_cleanup_reason(entry, "unknown_mode"))

        for mode, keep_count in (("quick", keep_quick), ("full", keep_full)):
            for index, entry in enumerate(groups[mode]):
                backup_id = str(entry.get("id") or "").strip()
                if backup_id and backup_id in protected_ids:
                    preserved_backups.append(self._with_cleanup_reason(entry, "protected_restore_anchor"))
                elif index < keep_count:
                    preserved_backups.append(self._with_cleanup_reason(entry, f"keep_latest_{mode}"))
                else:
                    delete_candidates.append(entry)

        delete_candidates = self._sort_backup_entries(delete_candidates)
        preserved_backups = self._sort_backup_entries(preserved_backups)
        reclaimable_bytes = sum(int(item.get("size_bytes") or 0) for item in delete_candidates)
        return {
            "success": True,
            "dry_run": True,
            "keep_policy": {
                "keep_quick": keep_quick,
                "keep_full": keep_full,
                "protect_restore_anchor": bool(protect_restore_anchor),
            },
            "protected_backup_ids": sorted(protected_ids),
            "delete_candidates": delete_candidates,
            "preserved_backups": preserved_backups,
            "candidate_count": len(delete_candidates),
            "reclaimable_bytes": reclaimable_bytes,
        }

    def cleanup_backups(
        self,
        *,
        keep_quick: int = DEFAULT_KEEP_QUICK_BACKUPS,
        keep_full: int = DEFAULT_KEEP_FULL_BACKUPS,
        protect_restore_anchor: bool = True,
        apply: bool = False,
        list_limit: int = 20,
    ) -> Dict[str, Any]:
        plan = self.build_cleanup_plan(
            keep_quick=keep_quick,
            keep_full=keep_full,
            protect_restore_anchor=protect_restore_anchor,
        )
        if not apply:
            listing = self.list_backups(limit=list_limit)
            return {
                **plan,
                "backups": listing.get("backups"),
                "summary": listing.get("summary"),
                "deleted_backups": [],
                "deleted_count": 0,
                "reclaimed_bytes": 0,
            }

        deleted_backups: List[Dict[str, Any]] = []
        reclaimed_bytes = 0
        for entry in list(plan.get("delete_candidates") or []):
            target = self._resolve_cleanup_target(entry)
            reclaimed_bytes += int(entry.get("size_bytes") or 0)
            shutil.rmtree(target)
            deleted_backups.append(entry)

        listing = self.list_backups(limit=list_limit)
        return {
            **plan,
            "success": True,
            "dry_run": False,
            "backups": listing.get("backups"),
            "summary": listing.get("summary"),
            "deleted_backups": deleted_backups,
            "deleted_count": len(deleted_backups),
            "reclaimed_bytes": reclaimed_bytes,
        }

    def create_backup(self, mode: str, *, label: str = "") -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in {"quick", "full"}:
            raise ValueError("mode must be quick or full")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = f"-{self._slugify(label)}" if label else ""
        backup_id = f"{stamp}-{normalized_mode}{suffix}"
        destination_root = self.backup_root / backup_id
        destination_root.mkdir(parents=True, exist_ok=False)

        copied_files: List[str] = []
        checksum_summary: Dict[str, str] = {}
        for source, relative_path in self._collect_sources(normalized_mode):
            target = destination_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                continue
            shutil.copy2(source, target)
            copied_files.append(relative_path.replace("\\", "/"))
            checksum_summary[relative_path.replace("\\", "/")] = self._sha256_file(target)

        manifest = {
            "backup_id": backup_id,
            "app_version": get_app_version(),
            "schema_version": BACKUP_SCHEMA_VERSION,
            "mode": normalized_mode,
            "label": str(label or ""),
            "created_at": int(time.time()),
            "included_files": copied_files,
            "checksum_summary": checksum_summary,
        }
        (destination_root / "backup_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self._backup_entry_from_manifest(destination_root, manifest)

    def resolve_backup(self, backup_ref: str) -> Tuple[Path, Dict[str, Any]]:
        raw = str(backup_ref or "").strip()
        if not raw:
            raise ValueError("backup_id is required")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.backup_root / raw
        candidate = candidate.resolve()
        manifest_path = candidate / "backup_manifest.json"
        manifest = self._load_json(manifest_path)
        if not candidate.exists() or not candidate.is_dir() or not isinstance(manifest, dict):
            raise FileNotFoundError(f"backup not found: {backup_ref}")
        return candidate, manifest

    def build_restore_plan(self, backup_ref: str) -> Dict[str, Any]:
        verification = self.verify_backup(backup_ref)
        return {
            "backup": verification.get("backup"),
            "missing_files": list(verification.get("missing_files") or []),
            "invalid_files": list(verification.get("invalid_files") or []),
            "included_files": list(verification.get("included_files") or []),
            "checksum_missing_files": list(verification.get("checksum_missing_files") or []),
            "checksum_mismatches": list(verification.get("checksum_mismatches") or []),
            "valid": bool(verification.get("valid")),
        }

    def verify_backup(self, backup_ref: str) -> Dict[str, Any]:
        backup_path, manifest = self.resolve_backup(backup_ref)
        included_files: List[str] = []
        invalid_files: List[str] = []
        checksum_summary = manifest.get("checksum_summary")
        checksum_map = dict(checksum_summary or {}) if isinstance(checksum_summary, dict) else {}
        for item in list(manifest.get("included_files") or []):
            raw_path = str(item or "").strip()
            if not raw_path:
                continue
            try:
                normalized_path = self._normalize_backup_relative_path(raw_path)
                self._resolve_restore_target(normalized_path)
                included_files.append(normalized_path)
            except ValueError:
                invalid_files.append(raw_path.replace("\\", "/"))
        missing_files = [
            relative_path
            for relative_path in included_files
            if not (backup_path / relative_path).exists()
        ]
        checksum_missing_files: List[str] = []
        checksum_mismatches: List[Dict[str, str]] = []
        for relative_path in included_files:
            backup_file = backup_path / relative_path
            if not backup_file.exists():
                continue

            expected_checksum = str(checksum_map.get(relative_path) or "").strip().lower()
            if not expected_checksum:
                checksum_missing_files.append(relative_path)
                continue

            actual_checksum = self._sha256_file(backup_file).lower()
            if actual_checksum != expected_checksum:
                checksum_mismatches.append(
                    {
                        "path": relative_path,
                        "expected": expected_checksum,
                        "actual": actual_checksum,
                    }
                )
        return {
            "backup": self._backup_entry_from_manifest(backup_path, manifest),
            "missing_files": missing_files,
            "invalid_files": invalid_files,
            "included_files": included_files,
            "checksum_missing_files": checksum_missing_files,
            "checksum_mismatches": checksum_mismatches,
            "valid": not missing_files and not invalid_files and not checksum_missing_files and not checksum_mismatches,
        }

    def apply_restore(self, backup_ref: str) -> Dict[str, Any]:
        plan = self.build_restore_plan(backup_ref)
        if not plan["valid"]:
            if list(plan.get("invalid_files") or []):
                raise ValueError("backup files contain unsupported paths")
            if list(plan.get("missing_files") or []):
                raise FileNotFoundError("backup files are incomplete")
            raise ValueError("backup checksum verification failed")

        restored_files: List[str] = []
        backup_path, _manifest = self.resolve_backup(backup_ref)
        for relative_path in plan["included_files"]:
            source = backup_path / relative_path
            target = self._resolve_restore_target(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored_files.append(relative_path)
        return {
            "success": True,
            "restored_files": restored_files,
            "restored_count": len(restored_files),
        }

    def save_restore_result(self, payload: Dict[str, Any]) -> None:
        self.last_restore_result_path.write_text(
            json.dumps(payload or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _collect_sources(self, mode: str) -> List[Tuple[Path, str]]:
        sources: List[Tuple[Path, str]] = []
        data_candidates = {
            "app_config.json": Path(get_app_config_path()).resolve(),
            "data/config_override.json": (get_project_root() / "data" / "config_override.json").resolve(),
            "data/api_keys.py": (get_project_root() / "data" / "api_keys.py").resolve(),
            "prompt_overrides.py": (get_project_root() / "prompt_overrides.py").resolve(),
            "chat_memory.db": (self.data_root / "chat_memory.db").resolve(),
            "reply_quality_history.db": (self.data_root / "reply_quality_history.db").resolve(),
            "usage_history.db": (self.data_root / "usage_history.db").resolve(),
            "pricing_catalog.json": (self.data_root / "pricing_catalog.json").resolve(),
            "export_rag_manifest.json": (self.data_root / "export_rag_manifest.json").resolve(),
        }
        for relative_path in self.QUICK_FILES:
            source = data_candidates[relative_path]
            if source.exists() and source.is_file():
                sources.append((source, relative_path))

        if mode == "full":
            for directory_name in self.FULL_DIRS:
                source_dir = self.data_root / directory_name
                if not source_dir.exists() or not source_dir.is_dir():
                    continue
                for file_path in source_dir.rglob("*"):
                    if file_path.is_file():
                        relative_path = str(file_path.relative_to(self.data_root)).replace("\\", "/")
                        sources.append((file_path, relative_path))
        return sources

    def _load_backup_entries(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for path in self.backup_root.iterdir():
            if not path.is_dir():
                continue
            manifest_path = path / "backup_manifest.json"
            if not manifest_path.exists():
                continue
            manifest = self._load_json(manifest_path)
            if not isinstance(manifest, dict):
                continue
            entries.append(self._backup_entry_from_manifest(path, manifest))
        entries.sort(
            key=self._backup_entry_sort_key,
            reverse=True,
        )
        return entries

    @staticmethod
    def _backup_entry_sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
        return (
            int(item.get("created_at") or 0),
            str(item.get("id") or ""),
        )

    @classmethod
    def _sort_backup_entries(cls, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(entries, key=cls._backup_entry_sort_key, reverse=True)

    def _collect_protected_backup_ids(self) -> set[str]:
        payload = self._load_json(self.last_restore_result_path) or {}
        if not isinstance(payload, dict):
            return set()
        pre_restore = payload.get("pre_restore_backup")
        if not isinstance(pre_restore, dict):
            return set()
        backup_id = str(pre_restore.get("id") or "").strip()
        return {backup_id} if backup_id else set()

    def _backup_entry_from_manifest(self, backup_path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
        size_bytes = self._compute_size_bytes(backup_path)
        return {
            "id": str(manifest.get("backup_id") or backup_path.name),
            "path": str(backup_path),
            "mode": str(manifest.get("mode") or ""),
            "label": str(manifest.get("label") or ""),
            "created_at": int(manifest.get("created_at") or 0),
            "size_bytes": size_bytes,
            "included_files": list(manifest.get("included_files") or []),
            "app_version": str(manifest.get("app_version") or ""),
            "schema_version": int(manifest.get("schema_version") or 0),
        }

    @staticmethod
    def _slugify(value: str) -> str:
        text = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_"})
        return text[:32] or "backup"

    @staticmethod
    def _normalize_keep_count(value: Any, *, field_name: str) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer >= 0") from exc
        if numeric < 0:
            raise ValueError(f"{field_name} must be an integer >= 0")
        return numeric

    @staticmethod
    def _with_cleanup_reason(entry: Dict[str, Any], reason: str) -> Dict[str, Any]:
        payload = dict(entry or {})
        payload["cleanup_reason"] = str(reason or "").strip()
        return payload

    def _resolve_cleanup_target(self, entry: Dict[str, Any]) -> Path:
        raw_path = str(entry.get("path") or "").strip()
        target = Path(raw_path).resolve()
        try:
            target.relative_to(self.backup_root)
        except ValueError as exc:
            raise ValueError(f"backup path is outside backup root: {raw_path}") from exc
        if target == self.backup_root or not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"backup not found: {raw_path}")
        return target

    def _resolve_restore_target(self, relative_path: str) -> Path:
        normalized = self._normalize_backup_relative_path(relative_path)
        if normalized == "app_config.json":
            return Path(get_app_config_path()).resolve()
        if normalized == "data/config_override.json":
            return (get_project_root() / "data" / "config_override.json").resolve()
        if normalized == "data/api_keys.py":
            return (get_project_root() / "data" / "api_keys.py").resolve()
        if normalized == "prompt_overrides.py":
            return (get_project_root() / "prompt_overrides.py").resolve()
        if normalized.startswith("chat_exports/") or normalized in {
            "chat_memory.db",
            "reply_quality_history.db",
            "usage_history.db",
            "pricing_catalog.json",
            "export_rag_manifest.json",
        }:
            return (self.data_root / normalized).resolve()
        raise ValueError(f"unsupported backup path: {relative_path}")

    @staticmethod
    def _normalize_backup_relative_path(relative_path: str) -> str:
        raw = str(relative_path or "").replace("\\", "/").strip()
        if not raw:
            raise ValueError("backup path is required")
        if raw.startswith("/"):
            raise ValueError("absolute backup paths are not allowed")

        pure_path = PurePosixPath(raw)
        if any(part == ".." for part in pure_path.parts):
            raise ValueError("backup path cannot escape workspace")
        if pure_path.parts and pure_path.parts[0].endswith(":"):
            raise ValueError("drive-qualified backup paths are not allowed")

        normalized = str(pure_path)
        if normalized in {".", ""}:
            raise ValueError("backup path is required")
        return normalized

    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _compute_size_bytes(path: Path) -> int:
        total = 0
        for file_path in path.rglob("*"):
            if file_path.is_file():
                total += int(file_path.stat().st_size)
        return total

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
