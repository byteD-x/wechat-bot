"""
导出聊天记录驱动的个性化 RAG。

目标：
- 自动扫描 `data/chat_exports/聊天记录`
- 为导出语料建立联系人级风格向量索引
- 在回复前按联系人召回本人历史表达片段
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.shared_config import ensure_data_root
from backend.utils.common import as_float, as_int
from tools.prompt_gen.csv_loader import (
    EXCLUDED_CONTACTS,
    extract_contact_name,
    is_text_record,
    load_chat_from_csv,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExportChunk:
    chat_id: str
    contact_name: str
    source_file: str
    text: str
    timestamp: float
    chunk_index: int


class ExportChatRAG:
    """管理导出聊天记录索引与检索。"""

    def __init__(self, vector_memory: Any):
        self.vector_memory = vector_memory
        self.enabled = False
        data_root = ensure_data_root()
        self.base_dir = str(data_root / "chat_exports" / "聊天记录")
        self.auto_ingest = True
        self.max_chunks_per_chat = 500
        self.chunk_messages = 6
        self.top_k = 3
        self.min_score = 1.0
        self.max_context_chars = 900
        self.prefer_recent = True
        self.max_parallel_embeddings = 4
        self.self_name = "知有"
        self.manifest_path = str(data_root / "export_rag_manifest.json")

        self.last_scan_at: Optional[float] = None
        self.last_scan_summary: Dict[str, Any] = {}
        self.indexed_contacts = 0
        self.indexed_chunks = 0

    def update_config(self, bot_cfg: Dict[str, Any]) -> None:
        self.enabled = bool(bot_cfg.get("export_rag_enabled", False))
        data_root = ensure_data_root()
        self.base_dir = str(
            bot_cfg.get("export_rag_dir") or (data_root / "chat_exports" / "聊天记录")
        ).strip()
        self.auto_ingest = bool(bot_cfg.get("export_rag_auto_ingest", True))
        self.max_chunks_per_chat = as_int(
            bot_cfg.get("export_rag_max_chunks_per_chat", 500), 500, min_value=1
        )
        self.chunk_messages = as_int(
            bot_cfg.get("export_rag_chunk_messages", 6), 6, min_value=1
        )
        self.top_k = as_int(bot_cfg.get("export_rag_top_k", 3), 3, min_value=1)
        self.min_score = as_float(
            bot_cfg.get("export_rag_min_score", 1.0), 1.0, min_value=0.0
        )
        self.max_context_chars = as_int(
            bot_cfg.get("export_rag_max_context_chars", 900), 900, min_value=120
        )
        self.prefer_recent = bool(bot_cfg.get("export_rag_prefer_recent", True))
        self.max_parallel_embeddings = as_int(
            bot_cfg.get("export_rag_max_parallel_embeddings", 4), 4, min_value=1
        )
        self.self_name = str(bot_cfg.get("self_name") or "知有").strip() or "知有"

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_dir": self.base_dir,
            "auto_ingest": self.auto_ingest,
            "indexed_contacts": self.indexed_contacts,
            "indexed_chunks": self.indexed_chunks,
            "last_scan_at": self.last_scan_at,
            "last_scan_summary": dict(self.last_scan_summary),
        }

    async def sync(
        self,
        ai_client: Any,
        *,
        force: bool = False,
        priority: str = "foreground",
    ) -> Dict[str, Any]:
        started_at = time.time()
        summary = {
            "success": True,
            "reason": "",
            "scanned_files": 0,
            "indexed_contacts": 0,
            "indexed_chunks": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "duration_sec": 0.0,
        }

        if not self.enabled:
            summary["reason"] = "disabled"
            return self._finish_scan(summary, started_at)
        if not self.vector_memory:
            summary["reason"] = "vector_memory_unavailable"
            return self._finish_scan(summary, started_at)
        if not ai_client or not getattr(ai_client, "embedding_model", None):
            summary["reason"] = "embedding_unavailable"
            return self._finish_scan(summary, started_at)
        if not self.base_dir or not os.path.isdir(self.base_dir):
            summary["reason"] = "export_dir_missing"
            return self._finish_scan(summary, started_at)

        manifest = await asyncio.to_thread(self._load_manifest)
        next_manifest: Dict[str, Dict[str, Any]] = {}
        targets = await asyncio.to_thread(self._discover_targets)
        summary["scanned_files"] = sum(len(target["csv_paths"]) for target in targets)

        for target in targets:
            manifest_key = target["manifest_key"]
            signature = target["signature"]
            chat_id = target["chat_id"]
            previous = manifest.get(manifest_key)

            if not force and previous and previous.get("signature") == signature:
                next_manifest[manifest_key] = previous
                summary["skipped_files"] += 1
                continue

            try:
                records = await asyncio.to_thread(
                    self._load_contact_records,
                    target["csv_paths"],
                )
                chunks = self._build_chunks(
                    chat_id=chat_id,
                    contact_name=target["contact_name"],
                    source_file=" | ".join(target["relative_paths"]),
                    records=records,
                )
                await asyncio.to_thread(
                    self.vector_memory.delete,
                    {"chat_id": chat_id, "source": "export_chat"},
                )
                indexed_count = await self._index_chunks(ai_client, chunks, priority=priority)
                next_manifest[manifest_key] = {
                    "signature": signature,
                    "chat_id": chat_id,
                    "contact_name": target["contact_name"],
                    "chunks": indexed_count,
                }
                summary["indexed_contacts"] += 1
                summary["indexed_chunks"] += indexed_count
            except Exception as exc:
                summary["failed_files"] += 1
                logger.warning(
                    "导出语料索引失败 [%s]: %s",
                    target["contact_name"],
                    exc,
                )

        removed_paths = set(manifest) - set(next_manifest)
        for relative_path in removed_paths:
            previous = manifest.get(relative_path)
            if not isinstance(previous, dict):
                continue
            chat_id = str(previous.get("chat_id") or "").strip()
            if not chat_id:
                continue
            await asyncio.to_thread(
                self.vector_memory.delete,
                {"chat_id": chat_id, "source": "export_chat"},
            )

        await asyncio.to_thread(self._save_manifest, next_manifest)
        self.indexed_contacts = len(next_manifest)
        self.indexed_chunks = sum(
            as_int(item.get("chunks", 0), 0, min_value=0)
            for item in next_manifest.values()
            if isinstance(item, dict)
        )
        return self._finish_scan(summary, started_at)

    async def search(
        self,
        ai_client: Any,
        chat_id: str,
        query_text: str,
        *,
        chat_id_aliases: Optional[Sequence[str]] = None,
        priority: str = "foreground",
    ) -> List[Dict[str, Any]]:
        if not self.enabled or not self.vector_memory or not ai_client:
            return []
        if not chat_id.startswith("friend:"):
            return []
        query = str(query_text or "").strip()
        if not query:
            return []

        embedding = await ai_client.get_embedding(query, priority=priority)
        if not embedding:
            return []

        candidate_chat_ids: List[str] = []
        for candidate in [chat_id, *(list(chat_id_aliases or []))]:
            normalized = str(candidate or "").strip()
            if not normalized or not normalized.startswith("friend:") or normalized in candidate_chat_ids:
                continue
            candidate_chat_ids.append(normalized)

        results: List[Dict[str, Any]] = []
        for candidate_chat_id in candidate_chat_ids:
            matched = await asyncio.to_thread(
                self.vector_memory.search,
                n_results=max(self.top_k * 2, self.top_k),
                filter_meta={"chat_id": candidate_chat_id, "source": "export_chat"},
                query_embedding=embedding,
            )
            if matched:
                results.extend(list(matched))
        if not results:
            return []

        deduped: List[Dict[str, Any]] = []
        seen_texts = set()
        for item in self._sort_results(results):
            text = str(item.get("text", "") or "").strip()
            if not text or text in seen_texts:
                continue
            distance = item.get("distance")
            if distance is not None and float(distance) > self.min_score:
                continue
            seen_texts.add(text)
            deduped.append(item)
            if len(deduped) >= self.top_k:
                break
        return deduped

    def build_memory_message(self, results: Sequence[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        if not results:
            return None

        remaining = self.max_context_chars
        snippets: List[str] = []
        for index, item in enumerate(results, start=1):
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            line = f"{index}. {text}"
            if len(line) > remaining and snippets:
                break
            snippets.append(line[:remaining])
            remaining -= len(snippets[-1]) + 1
            if remaining <= 0:
                break

        if not snippets:
            return None

        return {
            "role": "system",
            "content": (
                "以下内容来自你与当前联系人的真实历史聊天，仅用于模仿你本人常用语气、措辞和节奏，"
                "不要逐字照搬，也不要捏造未提及的事实：\n" + "\n".join(snippets)
            ),
        }

    def _finish_scan(self, summary: Dict[str, Any], started_at: float) -> Dict[str, Any]:
        summary["duration_sec"] = round(max(0.0, time.time() - started_at), 3)
        self.last_scan_at = time.time()
        self.last_scan_summary = dict(summary)
        return summary

    def _discover_targets(self) -> List[Dict[str, Any]]:
        targets: List[Dict[str, Any]] = []
        for dirname in sorted(os.listdir(self.base_dir)):
            dir_path = os.path.join(self.base_dir, dirname)
            if not os.path.isdir(dir_path):
                continue
            contact_name = extract_contact_name(dirname)
            if not contact_name or contact_name in EXCLUDED_CONTACTS:
                continue
            csv_files = sorted(
                filename for filename in os.listdir(dir_path) if filename.lower().endswith(".csv")
            )
            if not csv_files:
                continue
            csv_paths = [os.path.join(dir_path, filename) for filename in csv_files]
            relative_paths = [os.path.relpath(csv_path, self.base_dir) for csv_path in csv_paths]
            signature_parts = []
            for csv_path in csv_paths:
                stat = os.stat(csv_path)
                signature_parts.append(f"{stat.st_mtime_ns}:{stat.st_size}:{os.path.basename(csv_path)}")
            targets.append({
                "contact_name": contact_name,
                "chat_id": f"friend:{contact_name}",
                "csv_paths": csv_paths,
                "relative_paths": relative_paths,
                "manifest_key": f"friend:{contact_name}",
                "signature": (
                    f"{'|'.join(signature_parts)}:"
                    f"{self.self_name}:{self.chunk_messages}:{self.max_chunks_per_chat}"
                ),
            })
        return targets

    async def _index_chunks(
        self,
        ai_client: Any,
        chunks: Sequence[ExportChunk],
        *,
        priority: str = "foreground",
    ) -> int:
        semaphore = asyncio.Semaphore(self.max_parallel_embeddings)

        async def _index_one(chunk: ExportChunk) -> int:
            async with semaphore:
                embedding = await ai_client.get_embedding(chunk.text, priority=priority)
                if not embedding:
                    return 0
                metadata = {
                    "chat_id": chunk.chat_id,
                    "contact_name": chunk.contact_name,
                    "source": "export_chat",
                    "scope": "style",
                    "timestamp": chunk.timestamp,
                    "source_file": chunk.source_file,
                    "chunk_index": chunk.chunk_index,
                }
                chunk_id = self._chunk_id(chunk)
                await asyncio.to_thread(
                    self.vector_memory.upsert_text,
                    chunk.text,
                    metadata,
                    chunk_id,
                    embedding,
                )
                return 1

        tasks = [asyncio.create_task(_index_one(chunk)) for chunk in chunks]
        indexed = 0
        for task in asyncio.as_completed(tasks):
            indexed += await task
        return indexed

    def _load_contact_records(self, csv_paths: Sequence[str]) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for csv_path in csv_paths:
            records.extend(load_chat_from_csv(csv_path, self.self_name))
        records.sort(
            key=lambda item: (
                item.get("timestamp").timestamp()
                if hasattr(item.get("timestamp"), "timestamp")
                else 0.0
            )
        )
        return records

    def _build_chunks(
        self,
        *,
        chat_id: str,
        contact_name: str,
        source_file: str,
        records: Sequence[Dict[str, Any]],
    ) -> List[ExportChunk]:
        chunks: List[ExportChunk] = []
        pending_lines: List[str] = []
        pending_timestamps: List[float] = []

        def flush() -> None:
            nonlocal pending_lines, pending_timestamps
            if not pending_lines:
                return
            text = "\n".join(pending_lines).strip()
            if text:
                chunks.append(
                    ExportChunk(
                        chat_id=chat_id,
                        contact_name=contact_name,
                        source_file=source_file,
                        text=text,
                        timestamp=max(pending_timestamps) if pending_timestamps else time.time(),
                        chunk_index=len(chunks),
                    )
                )
            pending_lines = []
            pending_timestamps = []

        for record in records:
            if not is_text_record(record):
                flush()
                continue
            role = str(record.get("role", "") or "").strip().lower()
            content = str(record.get("content", "") or "").strip()
            if role != "assistant":
                flush()
                continue
            pending_lines.append(content)
            ts = record.get("timestamp")
            pending_timestamps.append(ts.timestamp() if hasattr(ts, "timestamp") else time.time())
            if len(pending_lines) >= self.chunk_messages:
                flush()

        flush()
        if len(chunks) > self.max_chunks_per_chat:
            chunks = chunks[-self.max_chunks_per_chat :]
        return chunks

    def _sort_results(self, results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def _key(item: Dict[str, Any]) -> Tuple[float, float]:
            distance = float(item.get("distance", 0.0) or 0.0)
            timestamp = float(item.get("metadata", {}).get("timestamp", 0.0) or 0.0)
            recent_weight = -timestamp if self.prefer_recent else 0.0
            return (distance, recent_weight)

        return sorted(results, key=_key)

    def _chunk_id(self, chunk: ExportChunk) -> str:
        payload = "|".join([
            chunk.chat_id,
            chunk.source_file,
            str(chunk.chunk_index),
            str(int(chunk.timestamp)),
            chunk.text,
        ])
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return f"export::{digest}"

    def _load_manifest(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.manifest_path):
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_manifest(self, manifest: Dict[str, Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
