"""
向量记忆管理模块 - 基于 ChromaDB 实现 RAG

功能：
- 存储和检索历史对话的向量表示
- 支持基于语义的上下文检索
"""

import logging
import math
import os
import re
from collections import Counter
from typing import List, Dict, Optional, Any
from backend.shared_config import ensure_data_root
from ..utils.runtime_artifacts import chdir_temporarily, CHROMA_DIR, relocate_known_root_artifacts

logger = logging.getLogger(__name__)

_KEYWORD_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")


def _tokenize_keyword_text(text: str) -> List[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    return [token for token in _KEYWORD_TOKEN_RE.findall(normalized) if token]


def _keyword_identity(item: Dict[str, Any]) -> str:
    metadata = dict(item.get("metadata") or {})
    for value in (
        item.get("id"),
        metadata.get("chunk_id"),
        metadata.get("doc_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(item.get("text") or "")


def _rank_keyword_candidates(query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query_terms = _tokenize_keyword_text(query)
    if not query_terms:
        return []

    documents: List[List[str]] = []
    for item in candidates:
        documents.append(_tokenize_keyword_text(str(item.get("text") or "")))

    doc_count = len(documents)
    if doc_count <= 0:
        return []

    document_frequency: Counter[str] = Counter()
    for tokens in documents:
        for token in set(tokens):
            document_frequency[token] += 1

    avg_doc_len = sum(len(tokens) for tokens in documents) / max(1, doc_count)
    ranked: List[Dict[str, Any]] = []
    for item, tokens in zip(candidates, documents):
        if not tokens:
            continue
        token_counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = token_counts.get(term, 0)
            if frequency <= 0:
                continue
            idf = math.log(1 + (doc_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * (len(tokens) / max(avg_doc_len, 1.0)))
            score += idf * ((frequency * 2.2) / max(denominator, 0.0001))
        if score <= 0:
            continue
        ranked.append({**item, "keyword_score": round(score, 4)})

    ranked.sort(key=lambda item: (float(item.get("keyword_score") or 0.0), _keyword_identity(item)), reverse=True)
    return ranked

class VectorMemory:
    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            db_path = str(ensure_data_root() / "vector_db")
        self.db_path = os.path.abspath(db_path)
        os.makedirs(self.db_path, exist_ok=True)

        self.client = None
        self.collection = None
        
        try:
            # Lazy import: avoid slowing down bot startup when vector memory is not used.
            import chromadb

            with chdir_temporarily(CHROMA_DIR):
                self.client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.client.get_or_create_collection(
                name="chat_history",
                metadata={"hnsw:space": "cosine"}
            )
            relocate_known_root_artifacts()
            logger.info(f"VectorMemory initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self.client = None
            self.collection = None

    def __bool__(self) -> bool:
        # Treat partially-initialized instances as unavailable so callers can
        # correctly short-circuit (e.g. export_rag.sync).
        return bool(self.collection)

    def add_text(self, text: str, metadata: Dict[str, Any], id: str, embedding: Optional[List[float]] = None) -> None:
        if not self.collection:
            return
            
        try:
            if embedding:
                self.collection.add(
                    documents=[text],
                    metadatas=[metadata],
                    embeddings=[embedding],
                    ids=[id]
                )
            else:
                self.collection.add(
                    documents=[text],
                    metadatas=[metadata],
                    ids=[id]
                )
        except Exception as e:
            logger.error(f"Failed to add text to vector db: {e}")

    def upsert_text(self, text: str, metadata: Dict[str, Any], id: str, embedding: Optional[List[float]] = None) -> None:
        if not self.collection:
            return

        try:
            payload = {
                "documents": [text],
                "metadatas": [metadata],
                "ids": [id],
            }
            if embedding:
                payload["embeddings"] = [embedding]
            self.collection.upsert(**payload)
        except Exception as e:
            logger.error(f"Failed to upsert text to vector db: {e}")

    def search(self, query: Optional[str] = None, n_results: int = 5, filter_meta: Optional[Dict] = None, query_embedding: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        if not self.collection:
            return []
            
        try:
            if query_embedding:
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    where=filter_meta
                )
            else:
                results = self.collection.query(
                    query_texts=[query or ""],
                    n_results=n_results,
                    where=filter_meta
                )
            
            formatted = []
            if results['documents']:
                for i in range(len(results['documents'][0])):
                    formatted.append({
                        'id': results['ids'][0][i] if results.get('ids') else "",
                        'text': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                        'distance': results['distances'][0][i] if results['distances'] else 0.0
                    })
            return formatted
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def keyword_search(
        self,
        query: str,
        n_results: int = 5,
        filter_meta: Optional[Dict] = None,
        candidate_limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if not self.collection:
            return []

        try:
            limit = max(int(n_results or 1), min(max(int(candidate_limit or 1), int(n_results or 1)), 1000))
            results = self.collection.get(
                where=filter_meta,
                include=["documents", "metadatas"],
                limit=limit,
            )
            candidates = []
            documents = list(results.get("documents") or [])
            metadatas = list(results.get("metadatas") or [])
            ids = list(results.get("ids") or [])
            for index, text in enumerate(documents):
                candidates.append({
                    "id": ids[index] if index < len(ids) else "",
                    "text": text,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                })
            return _rank_keyword_candidates(query, candidates)[: max(1, int(n_results or 1))]
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    def list_metadata(self, where: Optional[Dict[str, Any]] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        if not self.collection:
            return []

        try:
            safe_limit = max(1, min(int(limit or 1000), 5000))
            results = self.collection.get(
                where=where,
                include=["metadatas"],
                limit=safe_limit,
            )
            ids = list(results.get("ids") or [])
            metadatas = list(results.get("metadatas") or [])
            items = []
            for index, item_id in enumerate(ids):
                items.append({
                    "id": item_id,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                })
            return items
        except Exception as e:
            logger.error(f"Vector metadata listing failed: {e}")
            return []

    def delete(self, where: Dict[str, Any]) -> None:
        """删除记录"""
        if not self.collection:
            return
        try:
            self.collection.delete(where=where)
        except Exception as e:
            logger.error(f"Vector delete failed: {e}")

    def count(self, where: Optional[Dict[str, Any]] = None) -> int:
        if not self.collection:
            return 0
        try:
            if where:
                results = self.collection.get(where=where, include=[])
                return len(results.get("ids") or [])
            return int(self.collection.count())
        except Exception as e:
            logger.error(f"Vector count failed: {e}")
            return 0
