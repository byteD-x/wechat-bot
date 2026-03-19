"""
向量记忆管理模块 - 基于 ChromaDB 实现 RAG

功能：
- 存储和检索历史对话的向量表示
- 支持基于语义的上下文检索
"""

import os
import logging
from typing import List, Dict, Optional, Any
from backend.shared_config import ensure_data_root
from ..utils.runtime_artifacts import chdir_temporarily, CHROMA_DIR, relocate_known_root_artifacts

logger = logging.getLogger(__name__)

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
