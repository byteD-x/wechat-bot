"""
类型定义模块 - 定义项目中通用的数据类和类型别名。
"""

from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "MessageEvent",
    "ReconnectPolicy",
]


@dataclass(slots=True)
class MessageEvent:
    """
    统一的消息事件对象。
    
    Attributes:
        chat_name (str): 会话名称（群名或好友昵称）
        sender (str): 发送者昵称
        content (str): 消息内容
        is_group (bool): 是否为群聊
        is_at_me (bool): 是否 @ 了机器人（仅群聊有效）
        msg_type (str): 消息类型（text/voice/image 等）
        is_self (bool): 是否为自己（机器人）发送
        chat_type (str | None): 会话类型（friend/group/official 等）
        raw_item (Any): 原始消息对象（传输层返回的）
    """
    chat_name: str
    sender: str
    content: str
    is_group: bool
    is_at_me: bool
    msg_type: str
    is_self: bool
    chat_type: Optional[str]
    timestamp: Optional[float] = None
    raw_item: Optional[Any] = None


@dataclass(slots=True)
class ReconnectPolicy:
    """
    重连策略配置。
    
    Attributes:
        max_retries (int): 最大重试次数
        base_delay_sec (float): 基础延迟时间（秒）
        max_delay_sec (float): 最大延迟时间（秒）
    """
    max_retries: int
    base_delay_sec: float
    max_delay_sec: float
