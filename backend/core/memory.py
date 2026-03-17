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
            messages.append({
                "id": row["id"],
                "wx_id": row["wx_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["created_at"],
                "sender": row["nickname"] or row["wx_id"],
                "is_self": row["role"] == "assistant",
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
