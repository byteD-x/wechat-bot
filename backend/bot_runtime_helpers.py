from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set

from .types import MessageEvent
from .utils.common import as_float, as_int
from .utils.config import get_model_alias
from .utils.message import (
    build_reply_suffix,
    refine_reply_text,
    sanitize_reply_text,
    split_reply_chunks,
)

FILEHELPER_CHAT_NAMES: Set[str] = {"filehelper", "文件传输助手"}
RECENT_SELF_MESSAGE_ECHO_TTL_SEC = 8.0
RECENT_SELF_MESSAGE_ECHO_MAX_ITEMS = 20


def normalize_chat_name(chat_name: str) -> str:
    return str(chat_name or "").strip().lower()


def is_filehelper_chat(chat_name: str) -> bool:
    return normalize_chat_name(chat_name) in FILEHELPER_CHAT_NAMES


def prune_recent_outgoing_messages(
    recent_outgoing_messages: Dict[str, List[Dict[str, Any]]],
    *,
    now: Optional[float] = None,
) -> None:
    deadline = float(now if now is not None else time.time()) - RECENT_SELF_MESSAGE_ECHO_TTL_SEC
    stale_keys: List[str] = []
    for chat_key, entries in recent_outgoing_messages.items():
        kept = [
            item for item in entries
            if float(item.get("ts", 0.0) or 0.0) >= deadline
        ]
        if kept:
            recent_outgoing_messages[chat_key] = kept[-RECENT_SELF_MESSAGE_ECHO_MAX_ITEMS:]
        else:
            stale_keys.append(chat_key)
    for chat_key in stale_keys:
        recent_outgoing_messages.pop(chat_key, None)


def remember_recent_outgoing_message(
    recent_outgoing_messages: Dict[str, List[Dict[str, Any]]],
    chat_name: str,
    text: str,
    *,
    chunk_size: Optional[int] = None,
) -> None:
    if not is_filehelper_chat(chat_name):
        return

    content = str(text or "").strip()
    if not content:
        return

    pieces = [content]
    if chunk_size and chunk_size > 0:
        try:
            pieces = [
                chunk.strip()
                for chunk in split_reply_chunks(content, int(chunk_size))
                if str(chunk).strip()
            ] or [content]
        except Exception:
            pieces = [content]

    now = time.time()
    prune_recent_outgoing_messages(recent_outgoing_messages, now=now)
    chat_key = normalize_chat_name(chat_name)
    entries = recent_outgoing_messages.setdefault(chat_key, [])
    for piece in pieces:
        entries.append({"content": piece, "ts": now})
    recent_outgoing_messages[chat_key] = entries[-RECENT_SELF_MESSAGE_ECHO_MAX_ITEMS:]


def is_recent_outgoing_echo(
    recent_outgoing_messages: Dict[str, List[Dict[str, Any]]],
    event: MessageEvent,
) -> bool:
    if not event.is_self or not is_filehelper_chat(event.chat_name):
        return False

    content = str(event.content or "").strip()
    if not content:
        return False

    prune_recent_outgoing_messages(recent_outgoing_messages)
    for item in reversed(
        recent_outgoing_messages.get(normalize_chat_name(event.chat_name), [])
    ):
        if str(item.get("content") or "").strip() == content:
            return True
    return False


def prepare_event_for_processing(
    event: MessageEvent,
    bot_cfg: Dict[str, Any],
    recent_outgoing_messages: Dict[str, List[Dict[str, Any]]],
) -> str:
    if not event.is_self:
        return "normal"
    if not is_filehelper_chat(event.chat_name):
        return "self_filtered"
    if not bool(bot_cfg.get("allow_filehelper_self_message", True)):
        return "self_filtered"
    if is_recent_outgoing_echo(recent_outgoing_messages, event):
        return "skip_recent_outgoing_echo"

    event.is_self = False
    return "accepted_self_filehelper"


def sanitize_reply_segment(bot_cfg: Dict[str, Any], reply_text: str) -> str:
    emoji_policy = str(bot_cfg.get("emoji_policy", "wechat"))
    replacements = bot_cfg.get("emoji_replacements")
    refined_reply = refine_reply_text(reply_text)
    return sanitize_reply_text(refined_reply, emoji_policy, replacements)


def build_reply_body_text(bot_cfg: Dict[str, Any], reply_text: str) -> str:
    sanitized = sanitize_reply_segment(bot_cfg, reply_text)
    if str(sanitized or "").strip():
        return str(sanitized).strip()

    fallback_raw = str(reply_text or "").strip()
    if not fallback_raw:
        return ""

    emoji_policy = str(bot_cfg.get("emoji_policy", "wechat"))
    replacements = bot_cfg.get("emoji_replacements")
    fallback_sanitized = sanitize_reply_text(fallback_raw, emoji_policy, replacements)
    return str(fallback_sanitized or "").strip()


def ensure_send_succeeded(result: Any, *, context: str) -> None:
    ok, err_msg = result
    if ok:
        return
    detail = str(err_msg or "").strip() or "unknown error"
    raise RuntimeError(f"{context}发送失败: {detail}")


def build_reply_suffix_text(bot_cfg: Dict[str, Any], ai_client: Any) -> str:
    reply_suffix = str(bot_cfg.get("reply_suffix") or "").strip()
    if not reply_suffix:
        return ""
    model_name = getattr(ai_client, "model", "") if ai_client else ""
    alias = get_model_alias(ai_client)
    return build_reply_suffix(reply_suffix, model_name or "", alias)


def build_final_reply_text(bot_cfg: Dict[str, Any], ai_client: Any, reply_text: str) -> str:
    sanitized = build_reply_body_text(bot_cfg, reply_text)
    if not sanitized:
        return ""
    suffix = build_reply_suffix_text(bot_cfg, ai_client)
    return f"{sanitized}{suffix}" if suffix else sanitized


def get_natural_split_config(bot_cfg: Dict[str, Any]) -> Dict[str, float]:
    delay_range = bot_cfg.get("natural_split_delay_sec")
    delay_min = as_float(
        delay_range[0] if isinstance(delay_range, (list, tuple)) and len(delay_range) > 0 else 0.3,
        0.3,
        min_value=0.0,
    )
    delay_max = as_float(
        delay_range[1] if isinstance(delay_range, (list, tuple)) and len(delay_range) > 1 else delay_min,
        delay_min,
        min_value=0.0,
    )
    if delay_max < delay_min:
        delay_min, delay_max = delay_max, delay_min
    return {
        "min_chars": as_int(bot_cfg.get("natural_split_min_chars", 30), 30, min_value=1),
        "max_chars": as_int(bot_cfg.get("natural_split_max_chars", 120), 120, min_value=1),
        "max_segments": as_int(bot_cfg.get("natural_split_max_segments", 3), 3, min_value=1),
        "delay_min": delay_min,
        "delay_max": delay_max,
    }


__all__ = [
    "build_final_reply_text",
    "build_reply_body_text",
    "build_reply_suffix_text",
    "ensure_send_succeeded",
    "get_natural_split_config",
    "is_filehelper_chat",
    "is_recent_outgoing_echo",
    "normalize_chat_name",
    "prepare_event_for_processing",
    "prune_recent_outgoing_messages",
    "remember_recent_outgoing_message",
    "sanitize_reply_segment",
]
