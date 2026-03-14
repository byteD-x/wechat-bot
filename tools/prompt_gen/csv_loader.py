"""
聊天记录 CSV 加载工具。

提供给 prompt 生成器和导出语料 RAG 共用，避免重复维护解析逻辑。
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EXCLUDED_CONTACTS = frozenset({
    "微信团队",
    "文件传输助手",
    "QQ离线消息",
    "QQ邮箱提醒",
    "朋友推荐消息",
    "语音记事本",
    "漂流瓶",
    "招商银行信用卡",
})

NON_TEXT_TYPES = frozenset({
    "语音", "图片", "视频", "文件", "表情包", "位置分享",
    "个人/公众号名片", "合并转发的聊天记录", "分享链接", "小程序",
    "系统消息", "未知类型",
})

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def extract_contact_name(dirname: str) -> str:
    """从 `联系人(wxid)` 目录名里提取联系人显示名。"""
    return str(dirname or "").split("(")[0].strip()


def parse_timestamp(raw_value: str) -> datetime:
    """兼容多种导出时间格式。"""
    text = str(raw_value or "").strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.now()


def load_chat_from_csv(csv_path: str, self_name: str = "知有") -> List[Dict[str, Any]]:
    """
    从 CSV 文件加载聊天记录。

    Args:
        csv_path: CSV 文件路径
        self_name: 用户自己的昵称，用于识别 assistant 侧消息

    Returns:
        聊天记录列表，每条包含 role, content, timestamp, msg_type, sender
    """
    records: List[Dict[str, Any]] = []
    encodings = ("utf-8", "utf-8-sig", "gbk", "gb2312")
    normalized_self_name = str(self_name or "").strip()

    for encoding in encodings:
        try:
            with open(csv_path, "r", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    sender = str(row.get("发送人", "") or "").strip()
                    records.append({
                        "role": "assistant" if sender == normalized_self_name else "user",
                        "content": row.get("内容", ""),
                        "timestamp": parse_timestamp(row.get("时间", "")),
                        "msg_type": row.get("类型", ""),
                        "sender": sender,
                    })
            break
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.error("Failed to load CSV %s with %s: %s", csv_path, encoding, exc)
            break

    return records


def is_text_record(record: Dict[str, Any]) -> bool:
    """判断记录是否为可用文本消息。"""
    if not isinstance(record, dict):
        return False
    msg_type = str(record.get("msg_type", "") or "").strip()
    if msg_type and msg_type in NON_TEXT_TYPES:
        return False
    return bool(str(record.get("content", "") or "").strip())
