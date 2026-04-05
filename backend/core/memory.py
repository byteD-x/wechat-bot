"""
聊天记忆管理模块 - 基于 aiosqlite 的异步持久化存储。

本模块提供了轻量级的聊天历史和用户画像管理功能：
- 按会话存储用户/助手消息历史
- 支持 TTL 自动清理过期记录
- 用户画像管理（昵称、关系、偏好、事实记忆）
- 情绪历史记录

主要类:
    MemoryManager: 核心管理器类，封装了所有数据库操作

使用示例:
    manager = MemoryManager("data/chat_memory.db")
    await manager.add_message("user_123", "user", "你好！")
    context = await manager.get_recent_context("user_123", limit=10)
    await manager.close()
"""

from __future__ import annotations

import json
import os
import time
import copy
import asyncio
import importlib
import sys
import aiosqlite
from typing import Any, Dict, Iterable, List, Optional, Tuple
from ..schemas import UserProfile

# ═══════════════════════════════════════════════════════════════════════════════
#                               常量定义
# ═══════════════════════════════════════════════════════════════════════════════

# 使用 frozenset 加速成员检查（O(1) 复杂度）
ALLOWED_ROLES: frozenset = frozenset({"user", "assistant", "system"})

# JSON 字段集合（优化 update_user_profile 中的字段类型检查）
_JSON_FIELDS: frozenset = frozenset({"preferences", "context_facts", "emotion_history"})
_PENDING_REPLY_STATUSES: frozenset = frozenset({
    "pending",
    "approved",
    "rejected",
    "expired",
    "failed",
})

# 默认用户画像模板
DEFAULT_USER_PROFILE = {
    "nickname": "",
    "relationship": "unknown",  # unknown/friend/close_friend/family/colleague/stranger
    "personality": "",
    "preferences": {},  # {"topics": [], "style": "", "likes": [], "dislikes": []}
    "context_facts": [],  # ["生日是5月1日", "喜欢猫", ...]
    "last_emotion": "neutral",
    "profile_summary": "",
    "contact_prompt": "",
    "contact_prompt_updated_at": 0,
    "contact_prompt_source": "",
    "contact_prompt_last_message_count": 0,
    "emotion_history": [],  # 最近 N 次情绪记录
    "message_count": 0,
}


def _resolve_aiosqlite_module():
    module = aiosqlite
    if hasattr(module, "connect") and hasattr(module, "Row"):
        return module

    sys.modules.pop("aiosqlite", None)
    resolved = importlib.import_module("aiosqlite")
    globals()["aiosqlite"] = resolved
    return resolved


