"""
消息转换模块 - 负责将微信原始消息转换为统一的 MessageEvent 对象。
"""

import logging
from typing import Any, List, Optional

from ..types import MessageEvent
from ..utils.common import iter_items
from ..utils.message import (
    is_text_message,
    is_voice_message,
    is_image_message,
    split_group_message,
    is_at_me,
    strip_at_text,
    VOICE_PLACEHOLDER,
)

__all__ = [
    "normalize_new_messages",
    "normalize_message_item",
    "normalize_message_item_from_list",
]


def normalize_new_messages(raw: Any, self_name: str) -> List[MessageEvent]:
    """
    标准化新消息列表。
    
    支持处理 wxauto 返回的不同格式的消息结构。
    """
    events: List[MessageEvent] = []
    if not raw:
        return events

    # 微信自动化库当前返回格式：{"chat_name": "...", "chat_type": "...", "msg": [...]}
    if isinstance(raw, dict) and "chat_name" in raw and "msg" in raw:
        chat_name = str(raw.get("chat_name", "")).strip()
        chat_type = str(raw.get("chat_type", "")).strip()
        for item in iter_items(raw.get("msg", [])):
            event = normalize_message_item(chat_name, item, self_name, chat_type)
            if event:
                events.append(event)
        return events

    # 兼容旧格式：{会话名: [消息1, 消息2, ...]}
    if isinstance(raw, dict):
        for chat_name, items in raw.items():
            chat_name = str(chat_name).strip()
            for item in iter_items(items):
                event = normalize_message_item(chat_name, item, self_name, None)
                if event:
                    events.append(event)
        return events

    # 部分版本会返回消息字典列表。
    if isinstance(raw, list):
        for item in raw:
            event = normalize_message_item_from_list(item, self_name)
            if event:
                events.append(event)
        return events

    logging.debug("未知消息结构：%s", type(raw))
    return events


def normalize_message_item(
    chat_name: str, item: Any, self_name: str, chat_type: Optional[str]
) -> Optional[MessageEvent]:
    """
    将单条原始消息标准化为 MessageEvent。
    
    处理逻辑：
    1. 提取内容、发送者、消息类型
    2. 过滤系统消息
    3. 解析群聊发送者
    4. 识别是否 @ 机器人
    """
    chat_type_norm = str(chat_type).lower() if chat_type else None
    is_group = chat_type_norm == "group"
    is_self = False
    chat_name = str(chat_name).strip()

    timestamp = None
    if hasattr(item, "content") and hasattr(item, "type"):
        content = getattr(item, "content", "") or ""
        sender = (
            getattr(item, "sender", None)
            or getattr(item, "sender_remark", None)
            or chat_name
        )
        msg_type = getattr(item, "type", None)
        attr = getattr(item, "attr", None)
        timestamp = (
            getattr(item, "timestamp", None)
            or getattr(item, "time", None)
            or getattr(item, "create_time", None)
            or getattr(item, "createTime", None)
        )
        if (not content) and hasattr(item, "info"):
            info = getattr(item, "info", None)
            if isinstance(info, dict):
                content = info.get("content", content) or content
                msg_type = info.get("type", msg_type)
                attr = info.get("attr", attr)
                if timestamp is None:
                    timestamp = (
                        info.get("timestamp")
                        or info.get("time")
                        or info.get("create_time")
                        or info.get("createTime")
                    )
        is_self = attr == "self"
        if attr in ("system", "time", "tickle"):
            return None
    elif isinstance(item, dict):
        content = item.get("msg") or item.get("content") or item.get("text") or ""
        sender = item.get("sender") or item.get("from") or item.get("nickname") or chat_name
        msg_type = item.get("type") or item.get("msg_type") or "text"
        is_group = is_group or bool(item.get("is_group") or item.get("group"))
        is_self = bool(item.get("is_self"))
        timestamp = (
            item.get("timestamp")
            or item.get("time")
            or item.get("ts")
            or item.get("create_time")
            or item.get("createTime")
        )
    elif isinstance(item, str):
        content = item
        sender = chat_name
        msg_type = "text"
        is_group = is_group or False
    else:
        return None

    content = content.strip()
    if is_voice_message(msg_type):
        if not content:
            content = VOICE_PLACEHOLDER
    elif is_image_message(msg_type):
        content = "[图片]"
    elif not is_text_message(msg_type, content):
        return None

    if is_group and (not sender or sender == chat_name):
        sender_from_text, clean = split_group_message(content)
        if sender_from_text:
            sender = sender_from_text
            content = clean

    if timestamp is not None:
        try:
            timestamp = float(timestamp)
        except Exception:
            timestamp = None

    at_me = is_group and is_at_me(content, self_name)
    if is_group:
        content = strip_at_text(content, self_name)

    return MessageEvent(
        chat_name=chat_name,
        sender=sender,
        content=content,
        is_group=is_group,
        is_at_me=at_me,
        msg_type=str(msg_type),
        is_self=is_self,
        chat_type=chat_type_norm,
        timestamp=timestamp,
        raw_item=item,
    )


def normalize_message_item_from_list(item: Any, self_name: str) -> Optional[MessageEvent]:
    """列表结构的兜底解析。"""
    if not isinstance(item, dict):
        return None

    chat_name = (
        item.get("chat")
        or item.get("who")
        or item.get("group")
        or item.get("from")
        or item.get("sender")
        or ""
    )
    if not chat_name:
        return None

    return normalize_message_item(chat_name, item, self_name, item.get("chat_type"))
