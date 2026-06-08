from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit


KNOWLEDGE_SOURCE = "knowledge_base"
MAX_KNOWLEDGE_CONTENT_CHARS = 120000
MAX_KNOWLEDGE_BATCH_DOCUMENTS = 20
MAX_KNOWLEDGE_BATCH_CONTENT_CHARS = 300000


def _normalize_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _stable_hash(value: str, *, length: int = 20) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def _redact_path_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1].strip()
    return f".../{leaf}" if leaf else "..."


def redact_knowledge_local_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme.lower() == "file":
        return _redact_path_value(parsed.path or parsed.netloc or text)
    normalized = text.replace("\\", "/")
    if re.match(r"^(?:[A-Za-z]:/|/|~(?:/|$)|//)", normalized):
        return _redact_path_value(text)
    return normalized


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


def parse_knowledge_document_payload(data: Dict[str, Any]) -> KnowledgeDocument:
    if not isinstance(data, dict):
        raise ValueError("request body must be an object")

    content = str(data.get("content") or "")
    if not content.strip():
        raise ValueError("content is required")
    if len(content) > MAX_KNOWLEDGE_CONTENT_CHARS:
        raise ValueError(f"content is too long; max {MAX_KNOWLEDGE_CONTENT_CHARS} characters")

    content_type = str(data.get("content_type") or "text").strip().lower()
    if content_type not in {"text", "plain", "markdown", "text/plain", "text/markdown"}:
        raise ValueError("content_type must be text or markdown")

    metadata = data.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    metadata = dict(metadata)
    if "page" in data and "page" not in metadata:
        metadata["page"] = data.get("page")
    for key in ("source_file", "url", "source_url"):
        if key in metadata:
            metadata[key] = redact_knowledge_local_path(metadata.get(key))

    return KnowledgeDocument(
        content=content,
        doc_id=redact_knowledge_local_path(data.get("doc_id")),
        version=str(data.get("version") or data.get("doc_version") or "v1").strip() or "v1",
        source_file=redact_knowledge_local_path(data.get("source_file") or metadata.get("source_file")),
        url=redact_knowledge_local_path(data.get("url") or metadata.get("url") or metadata.get("source_url")),
        metadata=metadata,
    )


def parse_knowledge_batch_payload(data: Dict[str, Any]) -> List[KnowledgeDocument]:
    if not isinstance(data, dict):
        raise ValueError("request body must be an object")

    documents = data.get("documents")
    if not isinstance(documents, list):
        raise ValueError("documents must be an array")
    if not documents:
        raise ValueError("documents is required")
    if len(documents) > MAX_KNOWLEDGE_BATCH_DOCUMENTS:
        raise ValueError(f"documents is too large; max {MAX_KNOWLEDGE_BATCH_DOCUMENTS} documents")

    parsed_documents: List[KnowledgeDocument] = []
    total_chars = 0
    for index, item in enumerate(documents):
        if not isinstance(item, dict):
            raise ValueError(f"documents[{index}] must be an object")
        document = parse_knowledge_document_payload(item)
        total_chars += len(str(document.content or ""))
        if total_chars > MAX_KNOWLEDGE_BATCH_CONTENT_CHARS:
            raise ValueError(
                f"total content is too long; max {MAX_KNOWLEDGE_BATCH_CONTENT_CHARS} characters"
            )
        parsed_documents.append(document)
    return parsed_documents


def build_knowledge_chunk_preview(chunks: List[Any]) -> List[Dict[str, Any]]:
    preview: List[Dict[str, Any]] = []
    for chunk in chunks:
        metadata = dict(getattr(chunk, "metadata", {}) or {})
        preview.append(
            {
                "doc_id": str(getattr(chunk, "doc_id", "") or ""),
                "doc_version": str(getattr(chunk, "version", "") or ""),
                "chunk_id": str(getattr(chunk, "chunk_id", "") or ""),
                "chunk_index": int(getattr(chunk, "chunk_index", 0) or 0),
                "char_count": len(str(getattr(chunk, "text", "") or "")),
                "source_file": str(metadata.get("source_file") or ""),
                "url": str(metadata.get("url") or ""),
                "page": metadata.get("page", ""),
            }
        )
    return preview