# ═══════════════════════════════════════════════════════════════════════════════
#                               记忆管理器类
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryManager:
    """
    基于 aiosqlite 的异步聊天历史存储管理器。
    
    支持消息历史存储、用户画像管理、TTL 自动清理等功能。
    
    Attributes:
        db_path (str): SQLite 数据库文件路径
    """
    
    # 允许更新的用户画像字段（使用 frozenset 加速查找）
    _ALLOWED_PROFILE_FIELDS: frozenset = frozenset({
        "nickname", "relationship", "personality", "preferences",
        "context_facts", "last_emotion", "emotion_history", "profile_summary",
        "contact_prompt", "contact_prompt_updated_at", "contact_prompt_source",
        "contact_prompt_last_message_count", "message_count"
    })

    def __init__(
        self,
        db_path: str = "data/chat_memory.db",
        ttl_sec: Optional[float] = None,
        cleanup_interval_sec: float = 300.0,
    ) -> None:
        self.db_path = os.path.abspath(db_path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._ttl_sec = self._normalize_ttl(ttl_sec)
        self._cleanup_interval_sec = self._normalize_interval(cleanup_interval_sec)
        self._last_cleanup_ts = 0.0
        self._init_lock = asyncio.Lock() # 防止并发初始化

    async def __aenter__(self) -> "MemoryManager":
        """异步上下文管理器入口。"""
        await self._get_db()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口，自动关闭连接。"""
        await self.close()

    async def _get_db(self) -> aiosqlite.Connection:
        """获取数据库连接（懒加载）"""
        if self._conn:
            return self._conn
            
        async with self._init_lock:
            if self._conn:
                return self._conn
                
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
                
            sqlite_module = _resolve_aiosqlite_module()
            self._conn = await sqlite_module.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite_module.Row
            await self._init_tables()
            return self._conn

    async def initialize(self) -> aiosqlite.Connection:
        """显式初始化数据库连接，避免健康检查误报未连接。"""
        return await self._get_db()

    async def _init_tables(self) -> None:
        """初始化数据库表结构"""
        if not self._conn:
            return
            
        # 聊天历史表
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "wx_id TEXT NOT NULL,"
            "role TEXT NOT NULL,"
            "content TEXT NOT NULL,"
            "created_at INTEGER NOT NULL,"
            "metadata TEXT DEFAULT '{}'"
            ")"
        )
        # 索引：按 wx_id 和 id 查询（用于获取最近消息）
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_history_wx_id_id "
            "ON chat_history (wx_id, id)"
        )
        # 索引：按 created_at 查询（用于 TTL 清理，大幅提升清理性能）
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_history_created_at "
            "ON chat_history (created_at)"
        )
        # 用户画像表
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS user_profiles ("
            "wx_id TEXT PRIMARY KEY,"
            "nickname TEXT DEFAULT '',"
            "relationship TEXT DEFAULT 'unknown',"
            "personality TEXT DEFAULT '',"
            "preferences TEXT DEFAULT '{}',"
            "context_facts TEXT DEFAULT '[]',"
            "last_emotion TEXT DEFAULT 'neutral',"
            "emotion_history TEXT DEFAULT '[]',"
            "profile_summary TEXT DEFAULT '',"
            "contact_prompt TEXT DEFAULT '',"
            "contact_prompt_updated_at INTEGER DEFAULT 0,"
            "contact_prompt_source TEXT DEFAULT '',"
            "contact_prompt_last_message_count INTEGER DEFAULT 0,"
            "message_count INTEGER DEFAULT 0,"
            "updated_at INTEGER NOT NULL"
            ")"
        )
        # 索引：按 updated_at 查询（用于活跃用户排序）
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_updated_at "
            "ON user_profiles (updated_at)"
        )
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS background_backlog ("
            "chat_id TEXT NOT NULL,"
            "task_type TEXT NOT NULL,"
            "payload TEXT DEFAULT '{}',"
            "updated_at INTEGER NOT NULL,"
            "PRIMARY KEY (chat_id, task_type)"
            ")"
        )
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_replies ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "chat_id TEXT NOT NULL,"
            "source_message_id TEXT DEFAULT '',"
            "trigger_reason TEXT NOT NULL,"
            "draft_reply TEXT NOT NULL,"
            "metadata_json TEXT DEFAULT '{}',"
            "status TEXT NOT NULL DEFAULT 'pending',"
            "created_at INTEGER NOT NULL,"
            "resolved_at INTEGER DEFAULT NULL"
            ")"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_background_backlog_updated_at "
            "ON background_backlog (updated_at)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_replies_status_created_at "
            "ON pending_replies (status, created_at DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_replies_chat_id "
            "ON pending_replies (chat_id, created_at DESC)"
        )
        # 启用 WAL 模式提升并发性能
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # 启用 synchronous = NORMAL (WAL模式下安全且更快)
        await self._conn.execute("PRAGMA synchronous = NORMAL")
        # 将临时表存储在内存中
        await self._conn.execute("PRAGMA temp_store = MEMORY")
        # 启用内存映射 I/O 提升读取性能
        await self._conn.execute("PRAGMA mmap_size=268435456")
        await self._ensure_column("chat_history", "metadata", "TEXT DEFAULT '{}'")
        await self._ensure_column("user_profiles", "profile_summary", "TEXT DEFAULT ''")
        await self._ensure_column("user_profiles", "contact_prompt", "TEXT DEFAULT ''")
        await self._ensure_column("user_profiles", "contact_prompt_updated_at", "INTEGER DEFAULT 0")
        await self._ensure_column("user_profiles", "contact_prompt_source", "TEXT DEFAULT ''")
        await self._ensure_column("user_profiles", "contact_prompt_last_message_count", "INTEGER DEFAULT 0")
        await self._conn.commit()

    async def _ensure_column(self, table: str, column: str, definition: str) -> None:
        if not self._conn:
            return
        async with self._conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
        existing = {str(row["name"]).strip().lower() for row in rows}
        if column.lower() in existing:
            return
        await self._conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )

    @staticmethod
    def _serialize_metadata(metadata: Optional[Dict[str, Any]]) -> str:
        if not isinstance(metadata, dict) or not metadata:
            return "{}"
        try:
            return json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError):
            return "{}"

    @staticmethod
    def _deserialize_metadata(raw: Any) -> Dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return copy.deepcopy(raw)
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _normalize_pending_reply_status(value: Any) -> str:
        status = str(value or "pending").strip().lower() or "pending"
        return status if status in _PENDING_REPLY_STATUSES else "pending"

    def _row_to_pending_reply(self, row: Any) -> Dict[str, Any]:
        return {
            "id": int(row["id"] or 0),
            "chat_id": str(row["chat_id"] or ""),
            "source_message_id": str(row["source_message_id"] or ""),
            "trigger_reason": str(row["trigger_reason"] or ""),
            "draft_reply": str(row["draft_reply"] or ""),
            "metadata": self._deserialize_metadata(row["metadata_json"]),
            "status": self._normalize_pending_reply_status(row["status"]),
            "created_at": int(row["created_at"] or 0),
            "resolved_at": int(row["resolved_at"] or 0) if row["resolved_at"] is not None else None,
        }

    @staticmethod
    def _normalize_ttl(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        try:
            val = float(value)
        except (TypeError, ValueError):
            return None
        if val <= 0:
            return None
        return val

    @staticmethod
    def _normalize_interval(value: Optional[float]) -> float:
        try:
            val = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, val)

    @staticmethod
    def _build_profile_summary(profile: Dict[str, Any]) -> str:
        summary_parts: List[str] = []

        relationship = str(profile.get("relationship") or "").strip()
        if relationship and relationship != "unknown":
            summary_parts.append(f"关系: {relationship}")

        personality = str(profile.get("personality") or "").strip()
        if personality:
            summary_parts.append(f"风格: {personality}")

        preferences = profile.get("preferences") or {}
        if isinstance(preferences, dict):
            topics = preferences.get("topics") or []
            likes = preferences.get("likes") or []
            dislikes = preferences.get("dislikes") or []
            style = str(preferences.get("style") or "").strip()

            topic_text = "、".join(str(item).strip() for item in topics if str(item).strip())
            like_text = "、".join(str(item).strip() for item in likes if str(item).strip())
            dislike_text = "、".join(str(item).strip() for item in dislikes if str(item).strip())

            if topic_text:
                summary_parts.append(f"常聊: {topic_text}")
            if like_text:
                summary_parts.append(f"偏好: {like_text}")
            if dislike_text:
                summary_parts.append(f"避开: {dislike_text}")
            if style:
                summary_parts.append(f"语气: {style}")

        facts = [
            str(item).strip()
            for item in (profile.get("context_facts") or [])[:5]
            if str(item).strip()
        ]
        if facts:
            summary_parts.append("已知事实: " + "；".join(facts))

        last_emotion = str(profile.get("last_emotion") or "").strip().lower()
        if last_emotion and last_emotion != "neutral":
            summary_parts.append(f"近期情绪: {last_emotion}")

        return " | ".join(part for part in summary_parts if part).strip()

    async def update_retention(
        self,
        ttl_sec: Optional[float],
        cleanup_interval_sec: Optional[float] = None,
    ) -> None:
        self._ttl_sec = self._normalize_ttl(ttl_sec)
        if cleanup_interval_sec is not None:
            self._cleanup_interval_sec = self._normalize_interval(
                cleanup_interval_sec
            )
        await self._maybe_cleanup(force=True)

    async def _maybe_cleanup(self, force: bool = False) -> None:
        if not self._ttl_sec:
            return
        now = time.time()
        if not force and self._cleanup_interval_sec > 0:
            if now - self._last_cleanup_ts < self._cleanup_interval_sec:
                return
        cutoff = int(now - self._ttl_sec)
        if cutoff <= 0:
            return
            
        db = await self._get_db()
        await db.execute(
            "DELETE FROM chat_history WHERE created_at < ?",
            (cutoff,),
        )
        await db.commit()
        self._last_cleanup_ts = now

    async def upsert_background_backlog(
        self,
        chat_id: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        chat_id = str(chat_id).strip()
        task_type = str(task_type).strip()
        if not chat_id or not task_type:
            return
        db = await self._get_db()
        await db.execute(
            "INSERT INTO background_backlog (chat_id, task_type, payload, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, task_type) DO UPDATE SET "
            "payload = excluded.payload, "
            "updated_at = excluded.updated_at",
            (
                chat_id,
                task_type,
                self._serialize_metadata(payload),
                int(time.time()),
            ),
        )
        await db.commit()

    async def list_background_backlog(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = (
            "SELECT chat_id, task_type, payload, updated_at "
            "FROM background_backlog "
            "ORDER BY updated_at ASC"
        )
        params: Tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (max(1, int(limit)),)
        db = await self._get_db()
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "chat_id": str(row["chat_id"] or ""),
                "task_type": str(row["task_type"] or ""),
                "payload": self._deserialize_metadata(row["payload"]),
                "updated_at": int(row["updated_at"] or 0),
            }
            for row in rows
        ]

    async def delete_background_backlog(self, chat_id: str, task_type: str) -> None:
        chat_id = str(chat_id).strip()
        task_type = str(task_type).strip()
        if not chat_id or not task_type:
            return
        db = await self._get_db()
        await db.execute(
            "DELETE FROM background_backlog WHERE chat_id = ? AND task_type = ?",
            (chat_id, task_type),
        )
        await db.commit()

    async def get_background_backlog_stats(self) -> Dict[str, Any]:
        db = await self._get_db()
        async with db.execute(
            "SELECT task_type, COUNT(*) AS total, MAX(updated_at) AS latest_updated_at "
            "FROM background_backlog GROUP BY task_type"
        ) as cursor:
            rows = await cursor.fetchall()
        total = 0
        latest_updated_at = 0
        by_task_type: Dict[str, int] = {}
        for row in rows:
            task_type = str(row["task_type"] or "").strip()
            count = int(row["total"] or 0)
            total += count
            if task_type:
                by_task_type[task_type] = count
            latest_updated_at = max(latest_updated_at, int(row["latest_updated_at"] or 0))
        return {
            "total": total,
            "by_task_type": by_task_type,
            "latest_updated_at": latest_updated_at,
        }

    async def create_pending_reply(
        self,
        *,
        chat_id: str,
        source_message_id: str,
        trigger_reason: str,
        draft_reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        chat_id_val = str(chat_id or "").strip()
        trigger_reason_val = str(trigger_reason or "").strip()
        draft_reply_val = str(draft_reply or "").strip()
        if not chat_id_val:
            raise ValueError("chat_id is required")
        if not trigger_reason_val:
            raise ValueError("trigger_reason is required")
        if not draft_reply_val:
            raise ValueError("draft_reply is required")

        db = await self._get_db()
        created_at = int(time.time())
        cursor = await db.execute(
            "INSERT INTO pending_replies ("
            "chat_id, source_message_id, trigger_reason, draft_reply, metadata_json, status, created_at, resolved_at"
            ") VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)",
            (
                chat_id_val,
                str(source_message_id or "").strip(),
                trigger_reason_val,
                draft_reply_val,
                self._serialize_metadata(metadata),
                created_at,
            ),
        )
        await db.commit()
        return await self.get_pending_reply(int(cursor.lastrowid or 0)) or {}

    async def get_pending_reply(self, pending_id: int) -> Optional[Dict[str, Any]]:
        try:
            pending_id_val = int(pending_id)
        except (TypeError, ValueError):
            return None
        if pending_id_val <= 0:
            return None

        db = await self._get_db()
        async with db.execute(
            "SELECT id, chat_id, source_message_id, trigger_reason, draft_reply, metadata_json, status, created_at, resolved_at "
            "FROM pending_replies WHERE id = ? LIMIT 1",
            (pending_id_val,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_pending_reply(row)

    async def list_pending_replies(
        self,
        *,
        chat_id: str = "",
        status: Optional[str] = "pending",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 50
        limit_val = max(1, min(limit_val, 200))

        where_clauses: List[str] = []
        params: List[Any] = []
        chat_id_val = str(chat_id or "").strip()
        if chat_id_val:
            where_clauses.append("chat_id = ?")
            params.append(chat_id_val)

        status_val = None if status is None else self._normalize_pending_reply_status(status)
        if status is not None:
            where_clauses.append("status = ?")
            params.append(status_val)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        db = await self._get_db()
        async with db.execute(
            "SELECT id, chat_id, source_message_id, trigger_reason, draft_reply, metadata_json, status, created_at, resolved_at "
            f"FROM pending_replies {where_sql} ORDER BY created_at DESC LIMIT ?",
            (*params, limit_val),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_pending_reply(row) for row in rows]

    async def resolve_pending_reply(
        self,
        pending_id: int,
        *,
        status: str,
        draft_reply: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        status_val = self._normalize_pending_reply_status(status)
        if status_val == "pending":
            raise ValueError("resolved status cannot be pending")

        current = await self.get_pending_reply(pending_id)
        if current is None:
            return None

        next_draft_reply = str(draft_reply or current.get("draft_reply") or "").strip()
        if not next_draft_reply:
            next_draft_reply = str(current.get("draft_reply") or "")
        next_metadata = dict(current.get("metadata") or {})
        if isinstance(metadata, dict) and metadata:
            next_metadata.update(metadata)

        db = await self._get_db()
        await db.execute(
            "UPDATE pending_replies SET draft_reply = ?, metadata_json = ?, status = ?, resolved_at = ? WHERE id = ?",
            (
                next_draft_reply,
                self._serialize_metadata(next_metadata),
                status_val,
                int(time.time()),
                int(pending_id),
            ),
        )
        await db.commit()
        return await self.get_pending_reply(pending_id)

    async def update_pending_reply(
        self,
        pending_id: int,
        *,
        draft_reply: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        current = await self.get_pending_reply(pending_id)
        if current is None:
            return None

        next_draft_reply = str(draft_reply or current.get("draft_reply") or "").strip()
        if not next_draft_reply:
            next_draft_reply = str(current.get("draft_reply") or "")
        next_metadata = dict(current.get("metadata") or {})
        if isinstance(metadata, dict) and metadata:
            next_metadata.update(metadata)

        db = await self._get_db()
        await db.execute(
            "UPDATE pending_replies SET draft_reply = ?, metadata_json = ? WHERE id = ?",
            (
                next_draft_reply,
                self._serialize_metadata(next_metadata),
                int(pending_id),
            ),
        )
        await db.commit()
        return await self.get_pending_reply(pending_id)

    async def expire_pending_replies(self, *, created_before: int) -> int:
        try:
            cutoff = int(created_before)
        except (TypeError, ValueError):
            return 0
        db = await self._get_db()
        cursor = await db.execute(
            "UPDATE pending_replies SET status = 'expired', resolved_at = ? "
            "WHERE status = 'pending' AND created_at < ?",
            (int(time.time()), cutoff),
        )
        await db.commit()
        return int(getattr(cursor, "rowcount", 0) or 0)

    async def get_pending_reply_stats(self) -> Dict[str, Any]:
        db = await self._get_db()
        async with db.execute(
            "SELECT status, COUNT(*) AS total, MAX(created_at) AS latest_created_at "
            "FROM pending_replies GROUP BY status"
        ) as cursor:
            rows = await cursor.fetchall()
        by_status: Dict[str, int] = {}
        latest_created_at = 0
        total = 0
        for row in rows:
            status = self._normalize_pending_reply_status(row["status"])
            count = int(row["total"] or 0)
            by_status[status] = count
            total += count
            latest_created_at = max(latest_created_at, int(row["latest_created_at"] or 0))
        return {
            "total": total,
            "pending": int(by_status.get("pending", 0) or 0),
            "approved": int(by_status.get("approved", 0) or 0),
            "rejected": int(by_status.get("rejected", 0) or 0),
            "expired": int(by_status.get("expired", 0) or 0),
            "failed": int(by_status.get("failed", 0) or 0),
            "by_status": by_status,
            "latest_created_at": latest_created_at,
        }

    async def has_messages(self, wx_id: str) -> bool:
        wx_id = str(wx_id).strip()
        if not wx_id:
            return False
        await self._maybe_cleanup()
        
        db = await self._get_db()
        async with db.execute(
            "SELECT 1 FROM chat_history WHERE wx_id = ? LIMIT 1",
            (wx_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def add_message(
        self,
        wx_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        wx_id = str(wx_id).strip()
        if not wx_id:
            return
        role = str(role).strip().lower()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Unsupported role: {role}")
        content = str(content or "").strip()
        if not content:
            return
        await self._maybe_cleanup()
        created_at = int(time.time())
        
        db = await self._get_db()
        await db.execute(
            "INSERT INTO chat_history (wx_id, role, content, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (wx_id, role, content, created_at, self._serialize_metadata(metadata)),
        )
        await db.commit()

    async def add_messages(self, wx_id: str, messages: Iterable[dict]) -> int:
        wx_id = str(wx_id).strip()
        if not wx_id:
            return 0
        await self._maybe_cleanup()
        created_at = int(time.time())
        rows = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).strip().lower()
            if role not in ALLOWED_ROLES:
                continue
            content = str(msg.get("content", "") or "").strip()
            if not content:
                continue
            rows.append(
                (
                    wx_id,
                    role,
                    content,
                    created_at,
                    self._serialize_metadata(msg.get("metadata")),
                )
            )
        if not rows:
            return 0
            
        db = await self._get_db()
        await db.executemany(
            "INSERT INTO chat_history (wx_id, role, content, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()
        return len(rows)

    async def get_recent_context(self, wx_id: str, limit: int = 20) -> List[dict]:
        wx_id = str(wx_id).strip()
        if not wx_id:
            return []
        await self._maybe_cleanup()
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 20
        if limit_val <= 0:
            return []
            
        db = await self._get_db()
        async with db.execute(
            "SELECT role, content FROM chat_history "
            "WHERE wx_id = ? ORDER BY id DESC LIMIT ?",
            (wx_id, limit_val),
        ) as cursor:
            rows = await cursor.fetchall()
            
        context: List[dict] = []
        for row in reversed(rows):
            content = row["content"]
            if not content:
                continue
            context.append({"role": row["role"], "content": content})
        return context

    async def get_recent_context_batch(
        self,
        wx_ids: Iterable[str],
        limit: int = 20,
    ) -> Dict[str, List[dict]]:
        """Fetch recent contexts for multiple chats in one query."""
        normalized_ids = []
        for raw in wx_ids:
            wx_id = str(raw or "").strip()
            if wx_id and wx_id not in normalized_ids:
                normalized_ids.append(wx_id)
        if not normalized_ids:
            return {}

        await self._maybe_cleanup()
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 20
        if limit_val <= 0:
            return {wx_id: [] for wx_id in normalized_ids}

        placeholders = ", ".join("?" for _ in normalized_ids)
        sql = f"""
            SELECT wx_id, role, content
            FROM (
                SELECT
                    wx_id,
                    role,
                    content,
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY wx_id
                        ORDER BY id DESC
                    ) AS row_num
                FROM chat_history
                WHERE wx_id IN ({placeholders})
            ) ranked
            WHERE row_num <= ?
            ORDER BY wx_id ASC, id ASC
        """

        db = await self._get_db()
        params = [*normalized_ids, limit_val]
        async with db.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()

        context_map: Dict[str, List[dict]] = {
            wx_id: [] for wx_id in normalized_ids
        }
        for row in rows:
            content = row["content"]
            if not content:
                continue
            context_map.setdefault(row["wx_id"], []).append(
                {"role": row["role"], "content": content}
            )
        return context_map

    async def get_global_recent_messages(self, limit: int = 50) -> List[dict]:
        """
        获取全局最近消息历史（跨所有会话）。
        """
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 50
        
        if limit_val <= 0:
            return []
            
        db = await self._get_db()
        
        # 使用 left join 获取 nickname
        sql = """
            SELECT 
                h.id, h.wx_id, h.role, h.content, h.created_at, h.metadata,
                u.nickname, u.relationship
            FROM chat_history h
            LEFT JOIN user_profiles u ON h.wx_id = u.wx_id
            ORDER BY h.id DESC
            LIMIT ?
        """
        async with db.execute(sql, (limit_val,)) as cursor:
            rows = await cursor.fetchall()
            
        messages = []
        for row in reversed(rows):
            msg = {
                "id": row["id"],
                "wx_id": row["wx_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["created_at"],
                "sender": row["nickname"] or row["wx_id"],
                "is_self": row["role"] == "assistant",
                "metadata": self._deserialize_metadata(row["metadata"]),
            }
            messages.append(msg)
            
        return messages

    async def get_message_page(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        chat_id: str = "",
        keyword: str = "",
    ) -> Dict[str, Any]:
        """按条件分页获取消息列表。"""
        await self._maybe_cleanup()

        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 50
        limit_val = max(1, min(limit_val, 200))

        try:
            offset_val = int(offset)
        except (TypeError, ValueError):
            offset_val = 0
        offset_val = max(0, offset_val)

        chat_id_val = str(chat_id or "").strip()
        keyword_val = str(keyword or "").strip()
        like_value = f"%{keyword_val}%"

        where_clauses: List[str] = []
        params: List[Any] = []
        if chat_id_val:
            where_clauses.append("h.wx_id = ?")
            params.append(chat_id_val)
        if keyword_val:
            where_clauses.append(
                "("
                "h.content LIKE ? "
                "OR COALESCE(u.nickname, '') LIKE ? "
                "OR h.wx_id LIKE ?"
                ")"
            )
            params.extend([like_value, like_value, like_value])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        db = await self._get_db()

        count_sql = (
            "SELECT COUNT(*) "
            "FROM chat_history h "
            "LEFT JOIN user_profiles u ON h.wx_id = u.wx_id "
            f"{where_sql}"
        )
        async with db.execute(count_sql, tuple(params)) as cursor:
            count_row = await cursor.fetchone()
        total = int(count_row[0]) if count_row else 0

        query_sql = (
            "SELECT "
            "h.id, h.wx_id, h.role, h.content, h.created_at, h.metadata, "
            "u.nickname, u.relationship "
            "FROM chat_history h "
            "LEFT JOIN user_profiles u ON h.wx_id = u.wx_id "
            f"{where_sql} "
            "ORDER BY h.id DESC "
            "LIMIT ? OFFSET ?"
        )
        query_params = [*params, limit_val, offset_val]
        async with db.execute(query_sql, tuple(query_params)) as cursor:
            rows = await cursor.fetchall()

        messages: List[Dict[str, Any]] = []
        for row in rows:
            display_name = str(row["nickname"] or row["wx_id"] or "").strip()
            role = str(row["role"] or "").strip().lower()
            messages.append({
                "id": row["id"],
                "wx_id": row["wx_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["created_at"],
                "sender": "AI" if role == "assistant" else display_name,
                "sender_display_name": "AI" if role == "assistant" else display_name,
                "display_name": display_name,
                "chat_display_name": display_name,
                "is_self": role == "assistant",
                "relationship": row["relationship"] or "unknown",
                "metadata": self._deserialize_metadata(row["metadata"]),
            })

        return {
            "messages": messages,
            "total": total,
            "limit": limit_val,
            "offset": offset_val,
            "has_more": offset_val + len(messages) < total,
        }

    async def update_message_feedback(
        self,
        message_id: int,
        feedback: str,
    ) -> Optional[Dict[str, Any]]:
        """更新指定消息的人工反馈，并返回最新消息记录。"""
        await self._maybe_cleanup()

        try:
            message_id_val = int(message_id)
        except (TypeError, ValueError):
            return None
        if message_id_val <= 0:
            return None

        normalized_feedback = str(feedback or "").strip().lower()
        if normalized_feedback not in {"", "helpful", "unhelpful"}:
            raise ValueError(f"Unsupported feedback: {feedback}")

        db = await self._get_db()
        async with db.execute(
            "SELECT id, wx_id, role, content, created_at, metadata "
            "FROM chat_history WHERE id = ? LIMIT 1",
            (message_id_val,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        metadata = self._deserialize_metadata(row["metadata"])
        reply_quality = dict(metadata.get("reply_quality") or {})
        previous_feedback = str(reply_quality.get("user_feedback") or "").strip().lower()

        if normalized_feedback:
            reply_quality["user_feedback"] = normalized_feedback
            reply_quality["feedback_updated_at"] = int(time.time())
        else:
            reply_quality.pop("user_feedback", None)
            reply_quality.pop("feedback_updated_at", None)

        if reply_quality:
            metadata["reply_quality"] = reply_quality
        else:
            metadata.pop("reply_quality", None)

        await db.execute(
            "UPDATE chat_history SET metadata = ? WHERE id = ?",
            (self._serialize_metadata(metadata), message_id_val),
        )
        await db.commit()

        return {
            "id": int(row["id"] or 0),
            "wx_id": str(row["wx_id"] or ""),
            "role": str(row["role"] or ""),
            "content": str(row["content"] or ""),
            "created_at": int(row["created_at"] or 0),
            "metadata": metadata,
            "previous_feedback": previous_feedback,
            "feedback": normalized_feedback,
        }

    async def list_chat_summaries(self, limit: int = 200) -> List[Dict[str, Any]]:
        """返回消息中心可用的会话摘要。"""
        await self._maybe_cleanup()

        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 200
        limit_val = max(1, min(limit_val, 500))

        db = await self._get_db()
        sql = """
            SELECT
                h.wx_id,
                COALESCE(u.nickname, h.wx_id) AS display_name,
                COUNT(*) AS message_count,
                MAX(h.created_at) AS last_timestamp
            FROM chat_history h
            LEFT JOIN user_profiles u ON h.wx_id = u.wx_id
            GROUP BY h.wx_id, COALESCE(u.nickname, h.wx_id)
            ORDER BY MAX(h.id) DESC
            LIMIT ?
        """
        async with db.execute(sql, (limit_val,)) as cursor:
            rows = await cursor.fetchall()

        chats: List[Dict[str, Any]] = []
        for row in rows:
            chats.append({
                "chat_id": row["wx_id"],
                "display_name": row["display_name"],
                "message_count": int(row["message_count"] or 0),
                "last_timestamp": row["last_timestamp"],
            })
        return chats

    async def list_messages_for_analysis(
        self,
        *,
        chat_id: str = "",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """按时间范围读取原始消息，用于成本/分析类只读聚合。"""
        await self._maybe_cleanup()

        where_clauses: List[str] = []
        params: List[Any] = []

        chat_id_val = str(chat_id or "").strip()
        if chat_id_val:
            where_clauses.append("h.wx_id = ?")
            params.append(chat_id_val)

        if start_timestamp is not None:
            where_clauses.append("h.created_at >= ?")
            params.append(int(start_timestamp))

        if end_timestamp is not None:
            where_clauses.append("h.created_at <= ?")
            params.append(int(end_timestamp))

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            params.append(max(1, int(limit)))

        query_sql = (
            "SELECT "
            "h.id, h.wx_id, h.role, h.content, h.created_at, h.metadata, "
            "COALESCE(u.nickname, h.wx_id) AS display_name "
            "FROM chat_history h "
            "LEFT JOIN user_profiles u ON h.wx_id = u.wx_id "
            f"{where_sql} "
            "ORDER BY h.wx_id ASC, h.id ASC"
            f"{limit_sql}"
        )

        db = await self._get_db()
        async with db.execute(query_sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()

        messages: List[Dict[str, Any]] = []
        for row in rows:
            messages.append({
                "id": int(row["id"] or 0),
                "wx_id": str(row["wx_id"] or ""),
                "role": str(row["role"] or ""),
                "content": str(row["content"] or ""),
                "created_at": int(row["created_at"] or 0),
                "display_name": str(row["display_name"] or ""),
                "metadata": self._deserialize_metadata(row["metadata"]),
            })
        return messages

    # ==================== 用户画像方法 ====================

    async def get_user_profile(self, wx_id: str) -> UserProfile:
        """获取用户画像，如果不存在则返回默认画像"""
        wx_id = str(wx_id).strip()
        if not wx_id:
            return UserProfile(wx_id=wx_id, **DEFAULT_USER_PROFILE)
            
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM user_profiles WHERE wx_id = ?",
            (wx_id,),
        ) as cursor:
            row = await cursor.fetchone()
            
        if row is None:
            return UserProfile(wx_id=wx_id, **DEFAULT_USER_PROFILE)
            
        data = dict(DEFAULT_USER_PROFILE)
        data['wx_id'] = wx_id
        
        data["nickname"] = row["nickname"] or ""
        data["relationship"] = row["relationship"] or "unknown"
        data["personality"] = row["personality"] or ""
        data["last_emotion"] = row["last_emotion"] or "neutral"
        data["profile_summary"] = row["profile_summary"] or ""
        data["contact_prompt"] = row["contact_prompt"] or ""
        data["contact_prompt_updated_at"] = int(row["contact_prompt_updated_at"] or 0)
        data["contact_prompt_source"] = row["contact_prompt_source"] or ""
        data["contact_prompt_last_message_count"] = int(row["contact_prompt_last_message_count"] or 0)
        data["message_count"] = row["message_count"] or 0
        data["updated_at"] = row["updated_at"] or 0

        # 解析 JSON 字段
        try:
            data["preferences"] = json.loads(row["preferences"] or "{}")
        except (json.JSONDecodeError, TypeError):
            data["preferences"] = {}
        try:
            data["context_facts"] = json.loads(row["context_facts"] or "[]")
        except (json.JSONDecodeError, TypeError):
            data["context_facts"] = []
        try:
            data["emotion_history"] = json.loads(row["emotion_history"] or "[]")
        except (json.JSONDecodeError, TypeError):
            data["emotion_history"] = []
        if not data["profile_summary"]:
            data["profile_summary"] = self._build_profile_summary(data)

        return UserProfile(**data)

    async def _ensure_user_profile(self, wx_id: str) -> None:
        """确保用户画像存在，不存在则创建"""
        db = await self._get_db()
        await db.execute(
            "INSERT OR IGNORE INTO user_profiles (wx_id, updated_at) VALUES (?, ?)",
            (wx_id, int(time.time())),
        )
        await db.commit()

    async def update_user_profile(self, wx_id: str, **fields: Any) -> None:
        """
        更新用户画像的指定字段。
        """
        wx_id = str(wx_id).strip()
        if not wx_id:
            return
        await self._ensure_user_profile(wx_id)

        current_profile = await self.get_user_profile(wx_id)
        next_profile = current_profile.model_dump(mode="json")

        for key, value in fields.items():
            if key not in self._ALLOWED_PROFILE_FIELDS:
                continue
            next_profile[key] = value

        changed_fields = {
            key: next_profile[key]
            for key in self._ALLOWED_PROFILE_FIELDS
            if key in fields
        }
        if not changed_fields:
            return

        next_profile["profile_summary"] = self._build_profile_summary(next_profile)
        changed_fields["profile_summary"] = next_profile["profile_summary"]

        updates: List[str] = []
        values: List[Any] = []
        for key, value in changed_fields.items():
            if key in _JSON_FIELDS:
                value = json.dumps(value, ensure_ascii=False)
            updates.append(f"{key} = ?")
            values.append(value)

        updates.append("updated_at = ?")
        values.append(int(time.time()))
        values.append(wx_id)
        
        sql = f"UPDATE user_profiles SET {', '.join(updates)} WHERE wx_id = ?"
        db = await self._get_db()
        await db.execute(sql, values)
        await db.commit()

    async def get_profile_prompt_snapshot(self, wx_id: str) -> Dict[str, Any]:
        profile = await self.get_user_profile(wx_id)
        return {
            "wx_id": profile.wx_id,
            "nickname": profile.nickname,
            "relationship": profile.relationship,
            "message_count": profile.message_count,
            "last_emotion": profile.last_emotion,
            "profile_summary": profile.profile_summary or self._build_profile_summary(
                profile.model_dump(mode="json")
            ),
            "contact_prompt": profile.contact_prompt or "",
            "contact_prompt_updated_at": int(profile.contact_prompt_updated_at or 0),
            "contact_prompt_source": profile.contact_prompt_source or "",
            "contact_prompt_last_message_count": int(profile.contact_prompt_last_message_count or 0),
        }

    @staticmethod
    def _normalize_chat_id_candidates(
        primary_wx_id: str,
        aliases: Optional[Iterable[str]] = None,
    ) -> tuple[str, List[str]]:
        primary = str(primary_wx_id or "").strip()
        normalized_aliases: List[str] = []
        for raw in list(aliases or []):
            alias = str(raw or "").strip()
            if not alias or alias == primary or alias in normalized_aliases:
                continue
            normalized_aliases.append(alias)
        return primary, normalized_aliases

    async def _get_user_profile_row(self, wx_id: str) -> Optional[Dict[str, Any]]:
        wx_id = str(wx_id).strip()
        if not wx_id:
            return None
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM user_profiles WHERE wx_id = ?",
            (wx_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def reconcile_chat_aliases(
        self,
        primary_wx_id: str,
        aliases: Optional[Iterable[str]] = None,
        *,
        nickname: str = "",
    ) -> str:
        primary, normalized_aliases = self._normalize_chat_id_candidates(
            primary_wx_id,
            aliases,
        )
        if not primary:
            return normalized_aliases[0] if normalized_aliases else ""
        if not normalized_aliases:
            return primary

        db = await self._get_db()
        for alias in normalized_aliases:
            await db.execute(
                "UPDATE chat_history SET wx_id = ? WHERE wx_id = ?",
                (primary, alias),
            )
            await db.execute(
                "UPDATE pending_replies SET chat_id = ? WHERE chat_id = ?",
                (primary, alias),
            )
            async with db.execute(
                "SELECT task_type, payload, updated_at FROM background_backlog WHERE chat_id = ?",
                (alias,),
            ) as cursor:
                backlog_rows = await cursor.fetchall()
            for row in backlog_rows:
                await db.execute(
                    """
                    INSERT INTO background_backlog (chat_id, task_type, payload, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id, task_type) DO UPDATE SET
                        payload = CASE
                            WHEN excluded.updated_at >= background_backlog.updated_at
                            THEN excluded.payload
                            ELSE background_backlog.payload
                        END,
                        updated_at = CASE
                            WHEN excluded.updated_at >= background_backlog.updated_at
                            THEN excluded.updated_at
                            ELSE background_backlog.updated_at
                        END
                    """,
                    (
                        primary,
                        str(row["task_type"] or "").strip(),
                        str(row["payload"] or "{}"),
                        int(row["updated_at"] or 0),
                    ),
                )
            await db.execute(
                "DELETE FROM background_backlog WHERE chat_id = ?",
                (alias,),
            )
        await db.commit()

        preferred_nickname = str(nickname or "").strip()
        primary_row = await self._get_user_profile_row(primary)
        for alias in normalized_aliases:
            alias_row = await self._get_user_profile_row(alias)
            if not alias_row:
                continue
            if not primary_row:
                await db.execute(
                    "UPDATE user_profiles SET wx_id = ? WHERE wx_id = ?",
                    (primary, alias),
                )
                await db.commit()
                primary_row = await self._get_user_profile_row(primary)
                continue

            primary_profile = await self.get_user_profile(primary)
            alias_profile = await self.get_user_profile(alias)
            primary_prompt_at = int(primary_profile.contact_prompt_updated_at or 0)
            alias_prompt_at = int(alias_profile.contact_prompt_updated_at or 0)
            newer_prompt_profile = alias_profile if alias_prompt_at > primary_prompt_at else primary_profile
            merged_facts = list(
                dict.fromkeys(
                    list(alias_profile.context_facts or [])
                    + list(primary_profile.context_facts or [])
                )
            )
            merged_history = list(alias_profile.emotion_history or []) + list(primary_profile.emotion_history or [])
            merged_fields = {
                "nickname": preferred_nickname or str(primary_profile.nickname or alias_profile.nickname or "").strip(),
                "relationship": (
                    str(primary_profile.relationship or "").strip()
                    if str(primary_profile.relationship or "").strip() not in {"", "unknown"}
                    else str(alias_profile.relationship or primary_profile.relationship or "unknown").strip()
                ),
                "personality": str(primary_profile.personality or alias_profile.personality or "").strip(),
                "preferences": dict(primary_profile.preferences or alias_profile.preferences or {}),
                "context_facts": merged_facts,
                "last_emotion": (
                    str(primary_profile.last_emotion or "").strip()
                    if str(primary_profile.last_emotion or "").strip() not in {"", "neutral"}
                    else str(alias_profile.last_emotion or primary_profile.last_emotion or "neutral").strip()
                ),
                "emotion_history": merged_history[-10:],
                "profile_summary": str(primary_profile.profile_summary or alias_profile.profile_summary or "").strip(),
                "contact_prompt": str(newer_prompt_profile.contact_prompt or "").strip(),
                "contact_prompt_updated_at": int(newer_prompt_profile.contact_prompt_updated_at or 0),
                "contact_prompt_source": str(newer_prompt_profile.contact_prompt_source or "").strip(),
                "contact_prompt_last_message_count": max(
                    int(primary_profile.contact_prompt_last_message_count or 0),
                    int(alias_profile.contact_prompt_last_message_count or 0),
                ),
                "message_count": int(primary_profile.message_count or 0) + int(alias_profile.message_count or 0),
            }
            await self.update_user_profile(primary, **merged_fields)
            await db.execute("DELETE FROM user_profiles WHERE wx_id = ?", (alias,))
            await db.commit()
            primary_row = await self._get_user_profile_row(primary)

        if preferred_nickname:
            primary_row = await self._get_user_profile_row(primary)
            if primary_row and str(primary_row.get("nickname") or "").strip() != preferred_nickname:
                await self.update_user_profile(primary, nickname=preferred_nickname)
        return primary

    async def get_contact_profile(self, wx_id: str) -> Dict[str, Any]:
        profile = await self.get_user_profile(wx_id)
        return {
            "chat_id": profile.wx_id,
            "nickname": profile.nickname,
            "relationship": profile.relationship,
            "message_count": int(profile.message_count or 0),
            "last_emotion": profile.last_emotion,
            "profile_summary": profile.profile_summary or self._build_profile_summary(
                profile.model_dump(mode="json")
            ),
            "context_facts": list(profile.context_facts or []),
            "contact_prompt": profile.contact_prompt or "",
            "contact_prompt_updated_at": int(profile.contact_prompt_updated_at or 0),
            "contact_prompt_source": profile.contact_prompt_source or "",
            "contact_prompt_last_message_count": int(profile.contact_prompt_last_message_count or 0),
            "updated_at": int(profile.updated_at or 0),
        }

    async def save_contact_prompt(
        self,
        wx_id: str,
        contact_prompt: str,
        *,
        source: str = "user_edit",
        last_message_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        profile = await self.get_user_profile(wx_id)
        next_message_count = (
            int(last_message_count)
            if last_message_count is not None
            else int(profile.message_count or 0)
        )
        await self.update_user_profile(
            wx_id,
            contact_prompt=str(contact_prompt or "").strip(),
            contact_prompt_source=str(source or "").strip(),
            contact_prompt_updated_at=int(time.time()),
            contact_prompt_last_message_count=next_message_count,
        )
        return await self.get_contact_profile(wx_id)

    async def add_context_fact(self, wx_id: str, fact: str, max_facts: int = 20) -> None:
        """添加一条事实信息到用户画像"""
        wx_id = str(wx_id).strip()
        fact = str(fact).strip()
        if not wx_id or not fact:
            return
            
        profile = await self.get_user_profile(wx_id)
        facts = list(profile.context_facts) # Use attribute access
        
        # 避免重复
        if fact not in facts:
            facts.append(fact)
            # 限制数量
            if len(facts) > max_facts:
                facts = facts[-max_facts:]
            await self.update_user_profile(wx_id, context_facts=facts)

    async def update_emotion(
        self, wx_id: str, emotion: str, max_history: int = 10
    ) -> None:
        """更新用户的当前情绪，并记录到历史"""
        wx_id = str(wx_id).strip()
        emotion = str(emotion).strip().lower()
        if not wx_id or not emotion:
            return
            
        profile = await self.get_user_profile(wx_id)
        history = list(profile.emotion_history) # Use attribute access
        
        history.append({"emotion": emotion, "timestamp": int(time.time())})
        if len(history) > max_history:
            history = history[-max_history:]
        await self.update_user_profile(
            wx_id, last_emotion=emotion, emotion_history=history
        )

    async def increment_message_count(self, wx_id: str) -> int:
        """增加用户消息计数并返回新值"""
        wx_id = str(wx_id).strip()
        if not wx_id:
            return 0
        profile = await self.get_user_profile(wx_id)
        next_count = int(profile.message_count or 0) + 1
        await self.update_user_profile(wx_id, message_count=next_count)
        return next_count

    async def close(self) -> None:
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
