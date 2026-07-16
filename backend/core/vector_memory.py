"""
向量记忆管理模块 - 基于 SQLite 实现轻量 RAG

设计:
- 复用项目已有的 SQLite 依赖,不引入 ChromaDB / onnxruntime / 其它重型向量库。
- embedding 以 JSON 数组存储,检索时在 Python 内做余弦相似度(暴力 KNN)。
  个人助手规模(RAG 默认关闭,单会话至多数千条片段)下,暴力检索延迟在毫秒级,
  无需 ANN 索引与编译扩展。
- 距离语义与原实现保持一致:``distance = 1 - cosine_similarity``(取值 [0, 2]),
  上层按 ``max(0, 1 - distance)`` 折算相似度。
"""

import json
import logging
import math
import os
import re
import sqlite3
import threading
from collections import Counter
from typing import List, Dict, Optional, Any

from backend.shared_config import ensure_data_root

logger = logging.getLogger(__name__)

_KEYWORD_TOKEN_RE = re.compile(r"[0-9a-zA-Z一-鿿]+")

# metadata 中用于快速过滤的热点键,单独抽列并建索引;其余键回退 json_extract。
_INDEXED_META_KEYS = ("source", "chat_id", "doc_id")


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


def _cosine_distance(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 1.0
    similarity = dot / (math.sqrt(norm_left) * math.sqrt(norm_right))
    # 数值裁剪,避免浮点误差导致相似度略超 [-1, 1]
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


class VectorMemory:
    """SQLite 后端的向量记忆。公开接口与旧 ChromaDB 实现保持一致。"""

    def __init__(self, db_path: Optional[str] = None):
        # 兼容旧契约:db_path 是一个目录,库文件落在其中,便于沿用既有配置。
        if not db_path:
            db_path = str(ensure_data_root() / "vector_db")
        self.db_path = os.path.abspath(db_path)
        os.makedirs(self.db_path, exist_ok=True)
        self._db_file = os.path.join(self.db_path, "vectors.sqlite3")

        self._lock = threading.Lock()
        self.conn: Optional[sqlite3.Connection] = None
        try:
            self.conn = sqlite3.connect(self._db_file, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
            logger.info("VectorMemory (sqlite) initialized at %s", self._db_file)
        except Exception as exc:
            logger.error("Failed to initialize SQLite vector memory: %s", exc)
            self.conn = None

    def _init_schema(self) -> None:
        assert self.conn is not None
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                embedding TEXT,
                source TEXT,
                chat_id TEXT,
                doc_id TEXT
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_source_chat ON vectors(source, chat_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_source_doc ON vectors(source, doc_id)"
        )
        self.conn.commit()

    def __bool__(self) -> bool:
        return self.conn is not None

    @staticmethod
    def _build_where(filter_meta: Optional[Dict[str, Any]]) -> tuple[str, list]:
        """把扁平等值过滤字典翻译为 SQL WHERE 子句(隐式 AND)。"""
        if not filter_meta:
            return "", []
        clauses: List[str] = []
        params: list = []
        for key, value in filter_meta.items():
            if key in _INDEXED_META_KEYS:
                clauses.append(f"{key} = ?")
                params.append(None if value is None else str(value))
            else:
                clauses.append("json_extract(metadata, '$.' || ?) = ?")
                params.append(str(key))
                params.append(value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def _write(self, text: str, metadata: Dict[str, Any], id: str, embedding: Optional[List[float]]) -> None:
        if self.conn is None:
            return
        meta = dict(metadata or {})
        embedding_json = json.dumps([float(x) for x in embedding]) if embedding else None
        row = (
            str(id),
            str(text or ""),
            json.dumps(meta, ensure_ascii=False),
            embedding_json,
            None if meta.get("source") is None else str(meta.get("source")),
            None if meta.get("chat_id") is None else str(meta.get("chat_id")),
            None if meta.get("doc_id") is None else str(meta.get("doc_id")),
        )
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO vectors "
                    "(id, text, metadata, embedding, source, chat_id, doc_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                self.conn.commit()
        except Exception as exc:
            logger.error("Failed to write text to vector db: %s", exc)

    def add_text(self, text: str, metadata: Dict[str, Any], id: str, embedding: Optional[List[float]] = None) -> None:
        self._write(text, metadata, id, embedding)

    def upsert_text(self, text: str, metadata: Dict[str, Any], id: str, embedding: Optional[List[float]] = None) -> None:
        self._write(text, metadata, id, embedding)

    def _fetch_rows(self, columns: str, filter_meta: Optional[Dict[str, Any]], limit: Optional[int]) -> List[sqlite3.Row]:
        where, params = self._build_where(filter_meta)
        sql = f"SELECT {columns} FROM vectors{where}"
        if limit is not None:
            sql += " LIMIT ?"
            params = [*params, int(limit)]
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())

    def search(
        self,
        query: Optional[str] = None,
        n_results: int = 5,
        filter_meta: Optional[Dict] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        if self.conn is None:
            return []
        top_n = max(1, int(n_results or 1))
        # 无 embedding 时回退关键词检索(不再依赖内置 ONNX 文本向量化)。
        if not query_embedding:
            return self.keyword_search(query or "", n_results=top_n, filter_meta=filter_meta)

        try:
            rows = self._fetch_rows("id, text, metadata, embedding", filter_meta, limit=None)
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            return []

        scored: List[Dict[str, Any]] = []
        for row in rows:
            if not row["embedding"]:
                continue
            try:
                vector = json.loads(row["embedding"])
            except (TypeError, ValueError):
                continue
            distance = _cosine_distance(query_embedding, vector)
            scored.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "distance": distance,
                }
            )
        scored.sort(key=lambda item: item["distance"])
        return scored[:top_n]

    def keyword_search(
        self,
        query: str,
        n_results: int = 5,
        filter_meta: Optional[Dict] = None,
        candidate_limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if self.conn is None:
            return []
        try:
            limit = max(int(n_results or 1), min(max(int(candidate_limit or 1), int(n_results or 1)), 1000))
            rows = self._fetch_rows("id, text, metadata", filter_meta, limit=limit)
            candidates = [
                {
                    "id": row["id"],
                    "text": row["text"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                }
                for row in rows
            ]
            return _rank_keyword_candidates(query, candidates)[: max(1, int(n_results or 1))]
        except Exception as exc:
            logger.error("Keyword search failed: %s", exc)
            return []

    def list_metadata(self, where: Optional[Dict[str, Any]] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        if self.conn is None:
            return []
        try:
            safe_limit = max(1, min(int(limit or 1000), 5000))
            rows = self._fetch_rows("id, metadata", where, limit=safe_limit)
            return [
                {
                    "id": row["id"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Vector metadata listing failed: %s", exc)
            return []

    def delete(self, where: Dict[str, Any]) -> None:
        if self.conn is None:
            return
        try:
            clause, params = self._build_where(where)
            with self._lock:
                self.conn.execute(f"DELETE FROM vectors{clause}", params)
                self.conn.commit()
        except Exception as exc:
            logger.error("Vector delete failed: %s", exc)

    def count(self, where: Optional[Dict[str, Any]] = None) -> int:
        if self.conn is None:
            return 0
        try:
            clause, params = self._build_where(where)
            with self._lock:
                cursor = self.conn.execute(f"SELECT COUNT(*) FROM vectors{clause}", params)
                return int(cursor.fetchone()[0])
        except Exception as exc:
            logger.error("Vector count failed: %s", exc)
            return 0