def build_knowledge_dry_run_payload(document: KnowledgeDocument) -> Dict[str, Any]:
    service = KnowledgeBaseService(None)
    chunks = service.build_chunks(document)
    doc_id = service._resolve_doc_id(document)
    version = str(document.version or "v1").strip() or "v1"
    return {
        "success": True,
        "dry_run": True,
        "doc_id": doc_id,
        "version": version,
        "chunk_count": len(chunks),
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
        "chunks": build_knowledge_chunk_preview(chunks),
        "char_count": len(str(document.content or "")),
    }


def build_knowledge_batch_dry_run_payload(documents: List[KnowledgeDocument]) -> Dict[str, Any]:
    document_payloads: List[Dict[str, Any]] = []
    total_chunks = 0
    total_chars = 0
    for index, document in enumerate(documents):
        payload = build_knowledge_dry_run_payload(document)
        total_chunks += int(payload.get("chunk_count") or 0)
        total_chars += int(payload.get("char_count") or 0)
        document_payloads.append({"index": index, **payload})
    return {
        "success": True,
        "dry_run": True,
        "batch": True,
        "document_count": len(document_payloads),
        "chunk_count": total_chunks,
        "char_count": total_chars,
        "documents": document_payloads,
    }


def _append_unique(values: List[Any], value: Any) -> None:
    if value in ("", None):
        return
    if value not in values:
        values.append(value)


def _sort_page_values(values: List[Any]) -> List[Any]:
    return sorted(values, key=lambda item: (str(type(item)), str(item)))


def build_knowledge_index_payload(
    records: List[Dict[str, Any]],
    *,
    chunk_count: int,
    limit: int,
) -> Dict[str, Any]:
    documents: Dict[str, Dict[str, Any]] = {}
    for record in records:
        metadata = dict((record or {}).get("metadata") or {})
        if metadata.get("source") != KNOWLEDGE_SOURCE:
            continue
        doc_id = redact_knowledge_local_path(metadata.get("doc_id"))
        if not doc_id:
            doc_id = redact_knowledge_local_path(metadata.get("source_file") or metadata.get("url"))
        if not doc_id:
            continue

        entry = documents.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "version": "",
                "versions": [],
                "source_file": "",
                "source_files": [],
                "url": "",
                "urls": [],
                "pages": [],
                "chunk_count": 0,
            },
        )
        entry["chunk_count"] += 1

        version = str(metadata.get("doc_version") or metadata.get("version") or "").strip()
        source_file = redact_knowledge_local_path(metadata.get("source_file"))
        url = redact_knowledge_local_path(metadata.get("url") or metadata.get("source_url"))
        page = metadata.get("page", "")

        _append_unique(entry["versions"], version)
        _append_unique(entry["source_files"], source_file)
        _append_unique(entry["urls"], url)
        _append_unique(entry["pages"], page)

    document_list = []
    for entry in documents.values():
        entry["versions"] = sorted(entry["versions"])
        entry["source_files"] = sorted(entry["source_files"])
        entry["urls"] = sorted(entry["urls"])
        entry["pages"] = _sort_page_values(entry["pages"])
        entry["version"] = entry["versions"][0] if len(entry["versions"]) == 1 else ""
        entry["source_file"] = entry["source_files"][0] if len(entry["source_files"]) == 1 else ""
        entry["url"] = entry["urls"][0] if len(entry["urls"]) == 1 else ""
        document_list.append(entry)

    document_list.sort(key=lambda item: str(item.get("doc_id") or ""))
    indexed_chunk_count = sum(
        1
        for record in records
        if dict((record or {}).get("metadata") or {}).get("source") == KNOWLEDGE_SOURCE
    )
    effective_chunk_count = max(0, int(chunk_count or 0), indexed_chunk_count)
    return {
        "source": KNOWLEDGE_SOURCE,
        "chunk_count": effective_chunk_count,
        "indexed_chunk_count": indexed_chunk_count,
        "document_count": len(document_list),
        "documents": document_list,
        "truncated": effective_chunk_count > indexed_chunk_count,
    }


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
    "MAX_KNOWLEDGE_BATCH_CONTENT_CHARS",
    "MAX_KNOWLEDGE_BATCH_DOCUMENTS",
    "MAX_KNOWLEDGE_CONTENT_CHARS",
    "build_knowledge_batch_dry_run_payload",
    "build_knowledge_chunk_preview",
    "build_knowledge_dry_run_payload",
    "build_knowledge_index_payload",
    "KnowledgeBaseService",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "parse_knowledge_batch_payload",
    "parse_knowledge_document_payload",
    "redact_knowledge_local_path",
]
