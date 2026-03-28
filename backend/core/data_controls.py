from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.shared_config import ensure_data_root, get_project_root


class DataControlService:
    TARGETS: Dict[str, Tuple[Tuple[str, str], ...]] = {
        "memory": (
            ("file", "chat_memory.db"),
            ("file", "reply_quality_history.db"),
            ("dir", "vector_db"),
        ),
        "usage": (
            ("file", "usage_history.db"),
        ),
        "export_rag": (
            ("file", "export_rag_manifest.json"),
            ("dir", "chat_exports"),
        ),
    }

    def __init__(self, *, data_root: Optional[Path] = None, bot_config: Optional[Dict[str, Any]] = None) -> None:
        self.data_root = (data_root or ensure_data_root()).resolve()
        self._targets: Dict[str, Tuple[Tuple[str, Path], ...]] = {}
        self._bot_config: Dict[str, Any] = {}
        self.update_config(bot_config or {})

    def update_config(self, bot_config: Optional[Dict[str, Any]] = None) -> None:
        self._bot_config = dict(bot_config or {})
        self._targets = self._build_targets(self._bot_config)

    def list_supported_scopes(self) -> List[str]:
        return sorted(self._targets.keys())

    def build_clear_plan(
        self,
        scopes: Optional[Iterable[str]] = None,
        *,
        allow_default_all: bool = True,
    ) -> Dict[str, Any]:
        normalized_scopes = self._normalize_scopes(scopes, allow_default_all=allow_default_all)
        targets: List[Dict[str, Any]] = []
        unsupported_targets: List[Dict[str, Any]] = []
        total_bytes = 0

        for scope in normalized_scopes:
            for target_type, target_path in self._targets[scope]:
                relative_path = self._to_display_path(target_path)
                try:
                    self._ensure_within_data_root(target_path)
                except ValueError as exc:
                    unsupported_targets.append(
                        {
                            "scope": scope,
                            "type": target_type,
                            "relative_path": relative_path,
                            "path": str(target_path),
                            "error": str(exc),
                        }
                    )
                    continue
                exists = target_path.exists()
                size_bytes = self._compute_size_bytes(target_path) if exists else 0
                total_bytes += size_bytes
                targets.append(
                    {
                        "scope": scope,
                        "type": target_type,
                        "relative_path": relative_path,
                        "path": str(target_path),
                        "exists": exists,
                        "size_bytes": size_bytes,
                    }
                )

        return {
            "success": True,
            "scopes": normalized_scopes,
            "targets": targets,
            "target_count": len(targets),
            "existing_target_count": sum(1 for item in targets if item.get("exists")),
            "reclaimable_bytes": total_bytes,
            "unsupported_targets": unsupported_targets,
            "unsupported_target_count": len(unsupported_targets),
        }

    def clear(self, scopes: Optional[Iterable[str]] = None, *, apply: bool = False) -> Dict[str, Any]:
        plan = self.build_clear_plan(scopes, allow_default_all=not apply)
        unsupported_targets = list(plan.get("unsupported_targets") or [])
        if not apply:
            return {
                **plan,
                "dry_run": True,
                "deleted_targets": [],
                "deleted_count": 0,
                "reclaimed_bytes": 0,
                "failed_targets": [],
            }

        if unsupported_targets:
            preview = ", ".join(
                str(item.get("relative_path") or item.get("path") or "").strip()
                for item in unsupported_targets[:3]
            ).strip(", ")
            suffix = f": {preview}" if preview else ""
            raise ValueError(f"selected scopes include targets outside data root{suffix}")

        deleted_targets: List[Dict[str, Any]] = []
        failed_targets: List[Dict[str, Any]] = []
        reclaimed_bytes = 0

        for item in plan.get("targets") or []:
            if not item.get("exists"):
                continue
            target_path = Path(str(item.get("path") or "")).resolve()
            try:
                self._ensure_within_data_root(target_path)
                if item.get("type") == "dir":
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
                reclaimed_bytes += int(item.get("size_bytes") or 0)
                deleted_targets.append(item)
            except Exception as exc:
                failed_targets.append(
                    {
                        **item,
                        "error": str(exc),
                    }
                )

        return {
            **plan,
            "success": not failed_targets,
            "dry_run": False,
            "deleted_targets": deleted_targets,
            "deleted_count": len(deleted_targets),
            "reclaimed_bytes": reclaimed_bytes,
            "failed_targets": failed_targets,
        }

    def _normalize_scopes(self, scopes: Optional[Iterable[str]], *, allow_default_all: bool) -> List[str]:
        if scopes is None:
            if allow_default_all:
                return self.list_supported_scopes()
            raise ValueError("scopes is required when apply=true; use ['all'] for full cleanup")

        normalized = []
        for item in scopes:
            value = str(item or "").strip().lower()
            if not value:
                continue
            if value == "all":
                return self.list_supported_scopes()
            if value not in self._targets:
                raise ValueError(f"unsupported scope: {value}")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("scopes cannot be empty")
        return normalized

    def _build_targets(self, bot_config: Dict[str, Any]) -> Dict[str, Tuple[Tuple[str, Path], ...]]:
        memory_db_path = self._resolve_runtime_path(
            bot_config.get("memory_db_path") or bot_config.get("sqlite_db_path"),
            fallback=self.data_root / "chat_memory.db",
        )
        memory_db_wal_path = self._resolve_runtime_path(
            bot_config.get("memory_db_wal_path"),
            fallback=Path(f"{memory_db_path}-wal"),
        )
        memory_db_shm_path = self._resolve_runtime_path(
            bot_config.get("memory_db_shm_path"),
            fallback=Path(f"{memory_db_path}-shm"),
        )
        export_rag_dir = self._resolve_runtime_path(
            bot_config.get("export_rag_dir"),
            fallback=self.data_root / "chat_exports",
        )
        return {
            "memory": (
                ("file", memory_db_path),
                ("file", memory_db_wal_path),
                ("file", memory_db_shm_path),
                ("file", (self.data_root / "reply_quality_history.db").resolve()),
                ("dir", (self.data_root / "vector_db").resolve()),
            ),
            "usage": (
                ("file", (self.data_root / "usage_history.db").resolve()),
            ),
            "export_rag": (
                ("file", (self.data_root / "export_rag_manifest.json").resolve()),
                ("dir", export_rag_dir),
            ),
        }

    def _resolve_runtime_path(self, value: Any, *, fallback: Path) -> Path:
        text = str(value or "").strip()
        if not text:
            return fallback.resolve()
        candidate = Path(text).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        normalized = text.replace("\\", "/")
        if normalized == "data":
            return self.data_root
        if normalized.startswith("data/"):
            return (self.data_root / normalized[5:]).resolve()
        return (get_project_root() / normalized).resolve()

    def _to_display_path(self, target: Path) -> str:
        try:
            return str(target.relative_to(self.data_root)).replace("\\", "/")
        except ValueError:
            return str(target)

    def _ensure_within_data_root(self, target: Path) -> None:
        try:
            target.relative_to(self.data_root)
        except ValueError as exc:
            raise ValueError(f"target path escapes data root: {target}") from exc

    @staticmethod
    def _compute_size_bytes(target: Path) -> int:
        if not target.exists():
            return 0
        if target.is_file():
            return int(target.stat().st_size)

        total = 0
        for child in target.rglob("*"):
            if child.is_file():
                total += int(child.stat().st_size)
        return total
