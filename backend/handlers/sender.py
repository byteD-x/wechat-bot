"""
消息发送模块 - 负责消息发送、分片及错误处理。
"""

import asyncio
import logging
import time
import random
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING
from ..utils.common import as_float
from ..utils.message import split_reply_chunks

if TYPE_CHECKING:
    from wxauto import WeChat

__all__ = [
    "parse_send_result",
    "send_message",
    "send_quote_message",
    "send_reply_chunks",
]


def parse_send_result(result: Any) -> Tuple[bool, Optional[str]]:
    """解析微信发送接口的返回结果。"""
    if hasattr(result, "is_success"):
        success = getattr(result, "is_success")
        message = getattr(result, "message", None) or getattr(result, "error", None)
        return bool(success), message
    if isinstance(result, dict):
        if "status" in result:
            status = str(result.get("status") or "")
            if status != "成功":
                return False, result.get("message") or result.get("error")
            return True, result.get("message")
        if result.get("success") is False:
            return False, result.get("message") or result.get("error")
        if "code" in result and result.get("code") not in (0, "0", None):
            return False, result.get("message") or result.get("error")
        return True, result.get("message")
    if result:
        return True, None
    return False, "SendMsg 返回假值 (falsy)"


def send_message(
    wx: "WeChat", chat_name: str, text: str, bot_cfg: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    发送文本消息，包含重试和错误处理逻辑。
    """
    # 简单的重试机制
    retry_count = 2
    last_error = None
    
    for attempt in range(retry_count):
        result = wx.SendMsg(
            text,
            chat_name,
            exact=bool(bot_cfg.get("send_exact_match", False)),
        )
        ok, err_msg = parse_send_result(result)
        
        if ok:
            return True, err_msg
            
        last_error = err_msg
        if attempt < retry_count - 1:
            logging.warning("发送消息失败，尝试重试 (%d/%d): %s", attempt + 1, retry_count, err_msg)
            time.sleep(0.5)
            
    # 重试失败后，尝试回退到当前窗口
    if bot_cfg.get("send_fallback_current_chat", True):
        logging.warning(
            "发送失败，尝试当前聊天窗口重试 | 会话=%s | 错误=%s",
            chat_name, last_error
        )
        result = wx.SendMsg(text)
        ok, err_msg = parse_send_result(result)
        return ok, err_msg
        
    return False, last_error


def send_quote_message(
    quote_item: Any, text: str, timeout_sec: float
) -> Tuple[bool, Optional[str]]:
    """发送引用消息（回复特定消息）。"""
    if quote_item is None:
        return False, "引用对象为空"
    quote_func = getattr(quote_item, "quote", None)
    if not callable(quote_func):
        return False, "对象不支持引用 (quote 方法)"
    
    # 增加重试机制，提高引用成功率
    for attempt in range(2):
        try:
            result = quote_func(text, timeout=timeout_sec)
            ok, err_msg = parse_send_result(result)
            if ok:
                return True, None
            # 首次失败，重试
            if attempt == 0:
                logging.warning("引用发送失败，重试中：%s", err_msg)
                time.sleep(0.3)
        except Exception as exc:
            if attempt == 0:
                logging.warning("引用发送异常，重试中：%s", exc)
                time.sleep(0.3)
            else:
                return False, str(exc)
    return False, "quote retry exhausted"


async def send_reply_chunks(
    wx: "WeChat",
    chat_name: str,
    text: str,
    bot_cfg: Dict[str, Any],
    chunk_size: int,
    chunk_delay_sec: float,
    min_reply_interval: float,
    last_reply_ts: Dict[str, float],
    wx_lock: asyncio.Lock,
    quote_item: Optional[Any] = None,
    quote_timeout_sec: float = 3.0,
    quote_fallback_text: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    分块发送长回复，支持模拟打字延迟和引用回复。
    """
    chunks = split_reply_chunks(text, chunk_size)
    quote_used = False
    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        async with wx_lock:
            elapsed = time.time() - last_reply_ts.get("ts", 0.0)
            if elapsed < min_reply_interval:
                await asyncio.sleep(min_reply_interval - elapsed)
            if quote_item is not None and not quote_used:
                ok, err_msg = await asyncio.to_thread(
                    send_quote_message, quote_item, chunk, quote_timeout_sec
                )
                quote_used = True
                if not ok and quote_fallback_text is not None:
                    fallback_chunk = (
                        f"{quote_fallback_text}{chunk}"
                        if quote_fallback_text
                        else chunk
                    )
                    ok, err_msg = await asyncio.to_thread(
                        send_message, wx, chat_name, fallback_chunk, bot_cfg
                    )
                if not ok:
                    return False, err_msg
            else:
                ok, err_msg = await asyncio.to_thread(
                    send_message, wx, chat_name, chunk, bot_cfg
                )
                if not ok:
                    return False, err_msg
            last_reply_ts["ts"] = time.time()
        if idx < len(chunks) - 1 and chunk_delay_sec > 0:
            await asyncio.sleep(chunk_delay_sec)
    return True, None
