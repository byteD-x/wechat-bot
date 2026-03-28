from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.core.config_audit import build_reload_plan, diff_config_paths
from backend.shared_config import ensure_data_root
from backend.utils.common import as_int

CHAT_EXPORT_SUBDIR = "聊天记录"


@dataclass
class _ResolvedApplyPlan:
    bot_patch: Dict[str, Any]
    preview_bot: Dict[str, Any]


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return str(Path(text).expanduser())


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _decrypt_version_list_path() -> Path:
    return _repo_root() / "tools" / "wx_db" / "decrypt" / "version_list.json"


class WechatExportService:
    def __init__(self):
        self._probe_refs: Dict[str, Dict[str, Any]] = {}
        self._probe_lock = asyncio.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._jobs_lock = asyncio.Lock()

    async def probe(self) -> Dict[str, Any]:
        warnings: List[str] = []
        version_list: Dict[str, Any] = {}
        version_path = _decrypt_version_list_path()
        if version_path.exists():
            try:
                version_list = json.loads(version_path.read_text(encoding="utf-8"))
            except Exception as exc:
                warnings.append(f"failed_to_load_version_list:{exc}")
        else:
            warnings.append("version_list_missing")

        get_info = None
        try:
            from tools.wx_db.decrypt.get_wx_info import get_info as _get_info

            get_info = _get_info
        except Exception as exc:
            warnings.append(f"decrypt_probe_dependency_unavailable:{exc}")

        raw_accounts: List[Dict[str, Any]] = []
        if get_info is not None:
            try:
                payload = await asyncio.to_thread(get_info, version_list)
                if isinstance(payload, list):
                    raw_accounts = [item for item in payload if isinstance(item, dict)]
            except Exception as exc:
                warnings.append(f"decrypt_probe_failed:{exc}")

        normalized_accounts: List[Dict[str, Any]] = []
        now_ts = time.time()
        async with self._probe_lock:
            self._probe_refs = {}
            for item in raw_accounts:
                probe_ref = f"probe_{secrets.token_hex(8)}"
                wxid = str(item.get("wxid") or "").strip()
                wx_dir = _normalize_path(item.get("wx_dir"))
                db_dir_hint = str((Path(wx_dir) / "Msg").resolve()) if wx_dir else ""
                key = str(item.get("key") or "").strip()
                account_payload = {
                    "probe_ref": probe_ref,
                    "wxid": wxid,
                    "name": str(item.get("name") or "").strip(),
                    "account": str(item.get("account") or "").strip(),
                    "mobile": str(item.get("mobile") or "").strip(),
                    "version": str(item.get("version") or "").strip(),
                    "wx_dir": wx_dir,
                    "db_dir_hint": db_dir_hint,
                    "has_key": bool(key and key.lower() != "none"),
                    "errcode": as_int(item.get("errcode", 0), 0, min_value=0),
                    "errmsg": str(item.get("errmsg") or "").strip(),
                }
                self._probe_refs[probe_ref] = {
                    **item,
                    "wxid": wxid,
                    "wx_dir": wx_dir,
                    "db_dir_hint": db_dir_hint,
                    "_saved_at": now_ts,
                }
                normalized_accounts.append(account_payload)

        normalized_accounts.sort(
            key=lambda value: (
                0 if value.get("has_key") else 1,
                str(value.get("name") or ""),
                str(value.get("wxid") or ""),
            )
        )
        return {
            "success": True,
            "dependency_ready": get_info is not None,
            "accounts": normalized_accounts,
            "warnings": warnings,
            "scanned_at": int(now_ts),
        }

    async def start_decrypt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        probe_ref = str(payload.get("probe_ref") or "").strip()
        db_version = as_int(payload.get("db_version", 4), 4, min_value=3)
        if db_version not in {3, 4}:
            raise ValueError("db_version must be 3 or 4")

        base_info: Dict[str, Any] = {}
        if probe_ref:
            async with self._probe_lock:
                base_info = dict(self._probe_refs.get(probe_ref) or {})
            if not base_info:
                raise ValueError("invalid probe_ref")

        wxid = str(payload.get("wxid") or base_info.get("wxid") or "").strip() or "unknown"
        key = str(payload.get("key") or base_info.get("key") or "").strip()
        if not key or key.lower() == "none":
            raise ValueError("missing db key; run probe first and choose an account with valid key")

        src_dir = _normalize_path(payload.get("src_dir") or base_info.get("db_dir_hint"))
        if not src_dir:
            raise ValueError("missing src_dir")
        if not os.path.isdir(src_dir):
            raise ValueError(f"src_dir not found: {src_dir}")

        data_root = ensure_data_root()
        default_dest = data_root / "decrypted_wechat" / wxid / "Msg"
        dest_dir = _normalize_path(payload.get("dest_dir") or default_dest)
        if not dest_dir:
            raise ValueError("missing dest_dir")

        job_id = f"wxexp_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        job_payload = {
            "job_id": job_id,
            "success": True,
            "status": "queued",
            "stage": "queued",
            "message": "decrypt job queued",
            "db_version": db_version,
            "wxid": wxid,
            "src_dir": src_dir,
            "dest_dir": dest_dir,
            "started_at": None,
            "finished_at": None,
            "decrypted_db_files": 0,
            "error": "",
        }

        async with self._jobs_lock:
            self._jobs[job_id] = job_payload

        asyncio.create_task(
            self._run_decrypt_job(
                job_id=job_id,
                key=key,
                db_version=db_version,
                src_dir=src_dir,
                dest_dir=dest_dir,
            )
        )
        return dict(job_payload)

    async def get_decrypt_job(self, job_id: str) -> Dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("missing job_id")
        async with self._jobs_lock:
            payload = self._jobs.get(normalized_job_id)
            if not payload:
                return {"success": False, "message": "decrypt job not found", "job_id": normalized_job_id}
            return dict(payload)

    async def list_contacts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_dir = _normalize_path(payload.get("db_dir"))
        if not db_dir:
            raise ValueError("missing db_dir")
        if not os.path.isdir(db_dir):
            raise ValueError(f"db_dir not found: {db_dir}")
        db_version = as_int(payload.get("db_version", 4), 4, min_value=3)
        if db_version not in {3, 4}:
            raise ValueError("db_version must be 3 or 4")
        include_chatrooms = _to_bool(payload.get("include_chatrooms"), False)
        keyword = str(payload.get("keyword") or "").strip().lower()

        contacts = await asyncio.to_thread(
            self._collect_contacts_sync,
            db_dir,
            db_version,
            include_chatrooms,
            keyword,
        )
        return {
            "success": True,
            "db_dir": db_dir,
            "db_version": db_version,
            "include_chatrooms": include_chatrooms,
            "contacts": contacts,
            "total": len(contacts),
        }

    async def export_contacts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_dir = _normalize_path(payload.get("db_dir"))
        if not db_dir:
            raise ValueError("missing db_dir")
        if not os.path.isdir(db_dir):
            raise ValueError(f"db_dir not found: {db_dir}")
        db_version = as_int(payload.get("db_version", 4), 4, min_value=3)
        if db_version not in {3, 4}:
            raise ValueError("db_version must be 3 or 4")
        include_chatrooms = _to_bool(payload.get("include_chatrooms"), False)
        output_dir = _normalize_path(payload.get("output_dir"))
        if not output_dir:
            output_dir = str((ensure_data_root() / "chat_exports").resolve())
        output_dir = self._normalize_export_output_dir(output_dir)

        raw_contacts = payload.get("contacts")
        contact_filters = []
        if isinstance(raw_contacts, list):
            contact_filters = [str(item or "").strip() for item in raw_contacts if str(item or "").strip()]
        if not contact_filters:
            raise ValueError("contacts is required")

        start = str(payload.get("start") or "").strip()
        end = str(payload.get("end") or "").strip()
        if bool(start) ^ bool(end):
            raise ValueError("start and end must be provided together")
        if start and end:
            self._validate_time_text(start, field_name="start")
            self._validate_time_text(end, field_name="end")
        time_range: Optional[Tuple[str, str]] = (start, end) if start and end else None

        result = await asyncio.to_thread(
            self._export_contacts_sync,
            db_dir,
            db_version,
            output_dir,
            contact_filters,
            include_chatrooms,
            time_range,
        )
        return {
            "success": True,
            "db_dir": db_dir,
            "db_version": db_version,
            "output_dir": output_dir,
            "rag_dir": str(Path(output_dir) / CHAT_EXPORT_SUBDIR),
            "include_chatrooms": include_chatrooms,
            "requested_contacts": contact_filters,
            **result,
        }

    async def preview_apply(self, payload: Dict[str, Any], *, config_service: Any) -> Dict[str, Any]:
        snapshot = config_service.get_snapshot()
        current_config = snapshot.to_dict()
        plan = self._resolve_apply_plan(payload)
        merged = config_service._merge_patch(current_config, {"bot": plan.bot_patch})
        normalized = config_service._validate_config_dict(merged)
        changed_paths = diff_config_paths(current_config, normalized)
        return {
            "success": True,
            "bot_preview": plan.preview_bot,
            "changed_paths": changed_paths,
            "changed_count": len(changed_paths),
            "reload_plan": build_reload_plan(changed_paths),
        }

    async def apply(
        self,
        payload: Dict[str, Any],
        *,
        config_service: Any,
        manager: Any,
    ) -> Dict[str, Any]:
        snapshot = config_service.get_snapshot()
        current_config = snapshot.to_dict()
        plan = self._resolve_apply_plan(payload)
        config_path = getattr(manager, "config_path", None)
        if not isinstance(config_path, str) or not config_path.strip():
            config_path = None

        next_snapshot = await asyncio.to_thread(
            config_service.save_effective_config,
            {"bot": plan.bot_patch},
            config_path,
            "wechat_export_apply",
        )
        effective_config = next_snapshot.to_dict()
        changed_paths = diff_config_paths(current_config, effective_config)
        reload_plan = build_reload_plan(changed_paths)

        force_ai_reload = any(
            item.get("component") == "ai_client" for item in reload_plan
        )

        runtime_apply = None
        if manager.is_running and manager.bot:
            runtime_apply = await manager.reload_runtime_config(
                new_config=effective_config,
                changed_paths=changed_paths,
                force_ai_reload=force_ai_reload,
                strict_active_preset=False,
            )

        sync_result = None
        if _to_bool(payload.get("run_sync"), True):
            try:
                sync_result = await manager.run_growth_task_now("export_rag_sync")
            except Exception as exc:
                sync_result = {"success": False, "message": f"export_rag_sync_failed:{exc}"}

        return {
            "success": True,
            "bot_preview": plan.preview_bot,
            "changed_paths": changed_paths,
            "changed_count": len(changed_paths),
            "reload_plan": reload_plan,
            "runtime_apply": runtime_apply,
            "sync_result": sync_result,
            "default_config_synced": True,
            "default_config_sync_message": "default config synced; sensitive values remain in secure sources",
        }

    async def _run_decrypt_job(
        self,
        *,
        job_id: str,
        key: str,
        db_version: int,
        src_dir: str,
        dest_dir: str,
    ) -> None:
        await self._update_job(
            job_id,
            status="running",
            stage="decrypting",
            message="decrypting database files",
            started_at=time.time(),
            error="",
        )
        try:
            await asyncio.to_thread(self._decrypt_sync, key, db_version, src_dir, dest_dir)
            decrypted_count = await asyncio.to_thread(self._count_db_files, dest_dir)
            if decrypted_count <= 0:
                raise RuntimeError("no decrypted database file generated")
            await self._update_job(
                job_id,
                status="succeeded",
                stage="completed",
                message="decrypt completed",
                decrypted_db_files=decrypted_count,
                finished_at=time.time(),
            )
        except Exception as exc:
            await self._update_job(
                job_id,
                success=False,
                status="failed",
                stage="failed",
                message="decrypt failed",
                error=str(exc),
                finished_at=time.time(),
            )

    async def _update_job(self, job_id: str, **changes: Any) -> None:
        async with self._jobs_lock:
            payload = self._jobs.get(job_id)
            if not payload:
                return
            payload.update(changes)

    def _decrypt_sync(self, key: str, db_version: int, src_dir: str, dest_dir: str) -> None:
        os.makedirs(dest_dir, exist_ok=True)
        if db_version == 4:
            from tools.wx_db.decrypt.decrypt_v4 import decrypt_db_files as _decrypt
        else:
            from tools.wx_db.decrypt.decrypt_v3 import decrypt_db_files as _decrypt
        _decrypt(key, src_dir, dest_dir)

    def _collect_contacts_sync(
        self,
        db_dir: str,
        db_version: int,
        include_chatrooms: bool,
        keyword: str,
    ) -> List[Dict[str, Any]]:
        from tools.chat_exporter.cli import is_exportable_contact
        from tools.wx_db import DatabaseConnection

        conn = DatabaseConnection(db_dir, db_version)
        database = conn.get_interface()
        if database is None:
            raise RuntimeError("db init failed: check db_dir/db_version")

        rows: List[Dict[str, Any]] = []
        for contact in database.get_contacts() or []:
            if not is_exportable_contact(contact, include_chatrooms):
                continue
            remark = str(getattr(contact, "remark", "") or "").strip()
            nickname = str(getattr(contact, "nickname", "") or "").strip()
            alias = str(getattr(contact, "alias", "") or "").strip()
            wxid = str(getattr(contact, "wxid", "") or "").strip()
            if keyword:
                haystack = " ".join([remark, nickname, alias, wxid]).lower()
                if keyword not in haystack:
                    continue
            label = remark or nickname or alias or wxid
            rows.append(
                {
                    "wxid": wxid,
                    "remark": remark,
                    "nickname": nickname,
                    "alias": alias,
                    "display_name": label,
                    "is_chatroom": bool(contact.is_chatroom()),
                }
            )
        rows.sort(key=lambda item: (str(item.get("display_name") or ""), str(item.get("wxid") or "")))
        return rows

    def _export_contacts_sync(
        self,
        db_dir: str,
        db_version: int,
        output_dir: str,
        filters: List[str],
        include_chatrooms: bool,
        time_range: Optional[Tuple[str, str]],
    ) -> Dict[str, Any]:
        from tools.chat_exporter.cli import collect_contacts
        from tools.chat_exporter.csv_exporter import CSVExporter
        from tools.wx_db import DatabaseConnection

        conn = DatabaseConnection(db_dir, db_version)
        database = conn.get_interface()
        if database is None:
            raise RuntimeError("db init failed: check db_dir/db_version")
        os.makedirs(output_dir, exist_ok=True)

        contacts = collect_contacts(database, filters, include_chatrooms)
        if not contacts:
            raise RuntimeError("no contacts matched the filter")

        exported_files: List[str] = []
        for contact in contacts:
            exporter = CSVExporter(
                database=database,
                contact=contact,
                output_dir=output_dir,
                message_types=None,
                time_range=time_range,
                group_members=None,
            )
            exported_path = exporter.start()
            exported_files.append(str(exported_path))

        return {
            "exported_contacts": len(contacts),
            "exported_files": exported_files,
        }

    def _resolve_apply_plan(self, payload: Dict[str, Any]) -> _ResolvedApplyPlan:
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            settings = dict(payload or {})

        default_export_dir = str((ensure_data_root() / "chat_exports" / CHAT_EXPORT_SUBDIR).resolve())
        export_dir = _normalize_path(settings.get("export_rag_dir")) or default_export_dir
        top_k = as_int(settings.get("export_rag_top_k", 3), 3, min_value=1)
        max_chunks = as_int(
            settings.get("export_rag_max_chunks_per_chat", 500),
            500,
            min_value=1,
        )
        auto_ingest = _to_bool(settings.get("export_rag_auto_ingest"), True)
        rag_enabled = _to_bool(settings.get("rag_enabled"), True)
        export_enabled = _to_bool(settings.get("export_rag_enabled"), True)
        embedding_model = str(settings.get("vector_memory_embedding_model") or "").strip()

        bot_patch: Dict[str, Any] = {
            "rag_enabled": rag_enabled,
            "export_rag_enabled": export_enabled,
            "export_rag_auto_ingest": auto_ingest,
            "export_rag_dir": export_dir,
            "export_rag_top_k": top_k,
            "export_rag_max_chunks_per_chat": max_chunks,
        }
        if embedding_model:
            bot_patch["vector_memory_embedding_model"] = embedding_model
        elif _to_bool(settings.get("clear_vector_memory_embedding_model"), False):
            bot_patch["vector_memory_embedding_model"] = ""

        return _ResolvedApplyPlan(
            bot_patch=bot_patch,
            preview_bot={
                "rag_enabled": rag_enabled,
                "export_rag_enabled": export_enabled,
                "export_rag_auto_ingest": auto_ingest,
                "export_rag_dir": export_dir,
                "export_rag_top_k": top_k,
                "export_rag_max_chunks_per_chat": max_chunks,
                "vector_memory_embedding_model": embedding_model,
            },
        )

    def _normalize_export_output_dir(self, output_dir: str) -> str:
        path = Path(str(output_dir or "").strip())
        if str(path.name) == CHAT_EXPORT_SUBDIR:
            parent = str(path.parent).strip()
            if parent and parent not in {".", ""}:
                return parent
        return str(path)

    def _validate_time_text(self, value: str, *, field_name: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        try:
            time.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"invalid {field_name}; expected format: YYYY-MM-DD HH:MM:SS") from exc

    def _count_db_files(self, base_dir: str) -> int:
        total = 0
        for _root, _dirs, files in os.walk(base_dir):
            for filename in files:
                if filename.lower().endswith(".db"):
                    total += 1
        return total
