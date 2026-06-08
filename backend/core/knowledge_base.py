from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlsplit


KNOWLEDGE_SOURCE = "knowledge_base"
MAX_KNOWLEDGE_CONTENT_CHARS = 120000
MAX_KNOWLEDGE_BATCH_DOCUMENTS = 20
MAX_KNOWLEDGE_BATCH_CONTENT_CHARS = 300000
KNOWLEDGE_AUTO_INDEX_INBOX_DIRNAME = "knowledge_base/inbox"
KNOWLEDGE_AUTO_INDEX_MAX_FILES = MAX_KNOWLEDGE_BATCH_DOCUMENTS
KNOWLEDGE_AUTO_INDEX_MAX_FILE_CHARS = MAX_KNOWLEDGE_CONTENT_CHARS
KNOWLEDGE_AUTO_INDEX_MAX_TOTAL_CHARS = MAX_KNOWLEDGE_BATCH_CONTENT_CHARS
KNOWLEDGE_AUTO_INDEX_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".mdown", ".mkd"}
KNOWLEDGE_JOB_MODE_INGEST = "ingest"
KNOWLEDGE_JOB_MODE_REBUILD = "rebuild"
DEFAULT_KNOWLEDGE_JOB_MAX_ITEMS = 50


def _normalize_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _stable_hash(value: str, *, length: int = 20) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return max(0, int(default))


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


def _infer_auto_index_content_type(path: Path) -> str:
    return "markdown" if path.suffix.lower() in {".md", ".markdown", ".mdown", ".mkd"} else "text"


def _build_auto_index_skipped_file(path: Path, reason: str) -> Dict[str, Any]:
    return {
        "name": path.name,
        "source_file": redact_knowledge_local_path(str(path)),
        "reason": reason,
    }


def build_knowledge_auto_index_preview_payload(
    inbox_dir: Union[Path, str],
    *,
    max_files: int = KNOWLEDGE_AUTO_INDEX_MAX_FILES,
    max_file_chars: int = KNOWLEDGE_AUTO_INDEX_MAX_FILE_CHARS,
    max_total_chars: int = KNOWLEDGE_AUTO_INDEX_MAX_TOTAL_CHARS,
) -> Dict[str, Any]:
    """Build a read-only dry-run plan for the fixed knowledge-base inbox."""

    inbox_path = Path(inbox_dir)
    inbox_exists = inbox_path.is_dir() and not inbox_path.is_symlink()
    payload: Dict[str, Any] = {
        "success": True,
        "dry_run": True,
        "auto_index": True,
        "mode": "preview",
        "source": KNOWLEDGE_SOURCE,
        "fixed_inbox": True,
        "inbox": redact_knowledge_local_path(str(inbox_path)),
        "exists": inbox_exists,
        "document_count": 0,
        "skipped_count": 0,
        "chunk_count": 0,
        "char_count": 0,
        "max_files": max(0, int(max_files or 0)),
        "max_file_chars": max(0, int(max_file_chars or 0)),
        "max_total_chars": max(0, int(max_total_chars or 0)),
        "documents": [],
        "skipped": [],
    }
    if not payload["exists"]:
        return payload

    documents: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    total_chars = 0
    total_chunks = 0
    accepted_files = 0
    max_files_value = int(payload["max_files"])
    max_file_chars_value = int(payload["max_file_chars"])
    max_total_chars_value = int(payload["max_total_chars"])

    for path in sorted(inbox_path.iterdir(), key=lambda item: item.name.lower()):
        if path.is_symlink():
            skipped.append(_build_auto_index_skipped_file(path, "symlink_ignored"))
            continue
        if path.is_dir():
            skipped.append(_build_auto_index_skipped_file(path, "directory_ignored"))
            continue
        if not path.is_file():
            skipped.append(_build_auto_index_skipped_file(path, "not_regular_file"))
            continue
        if path.suffix.lower() not in KNOWLEDGE_AUTO_INDEX_EXTENSIONS:
            skipped.append(_build_auto_index_skipped_file(path, "unsupported_extension"))
            continue
        if accepted_files >= max_files_value:
            skipped.append(_build_auto_index_skipped_file(path, "max_files_exceeded"))
            continue

        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            skipped.append(_build_auto_index_skipped_file(path, "unsupported_encoding"))
            continue
        except OSError:
            skipped.append(_build_auto_index_skipped_file(path, "file_read_failed"))
            continue

        if not content.strip():
            skipped.append(_build_auto_index_skipped_file(path, "empty_file"))
            continue
        if len(content) > max_file_chars_value:
            skipped.append(_build_auto_index_skipped_file(path, "file_too_large"))
            continue
        if total_chars + len(content) > max_total_chars_value:
            skipped.append(_build_auto_index_skipped_file(path, "total_content_too_large"))
            continue

        redacted_path = redact_knowledge_local_path(str(path))
        document = KnowledgeDocument(
            content=content,
            doc_id=redacted_path,
            source_file=redacted_path,
            metadata={"content_type": _infer_auto_index_content_type(path)},
        )
        preview = build_knowledge_dry_run_payload(document)
        item = {
            "index": len(documents),
            "name": path.name,
            "source_file": redacted_path,
            "content_type": _infer_auto_index_content_type(path),
            "doc_id": str(preview.get("doc_id") or ""),
            "version": str(preview.get("version") or "v1"),
            "chunk_count": _safe_int(preview.get("chunk_count"), 0),
            "chunk_ids": list(preview.get("chunk_ids") or []),
            "chunks": list(preview.get("chunks") or []),
            "char_count": len(content),
        }
        documents.append(item)
        accepted_files += 1
        total_chars += len(content)
        total_chunks += int(item["chunk_count"])

    payload.update(
        {
            "document_count": len(documents),
            "skipped_count": len(skipped),
            "chunk_count": total_chunks,
            "char_count": total_chars,
            "documents": documents,
            "skipped": skipped,
        }
    )
    return payload


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


