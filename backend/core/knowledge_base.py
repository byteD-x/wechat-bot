from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


KNOWLEDGE_SOURCE = "knowledge_base"


def _normalize_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _stable_hash(value: str, *, length: int = 20) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


@dataclass
class KnowledgeDocument:
    content: str
    doc_id: str = ""
    version: str = "v1"
    source_file: str = ""
    url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunk:
    doc_id: str
    chunk_id: str
    version: str
    chunk_index: int
    text: str
    metadata: Dict[str, Any]


class KnowledgeBaseService:
    """Ingest general knowledge documents into the existing vector memory."""

    def __init__(
        self,
        vector_memory: Any,
        *,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
    ) -> None:
        self.vector_memory = vector_memory
        self.chunk_size = max(120, int(chunk_size or 900))
        overlap = max(0, int(chunk_overlap or 0))
        self.chunk_overlap = min(overlap, max(0, self.chunk_size // 2))

    async def ingest_document(
        self,
        document: KnowledgeDocument,
        ai_client: Any,
        *,
        rebuild: bool = False,
        priority: str = "foreground",
    ) -> Dict[str, Any]:
        doc_id = self._resolve_doc_id(document)
        version = str(document.version or "v1").strip() or "v1"
        chunks = self.build_chunks(document)
        summary: Dict[str, Any] = {
            "success": True,
            "reason": "",
            "doc_id": doc_id,
            "version": version,
            "chunk_count": len(chunks),
            "indexed_chunks": 0,
            "skipped_chunks": 0,
            "deleted_previous": False,
            "chunk_ids": [],
        }

        if not self.vector_memory:
            summary.update({"success": False, "reason": "vector_memory_unavailable"})
            return summary
        if not chunks:
            summary.update({"success": False, "reason": "empty_document"})
            return summary
        if ai_client is None or not hasattr(ai_client, "get_embedding"):
            summary.update({"success": False, "reason": "embedding_unavailable"})
            return summary

        indexed_chunks = []
        for chunk in chunks:
            embedding = await self._get_embedding(ai_client, chunk.text, priority=priority)
            if not embedding:
                summary["skipped_chunks"] += 1
                continue
            indexed_chunks.append((chunk, embedding))

        if not indexed_chunks:
            summary.update({"success": False, "reason": "no_chunks_indexed"})
            return summary
        if rebuild and summary["skipped_chunks"] > 0:
            summary.update({"success": False, "reason": "incomplete_embeddings"})
            return summary

        if rebuild:
            await asyncio.to_thread(
                self.vector_memory.delete,
                {"source": KNOWLEDGE_SOURCE, "doc_id": doc_id},
            )
            summary["deleted_previous"] = True

        for chunk, embedding in indexed_chunks:
            await asyncio.to_thread(
                self.vector_memory.upsert_text,
                chunk.text,
                chunk.metadata,
                chunk.chunk_id,
                embedding,
            )
            summary["indexed_chunks"] += 1
            summary["chunk_ids"].append(chunk.chunk_id)

        return summary

    def build_chunks(self, document: KnowledgeDocument) -> List[KnowledgeChunk]:
        text = _normalize_text(document.content)
        if not text:
            return []

        doc_id = self._resolve_doc_id(document)
        version = str(document.version or "v1").strip() or "v1"
        raw_chunks = self._split_text(text)
        chunks: List[KnowledgeChunk] = []
        for index, chunk_text in enumerate(raw_chunks):
            chunk_id = self._build_chunk_id(
                doc_id=doc_id,
                version=version,
                chunk_index=index,
                text=chunk_text,
            )
            metadata = self._build_metadata(
                document,
                doc_id=doc_id,
                version=version,
                chunk_id=chunk_id,
                chunk_index=index,
                chunk_count=len(raw_chunks),
            )
            chunks.append(
                KnowledgeChunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    version=version,
                    chunk_index=index,
                    text=chunk_text,
                    metadata=metadata,
                )
            )
        return chunks

    def _split_text(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]

        chunks: List[str] = []
        start = 0
        min_boundary = max(80, self.chunk_size // 2)
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            if end < len(text):
                boundary = text.rfind("\n\n", start + 1, end)
                if boundary <= start + min_boundary:
                    boundary = text.rfind(" ", start + 1, end)
                if boundary > start + min_boundary:
                    end = boundary

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(start + 1, end - self.chunk_overlap)
        return chunks

    def _resolve_doc_id(self, document: KnowledgeDocument) -> str:
        for value in (document.doc_id, document.source_file, document.url):
            text = str(value or "").strip()
            if text:
                return text
        digest = _stable_hash(_normalize_text(document.content))
        return f"doc::{digest}"

    def _build_metadata(
        self,
        document: KnowledgeDocument,
        *,
        doc_id: str,
        version: str,
        chunk_id: str,
        chunk_index: int,
        chunk_count: int,
    ) -> Dict[str, Any]:
        metadata = dict(document.metadata or {})
        page = metadata.get("page", metadata.get("page_number", ""))
        metadata.update(
            {
                "source": KNOWLEDGE_SOURCE,
                "scope": "knowledge",
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "doc_version": version,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "source_file": str(document.source_file or metadata.get("source_file") or ""),
                "url": str(document.url or metadata.get("url") or metadata.get("source_url") or ""),
                "page": page if page is not None else "",
            }
        )
        return metadata

    @staticmethod
    def _build_chunk_id(*, doc_id: str, version: str, chunk_index: int, text: str) -> str:
        digest = _stable_hash("|".join([doc_id, version, str(chunk_index), text]))
        return f"kb::{digest}"

    @staticmethod
    async def _get_embedding(ai_client: Any, text: str, *, priority: str) -> Optional[List[float]]:
        try:
            embedding = await ai_client.get_embedding(text, priority=priority)
        except TypeError:
            embedding = await ai_client.get_embedding(text)
        if not embedding:
            return None
        return list(embedding)


__all__ = [
    "KNOWLEDGE_SOURCE",
    "KnowledgeBaseService",
    "KnowledgeChunk",
    "KnowledgeDocument",
]
