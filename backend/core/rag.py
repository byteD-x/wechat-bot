from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


def _clean_text(value: Any, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_from_item(item: Dict[str, Any]) -> Optional[float]:
    for key in ("rerank_score", "cross_encoder_score", "semantic_score", "score"):
        score = _safe_float(item.get(key))
        if score is not None:
            return round(score, 4)
    distance = _safe_float(item.get("distance"))
    if distance is None:
        return None
    return round(max(0.0, 1.0 - distance), 4)


@dataclass
class RetrievalBundle:
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class CitationService:
    def build(self, item: Dict[str, Any], *, source: str, index: int) -> Dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        text = _clean_text(item.get("text"), limit=500)
        source_file = str(metadata.get("source_file") or metadata.get("file") or "").strip()
        chunk_index = metadata.get("chunk_index")
        doc_id = str(metadata.get("doc_id") or source_file or metadata.get("chat_id") or source).strip()
        page = metadata.get("page") or metadata.get("page_number")
        url = str(metadata.get("url") or metadata.get("source_url") or "").strip()
        raw_id = "|".join(
            [
                source,
                str(metadata.get("chat_id") or ""),
                doc_id,
                str(chunk_index if chunk_index is not None else index),
                text,
            ]
        )
        citation_id = hashlib.sha1(raw_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return {
            "citation_id": citation_id,
            "source": source,
            "doc_id": doc_id,
            "chunk_id": str(metadata.get("chunk_id") or citation_id),
            "chunk_index": chunk_index,
            "page": page,
            "url": url,
            "source_file": source_file,
            "snippet": text,
            "score": _score_from_item(item),
        }


class RetrievalService:
    def __init__(self, runtime: Any, *, citation_service: Optional[CitationService] = None) -> None:
        self.runtime = runtime
        self.citation_service = citation_service or CitationService()

    async def retrieve(
        self,
        *,
        chat_id: str,
        query_text: str,
        dependencies: Dict[str, Any],
        event: Any = None,
        priority: str = "foreground",
    ) -> RetrievalBundle:
        started = time.perf_counter()
        messages: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        trace_snippets: List[str] = []
        runtime_hits = 0
        export_hits = 0

        vector_memory = dependencies.get("vector_memory")
        export_rag = dependencies.get("export_rag")

        if vector_memory is not None and self.runtime.bot_cfg.get("rag_enabled", False):
            runtime_results = await self._retrieve_runtime_memory(chat_id, query_text, vector_memory)
            if runtime_results:
                runtime_hits = len(runtime_results)
                messages.append(self._build_runtime_memory_message(runtime_results))
                for index, item in enumerate(runtime_results, start=1):
                    citations.append(self.citation_service.build(item, source="runtime_chat", index=index))
                    snippet = _clean_text(item.get("text"), limit=160)
                    if snippet:
                        trace_snippets.append(snippet)

        if export_rag is not None and self.runtime.bot_cfg.get("export_rag_enabled", False):
            export_results = await self._retrieve_export_rag(
                export_rag,
                chat_id=chat_id,
                query_text=query_text,
                event=event,
                priority=priority,
            )
            if export_results:
                export_hits = len(export_results)
                export_message = export_rag.build_memory_message(export_results)
                if export_message:
                    messages.append(dict(export_message))
                for index, item in enumerate(export_results, start=1):
                    citations.append(self.citation_service.build(item, source="export_chat", index=index))
                    snippet = _clean_text(item.get("text"), limit=160)
                    if snippet:
                        trace_snippets.append(snippet)

        citation_message = self._build_citation_message(citations)
        if citation_message:
            citation_policy_message = self._build_citation_policy_message(citations)
            if citation_policy_message:
                messages.append(citation_policy_message)
            messages.append(citation_message)

        metadata = {
            "augmented": bool(messages),
            "runtime_hit_count": runtime_hits,
            "export_hit_count": export_hits,
            "export_rag_used": export_hits > 0,
            "citation_count": len(citations),
            "citations": citations,
            "trace_snippets": trace_snippets[:8],
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        return RetrievalBundle(messages=messages, metadata=metadata)

    async def _retrieve_runtime_memory(
        self,
        chat_id: str,
        query_text: str,
        vector_memory: Any,
    ) -> List[Dict[str, Any]]:
        query = str(query_text or "").strip()
        if not query:
            return []
        embedding = await self.runtime.get_embedding(query)
        results = await asyncio.to_thread(
            vector_memory.search,
            query=query if not embedding else None,
            n_results=self.runtime.retriever_fetch_k,
            filter_meta={"chat_id": chat_id, "source": "runtime_chat"},
            query_embedding=embedding,
        )
        if not results:
            return []
        ranked_results = await self.runtime._rerank_runtime_results(query, list(results))
        selected: List[Dict[str, Any]] = []
        for item in ranked_results:
            distance = _safe_float(item.get("distance"))
            if distance is not None and distance > self.runtime.retriever_score_threshold:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            selected.append(item)
            if len(selected) >= self.runtime.retriever_top_k:
                break
        if selected:
            self.runtime._stats["retriever_hits"] += len(selected)
        return selected

    async def _retrieve_export_rag(
        self,
        export_rag: Any,
        *,
        chat_id: str,
        query_text: str,
        event: Any,
        priority: str,
    ) -> List[Dict[str, Any]]:
        aliases = self._build_chat_id_aliases(chat_id, event)
        results = await export_rag.search(
            self.runtime,
            chat_id,
            query_text,
            chat_id_aliases=aliases,
            priority=priority,
        )
        return list(results or [])

    @staticmethod
    def _build_runtime_memory_message(results: Sequence[Dict[str, Any]]) -> Dict[str, str]:
        lines = []
        for index, item in enumerate(results, start=1):
            text = _clean_text(item.get("text"), limit=500)
            if text:
                lines.append(f"[{index}] {text}")
        return {
            "role": "system",
            "content": "Relevant past memories with citation ids:\n" + "\n".join(lines),
            "hit_count": len(lines),
        }

    @staticmethod
    def _build_citation_message(citations: Sequence[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        if not citations:
            return None
        lines = []
        for citation in citations[:8]:
            citation_id = str(citation.get("citation_id") or "").strip()
            snippet = _clean_text(citation.get("snippet"), limit=220)
            if citation_id and snippet:
                lines.append(f"[{citation_id}] {snippet}")
        if not lines:
            return None
        return {
            "role": "system",
            "content": "Citation map for retrieved context:\n" + "\n".join(lines),
        }

    def _build_citation_policy_message(self, citations: Sequence[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        if not citations:
            return None
        citation_required = bool(
            self.runtime.bot_cfg.get("safety_require_citations_for_rag", False)
            or getattr(self.runtime, "agent_cfg", {}).get("safety_require_citations_for_rag", False)
        )
        if not citation_required:
            return None
        return {
            "role": "system",
            "content": (
                "When using retrieved context to answer factual or knowledge-style questions, "
                "include at least one exact citation id from the citation map in the answer. "
                "If no citation supports the answer, say you do not have enough reliable evidence."
            ),
        }

    @staticmethod
    def _build_chat_id_aliases(chat_id: str, event: Any) -> List[str]:
        if event is None or not str(chat_id or "").startswith("friend:"):
            return []
        chat_name = str(getattr(event, "chat_name", "") or "").strip()
        if not chat_name:
            return []
        alias = f"friend:{chat_name}"
        return [] if alias == chat_id else [alias]
