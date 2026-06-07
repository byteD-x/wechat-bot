from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from backend.core.knowledge_base import KNOWLEDGE_SOURCE
from backend.core.query_rewrite import QueryRewriteResult, QueryRewriteService


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
    for key in ("rerank_score", "cross_encoder_score", "fused_score", "semantic_score", "keyword_score", "score"):
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
        self.query_rewrite_service = QueryRewriteService()

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
        hybrid_enabled = bool(getattr(self.runtime, "retriever_hybrid_enabled", False))
        query_rewrite = self.query_rewrite_service.rewrite(query_text)
        retrieval_counts = {
            "runtime_vector_hit_count": 0,
            "runtime_keyword_hit_count": 0,
            "runtime_fused_candidate_count": 0,
            "knowledge_vector_hit_count": 0,
            "knowledge_keyword_hit_count": 0,
            "knowledge_fused_candidate_count": 0,
        }

        vector_memory = dependencies.get("vector_memory")
        export_rag = dependencies.get("export_rag")

        if vector_memory is not None and self.runtime.bot_cfg.get("rag_enabled", False):
            query_embedding = await self._build_query_embedding(query_text)
            runtime_results = await self._retrieve_runtime_memory(
                chat_id,
                query_text,
                vector_memory,
                query_embedding=query_embedding,
                query_rewrite=query_rewrite,
                hybrid_enabled=hybrid_enabled,
                retrieval_counts=retrieval_counts,
            )
            if runtime_results:
                runtime_hits = len(runtime_results)
                messages.append(self._build_runtime_memory_message(runtime_results))
                for index, item in enumerate(runtime_results, start=1):
                    citations.append(self.citation_service.build(item, source="runtime_chat", index=index))
                    snippet = _clean_text(item.get("text"), limit=160)
                    if snippet:
                        trace_snippets.append(snippet)

            knowledge_results = await self._retrieve_knowledge_base(
                query_text,
                vector_memory,
                query_embedding=query_embedding,
                query_rewrite=query_rewrite,
                hybrid_enabled=hybrid_enabled,
                retrieval_counts=retrieval_counts,
            )
            if knowledge_results:
                messages.append(self._build_knowledge_base_message(knowledge_results))
                for index, item in enumerate(knowledge_results, start=1):
                    citations.append(self.citation_service.build(item, source=KNOWLEDGE_SOURCE, index=index))
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
            "knowledge_hit_count": len([item for item in citations if item.get("source") == KNOWLEDGE_SOURCE]),
            "export_hit_count": export_hits,
            "export_rag_used": export_hits > 0,
            "knowledge_base_used": any(item.get("source") == KNOWLEDGE_SOURCE for item in citations),
            "citation_count": len(citations),
            "citations": citations,
            "trace_snippets": trace_snippets[:8],
            "retrieval_mode": "hybrid" if hybrid_enabled else "vector",
            "query_rewrite": query_rewrite.to_trace(enabled=hybrid_enabled),
            **retrieval_counts,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        return RetrievalBundle(messages=messages, metadata=metadata)

    async def _build_query_embedding(self, query_text: str) -> Optional[List[float]]:
        query = str(query_text or "").strip()
        if not query:
            return None
        return await self.runtime.get_embedding(query)

    async def _retrieve_runtime_memory(
        self,
        chat_id: str,
        query_text: str,
        vector_memory: Any,
        *,
        query_embedding: Optional[List[float]],
        query_rewrite: QueryRewriteResult,
        hybrid_enabled: bool,
        retrieval_counts: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        query = str(query_text or "").strip()
        if not query:
            return []
        filter_meta = {"chat_id": chat_id, "source": "runtime_chat"}
        results = await asyncio.to_thread(
            vector_memory.search,
            query=query if not query_embedding else None,
            n_results=self.runtime.retriever_fetch_k,
            filter_meta=filter_meta,
            query_embedding=query_embedding,
        )
        retrieval_counts["runtime_vector_hit_count"] = len(results or [])
        if hybrid_enabled:
            keyword_results = await self._retrieve_keyword_candidates(
                vector_memory,
                query_rewrite.keyword_query,
                filter_meta=filter_meta,
            )
            retrieval_counts["runtime_keyword_hit_count"] = len(keyword_results)
            self.runtime._stats["retriever_keyword_hits"] = (
                self.runtime._stats.get("retriever_keyword_hits", 0) + len(keyword_results)
            )
            results = self._fuse_retrieval_results(results, keyword_results)
            retrieval_counts["runtime_fused_candidate_count"] = len(results)
            self.runtime._stats["retriever_hybrid_fused_candidates"] = (
                self.runtime._stats.get("retriever_hybrid_fused_candidates", 0) + len(results)
            )
        if not results:
            return []
        ranked_results = await self.runtime._rerank_runtime_results(query, list(results))
        selected = self._select_ranked_results(ranked_results)
        if selected:
            self.runtime._stats["retriever_hits"] += len(selected)
        return selected

    async def _retrieve_knowledge_base(
        self,
        query_text: str,
        vector_memory: Any,
        *,
        query_embedding: Optional[List[float]],
        query_rewrite: QueryRewriteResult,
        hybrid_enabled: bool,
        retrieval_counts: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        query = str(query_text or "").strip()
        if not query:
            return []
        filter_meta = {"source": KNOWLEDGE_SOURCE}
        results = await asyncio.to_thread(
            vector_memory.search,
            query=query if not query_embedding else None,
            n_results=self.runtime.retriever_fetch_k,
            filter_meta=filter_meta,
            query_embedding=query_embedding,
        )
        retrieval_counts["knowledge_vector_hit_count"] = len(results or [])
        if hybrid_enabled:
            keyword_results = await self._retrieve_keyword_candidates(
                vector_memory,
                query_rewrite.keyword_query,
                filter_meta=filter_meta,
            )
            retrieval_counts["knowledge_keyword_hit_count"] = len(keyword_results)
            self.runtime._stats["retriever_keyword_hits"] = (
                self.runtime._stats.get("retriever_keyword_hits", 0) + len(keyword_results)
            )
            results = self._fuse_retrieval_results(results, keyword_results)
            retrieval_counts["knowledge_fused_candidate_count"] = len(results)
            self.runtime._stats["retriever_hybrid_fused_candidates"] = (
                self.runtime._stats.get("retriever_hybrid_fused_candidates", 0) + len(results)
            )
        if not results:
            return []
        ranked_results = await self.runtime._rerank_runtime_results(query, list(results))
        selected = self._select_ranked_results(ranked_results)
        if selected:
            self.runtime._stats["retriever_hits"] += len(selected)
        return selected

    async def _retrieve_keyword_candidates(
        self,
        vector_memory: Any,
        keyword_query: str,
        *,
        filter_meta: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        query = str(keyword_query or "").strip()
        keyword_search = getattr(vector_memory, "keyword_search", None)
        if not query or not callable(keyword_search):
            return []
        return list(
            await asyncio.to_thread(
                keyword_search,
                query,
                self.runtime.retriever_fetch_k,
                filter_meta,
            )
            or []
        )

    def _fuse_retrieval_results(
        self,
        vector_results: Sequence[Dict[str, Any]],
        keyword_results: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        keyword_weight = _safe_float(getattr(self.runtime, "retriever_keyword_weight", 0.35), 0.35) or 0.35
        keyword_weight = min(1.0, max(0.0, keyword_weight))
        vector_weight = 1.0 - keyword_weight
        merged: Dict[str, Dict[str, Any]] = {}

        for item in vector_results or []:
            key = self._result_identity(item)
            semantic_score = self._semantic_score(item)
            merged[key] = {
                **item,
                "semantic_score": round(semantic_score, 4),
                "_vector_score": semantic_score,
                "_keyword_raw_score": 0.0,
                "retrieval_channels": ["vector"],
            }

        for item in keyword_results or []:
            key = self._result_identity(item)
            keyword_score = max(0.0, _safe_float(item.get("keyword_score"), 0.0) or 0.0)
            if key in merged:
                channels = list(merged[key].get("retrieval_channels") or [])
                if "keyword" not in channels:
                    channels.append("keyword")
                merged[key].update({
                    "keyword_score": round(keyword_score, 4),
                    "_keyword_raw_score": keyword_score,
                    "retrieval_channels": channels,
                })
            else:
                merged[key] = {
                    **item,
                    "keyword_score": round(keyword_score, 4),
                    "_vector_score": 0.0,
                    "_keyword_raw_score": keyword_score,
                    "retrieval_channels": ["keyword"],
                }

        max_keyword = max((float(item.get("_keyword_raw_score") or 0.0) for item in merged.values()), default=0.0)
        fused = []
        for item in merged.values():
            vector_score = float(item.get("_vector_score") or 0.0)
            raw_keyword_score = float(item.get("_keyword_raw_score") or 0.0)
            keyword_score = raw_keyword_score / max_keyword if max_keyword > 0 else 0.0
            item["keyword_score"] = round(raw_keyword_score, 4)
            item["fused_score"] = round((vector_score * vector_weight) + (keyword_score * keyword_weight), 4)
            item.pop("_vector_score", None)
            item.pop("_keyword_raw_score", None)
            fused.append(item)

        fused.sort(
            key=lambda item: (
                float(item.get("fused_score") or 0.0),
                float(item.get("semantic_score") or 0.0),
                float(item.get("keyword_score") or 0.0),
            ),
            reverse=True,
        )
        return fused

    @staticmethod
    def _semantic_score(item: Dict[str, Any]) -> float:
        distance = _safe_float(item.get("distance"))
        if distance is not None:
            return max(0.0, 1.0 - distance)
        for key in ("semantic_score", "score"):
            value = _safe_float(item.get(key))
            if value is not None:
                return max(0.0, value)
        return 0.0

    @staticmethod
    def _result_identity(item: Dict[str, Any]) -> str:
        metadata = dict(item.get("metadata") or {})
        for value in (
            item.get("id"),
            metadata.get("chunk_id"),
            metadata.get("doc_id"),
            metadata.get("chat_id"),
        ):
            text = str(value or "").strip()
            if text:
                return text
        text = str(item.get("text") or "")
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _select_ranked_results(self, ranked_results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    def _build_knowledge_base_message(results: Sequence[Dict[str, Any]]) -> Dict[str, str]:
        lines = []
        for index, item in enumerate(results, start=1):
            text = _clean_text(item.get("text"), limit=500)
            metadata = dict(item.get("metadata") or {})
            doc_id = str(metadata.get("doc_id") or metadata.get("source_file") or "knowledge").strip()
            if text:
                lines.append(f"[KB{index} {doc_id}] {text}")
        return {
            "role": "system",
            "content": "Relevant knowledge base entries with citation ids:\n" + "\n".join(lines),
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
