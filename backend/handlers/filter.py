"""
消息过滤器模块 - 负责判断是否回复消息。
"""

from typing import Any, Dict, Tuple



from ..types import MessageEvent
from ..utils.common import iter_items

__all__ = ["should_reply_with_reason"]



def should_reply_with_reason(
    event: MessageEvent,
    config: Dict[str, Any],
    ignore_names_set: set = None,
    ignore_keywords_list: list = None,
) -> Tuple[bool, str]:
    """
    判断是否应该回复该消息。
    
    规则：
    1. 忽略空消息、自己发送的消息
    2. 忽略公众号/服务号通知（可配置）
    3. 忽略黑名单（名称/关键词）
    4. 群聊仅在被 @ 时回复（可配置）
    5. 群聊白名单过滤（可配置）
    """
    bot_cfg = config.get("bot", {})
    self_name = bot_cfg.get("self_name", "")

    if not event.content.strip():
        return False, "empty_content"
    if event.is_self:
        return False, "from_self"
    if self_name and event.sender == self_name:
        return False, "sender_is_self_name"

    if bot_cfg.get("ignore_official", True) and event.chat_type == "official":
        return False, "official_account"
    if bot_cfg.get("ignore_service", True) and event.chat_type == "service":
        return False, "service_account"

    # 优化：使用预处理的集合/列表
    if ignore_names_set is None or ignore_keywords_list is None:
        ignore_names = [
            str(name).strip()
            for name in iter_items(bot_cfg.get("ignore_names", []))
            if str(name).strip()
        ]
        ignore_keywords = [
            str(keyword).strip()
            for keyword in iter_items(bot_cfg.get("ignore_keywords", []))
            if str(keyword).strip()
        ]
        ignore_names_set = {name.lower() for name in ignore_names}
        ignore_keywords_list = ignore_keywords
    
    if ignore_names_set or ignore_keywords_list:
        chat_name_norm = event.chat_name.strip().lower()
        if chat_name_norm in ignore_names_set:
            return False, "ignored_chat_name"
        for keyword in ignore_keywords_list:
            if keyword in event.chat_name:
                return False, f"ignored_chat_keyword:{keyword}"

    if bot_cfg.get("group_reply_only_when_at", False) and event.is_group:
        if not event.is_at_me:
            return False, "group_not_at_me"

    if bot_cfg.get("whitelist_enabled", False) and event.is_group:
        whitelist = set(bot_cfg.get("whitelist", []))
        if event.chat_name not in whitelist:
            return False, "group_not_in_whitelist"

    return True, "ok"