def build_knowledge_batch_write_payload(results: List[Dict[str, Any]], *, mode: str) -> Dict[str, Any]:
    documents = []
    succeeded_documents = 0
    total_chunks = 0
    indexed_chunks = 0
    skipped_chunks = 0
    deleted_previous_documents = 0

    for index, result in enumerate(results):
        success = bool(result.get("success", False))
        deleted_previous = bool(result.get("deleted_previous", False))
        if success:
            succeeded_documents += 1
        if deleted_previous:
            deleted_previous_documents += 1
        total_chunks += _safe_int(result.get("chunk_count"), 0)
        indexed_chunks += _safe_int(result.get("indexed_chunks"), 0)
        skipped_chunks += _safe_int(result.get("skipped_chunks"), 0)
        documents.append(
            {
                "index": index,
                "success": success,
                "reason": str(result.get("reason") or ""),
                "doc_id": redact_knowledge_local_path(result.get("doc_id")),
                "version": str(result.get("version") or ""),
                "chunk_count": _safe_int(result.get("chunk_count"), 0),
                "indexed_chunks": _safe_int(result.get("indexed_chunks"), 0),
                "skipped_chunks": _safe_int(result.get("skipped_chunks"), 0),
                "deleted_previous": deleted_previous,
                "chunk_ids": list(result.get("chunk_ids") or []),
            }
        )

    failed_documents = max(0, len(documents) - succeeded_documents)
    payload = {
        "success": failed_documents == 0,
        "batch": True,
        "dry_run": False,
        "mode": mode,
        "document_count": len(documents),
        "succeeded_documents": succeeded_documents,
        "failed_documents": failed_documents,
        "chunk_count": total_chunks,
        "indexed_chunks": indexed_chunks,
        "skipped_chunks": skipped_chunks,
        "documents": documents,
    }
    if mode == KNOWLEDGE_JOB_MODE_REBUILD:
        payload["deleted_previous_documents"] = deleted_previous_documents
    return payload


