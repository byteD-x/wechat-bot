from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, Optional


class ReplyQualityTracker:
    """回复质量持久化追踪器。"""

    def __init__(self, db_path: str = "data/reply_quality_history.db") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if hasattr(self, "_conn"):
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reply_quality_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    delayed INTEGER DEFAULT 0,
                    retrieval_augmented INTEGER DEFAULT 0,
                    retrieval_hit_count INTEGER DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reply_quality_timestamp
                ON reply_quality_log(timestamp)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reply_feedback_log (
                    message_id INTEGER PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    feedback TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reply_feedback_timestamp
                ON reply_feedback_log(timestamp)
                """
            )
            self._conn.commit()

    def log_event(
        self,
        *,
        outcome: str,
        delayed: bool = False,
        retrieval_augmented: bool = False,
        retrieval_hit_count: int = 0,
        timestamp: Optional[float] = None,
    ) -> None:
        normalized = str(outcome or "").strip().lower() or "unknown"
        now = float(timestamp or time.time())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO reply_quality_log (
                    timestamp,
                    outcome,
                    delayed,
                    retrieval_augmented,
                    retrieval_hit_count
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    now,
                    normalized,
                    1 if delayed else 0,
                    1 if retrieval_augmented else 0,
                    max(0, int(retrieval_hit_count or 0)),
                ),
            )
            self._conn.commit()

    def get_summary(self, *, since_ts: float) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN outcome = 'empty' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(delayed), 0),
                    COALESCE(SUM(retrieval_augmented), 0),
                    COALESCE(SUM(retrieval_hit_count), 0),
                    MAX(timestamp)
                FROM reply_quality_log
                WHERE timestamp >= ?
                """,
                (float(since_ts),),
            ).fetchone()
            feedback_row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN feedback = 'helpful' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN feedback = 'unhelpful' THEN 1 ELSE 0 END), 0)
                FROM reply_feedback_log
                WHERE timestamp >= ?
                """,
                (float(since_ts),),
            ).fetchone()

        attempted = int(row[0] or 0)
        successful = int(row[1] or 0)
        empty = int(row[2] or 0)
        failed = int(row[3] or 0)
        delayed = int(row[4] or 0)
        retrieval_augmented = int(row[5] or 0)
        retrieval_hit_count = int(row[6] or 0)
        last_reply_at = float(row[7]) if row[7] is not None else None
        success_rate = round((successful / attempted) * 100, 1) if attempted > 0 else 0.0
        helpful_count = int(feedback_row[0] or 0)
        unhelpful_count = int(feedback_row[1] or 0)

        return {
            "attempted": attempted,
            "successful": successful,
            "empty": empty,
            "failed": failed,
            "delayed": delayed,
            "retrieval_augmented": retrieval_augmented,
            "retrieval_hit_count": retrieval_hit_count,
            "helpful_count": helpful_count,
            "unhelpful_count": unhelpful_count,
            "success_rate": success_rate,
            "last_reply_at": last_reply_at,
        }

    def log_feedback(
        self,
        *,
        message_id: int,
        feedback: str,
        timestamp: Optional[float] = None,
    ) -> None:
        try:
            message_id_val = int(message_id)
        except (TypeError, ValueError):
            return
        if message_id_val <= 0:
            return

        normalized = str(feedback or "").strip().lower()
        now = float(timestamp or time.time())
        with self._lock:
            if normalized not in {"helpful", "unhelpful"}:
                self._conn.execute(
                    "DELETE FROM reply_feedback_log WHERE message_id = ?",
                    (message_id_val,),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO reply_feedback_log (message_id, timestamp, feedback)
                    VALUES (?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        timestamp = excluded.timestamp,
                        feedback = excluded.feedback
                    """,
                    (message_id_val, now, normalized),
                )
            self._conn.commit()

    def get_recent_summaries(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        return {
            "24h": self.get_summary(since_ts=now - 24 * 3600),
            "7d": self.get_summary(since_ts=now - 7 * 24 * 3600),
        }


_reply_quality_tracker: Optional[ReplyQualityTracker] = None


def get_reply_quality_tracker(db_path: str = "data/reply_quality_history.db") -> ReplyQualityTracker:
    global _reply_quality_tracker
    if _reply_quality_tracker is None:
        _reply_quality_tracker = ReplyQualityTracker(db_path)
    return _reply_quality_tracker