class KnowledgeBaseJobQueue:
    """Small in-memory queue for controlled knowledge-base write jobs."""

    def __init__(self, *, max_jobs: int = DEFAULT_KNOWLEDGE_JOB_MAX_ITEMS) -> None:
        self.max_jobs = max(1, int(max_jobs or DEFAULT_KNOWLEDGE_JOB_MAX_ITEMS))
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._worker: Optional[asyncio.Task[Any]] = None

    async def enqueue(
        self,
        *,
        mode: str,
        documents: List[KnowledgeDocument],
        vector_memory: Any,
        ai_client: Any,
    ) -> Dict[str, Any]:
        normalized_mode = self._normalize_mode(mode)
        if not documents:
            raise ValueError("documents is required")
        job_id = f"kbjob_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        job = {
            "job_id": job_id,
            "success": True,
            "status": "queued",
            "stage": "queued",
            "message": "knowledge base job queued",
            "mode": normalized_mode,
            "source": KNOWLEDGE_SOURCE,
            "document_count": len(documents),
            "documents": self._summarize_documents(documents),
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": "",
            "error_type": "",
            "_documents": list(documents),
            "_vector_memory": vector_memory,
            "_ai_client": ai_client,
        }

        async with self._lock:
            self._jobs[job_id] = job
            self._trim_locked()
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._run_pending())
            return self._public_job(job)

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id is required")
        async with self._lock:
            job = self._jobs.get(normalized_job_id)
            if not job:
                return {"success": False, "message": "knowledge base job not found", "job_id": normalized_job_id}
            return self._public_job(job)

    async def get_status(self) -> Dict[str, Any]:
        async with self._lock:
            jobs = [self._public_job(item) for item in self._jobs.values()]
        by_status: Dict[str, int] = {}
        for item in jobs:
            status = str(item.get("status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "enabled": True,
            "max_jobs": self.max_jobs,
            "total": len(jobs),
            "by_status": by_status,
            "queued": by_status.get("queued", 0),
            "running": by_status.get("running", 0),
            "succeeded": by_status.get("succeeded", 0),
            "failed": by_status.get("failed", 0),
            "recent": jobs[-8:],
        }

    async def _run_pending(self) -> None:
        while True:
            async with self._lock:
                job = next(
                    (item for item in self._jobs.values() if item.get("status") == "queued"),
                    None,
                )
                if job is None:
                    return
                job["status"] = "running"
                job["stage"] = "indexing"
                job["message"] = "indexing knowledge documents"
                job["started_at"] = time.time()

            try:
                result = await self._execute_job(job)
                success = bool(result.get("success", False))
                await self._update_job(
                    str(job["job_id"]),
                    success=success,
                    status="succeeded" if success else "failed",
                    stage="completed" if success else "failed",
                    message="knowledge base job completed" if success else "knowledge base job failed",
                    result=result,
                    finished_at=time.time(),
                    error="" if success else self._first_failure_reason(result),
                )
            except Exception as exc:
                await self._update_job(
                    str(job["job_id"]),
                    success=False,
                    status="failed",
                    stage="failed",
                    message="knowledge base job failed",
                    error="job_failed",
                    error_type=exc.__class__.__name__,
                    finished_at=time.time(),
                )

    async def _execute_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        service = KnowledgeBaseService(job.get("_vector_memory"))
        ai_client = job.get("_ai_client")
        rebuild = str(job.get("mode") or "") == KNOWLEDGE_JOB_MODE_REBUILD
        results = []
        for document in job.get("_documents") or []:
            results.append(
                await service.ingest_document(
                    document,
                    ai_client,
                    rebuild=rebuild,
                    priority="background",
                )
            )
        return build_knowledge_batch_write_payload(results, mode=str(job.get("mode") or ""))

    async def _update_job(self, job_id: str, **changes: Any) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(changes)

    def _trim_locked(self) -> None:
        while len(self._jobs) > self.max_jobs:
            oldest_id = next(
                (
                    job_id
                    for job_id, item in self._jobs.items()
                    if item.get("status") not in {"queued", "running"}
                ),
                "",
            )
            if not oldest_id:
                break
            self._jobs.pop(oldest_id, None)

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = str(mode or KNOWLEDGE_JOB_MODE_INGEST).strip().lower() or KNOWLEDGE_JOB_MODE_INGEST
        if normalized not in {KNOWLEDGE_JOB_MODE_INGEST, KNOWLEDGE_JOB_MODE_REBUILD}:
            raise ValueError("mode must be ingest or rebuild")
        return normalized

    @staticmethod
    def _summarize_documents(documents: List[KnowledgeDocument]) -> List[Dict[str, Any]]:
        service = KnowledgeBaseService(None)
        summaries = []
        for index, document in enumerate(documents):
            metadata = dict(document.metadata or {})
            summaries.append(
                {
                    "index": index,
                    "doc_id": redact_knowledge_local_path(service._resolve_doc_id(document)),
                    "version": str(document.version or "v1").strip() or "v1",
                    "source_file": redact_knowledge_local_path(document.source_file),
                    "url": redact_knowledge_local_path(document.url),
                    "page": metadata.get("page", ""),
                    "chunk_count": len(service.build_chunks(document)),
                }
            )
        return summaries

    @staticmethod
    def _first_failure_reason(result: Dict[str, Any]) -> str:
        for item in result.get("documents") or []:
            if isinstance(item, dict) and not item.get("success"):
                return str(item.get("reason") or "document_failed")
        return ""

    @staticmethod
    def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "job_id": str(job.get("job_id") or ""),
            "success": bool(job.get("success", False)),
            "status": str(job.get("status") or ""),
            "stage": str(job.get("stage") or ""),
            "message": str(job.get("message") or ""),
            "mode": str(job.get("mode") or ""),
            "source": KNOWLEDGE_SOURCE,
            "document_count": _safe_int(job.get("document_count"), 0),
            "documents": [dict(item) for item in job.get("documents") or [] if isinstance(item, dict)],
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "error": str(job.get("error") or ""),
            "error_type": str(job.get("error_type") or ""),
        }
        result = job.get("result")
        if isinstance(result, dict):
            payload["result"] = dict(result)
        return payload


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
                return redact_knowledge_local_path(text)
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
                "source_file": redact_knowledge_local_path(document.source_file or metadata.get("source_file")),
                "url": redact_knowledge_local_path(
                    document.url or metadata.get("url") or metadata.get("source_url")
                ),
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
    "KNOWLEDGE_AUTO_INDEX_EXTENSIONS",
    "KNOWLEDGE_AUTO_INDEX_INBOX_DIRNAME",
    "KNOWLEDGE_AUTO_INDEX_MAX_FILE_CHARS",
    "KNOWLEDGE_AUTO_INDEX_MAX_FILES",
    "KNOWLEDGE_AUTO_INDEX_MAX_TOTAL_CHARS",
    "MAX_KNOWLEDGE_BATCH_CONTENT_CHARS",
    "MAX_KNOWLEDGE_BATCH_DOCUMENTS",
    "MAX_KNOWLEDGE_CONTENT_CHARS",
    "KNOWLEDGE_JOB_MODE_INGEST",
    "KNOWLEDGE_JOB_MODE_REBUILD",
    "KnowledgeBaseJobQueue",
    "build_knowledge_auto_index_preview_payload",
    "build_knowledge_batch_dry_run_payload",
    "build_knowledge_batch_write_payload",
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
