"""Message sending helpers with retries and chunking."""

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ..utils.common import as_float
from ..utils.logging import build_stage_log_message
from ..utils.message import split_reply_chunks

if TYPE_CHECKING:
    from wxauto import WeChat

__all__ = [
    "parse_send_result",
    "send_message",
    "send_reply_chunks",
]


def parse_send_result(result: Any) -> Tuple[bool, Optional[str]]:
    """Normalize transport-specific send results into a success tuple."""
    if isinstance(result, bool):
        if result:
            return True, None
        return False, "SendMsg returned False"
    if isinstance(result, (int, float)):
        if int(result) == 0:
            return True, None
        return False, str(result)
    if hasattr(result, "is_success"):
        success = getattr(result, "is_success")
        message = getattr(result, "message", None) or getattr(result, "error", None)
        return bool(success), message
    if isinstance(result, dict):
        if "status" in result:
            status = str(result.get("status") or "").strip().lower()
            if status not in {"成功", "success", "ok", "0"}:
                return False, result.get("message") or result.get("error")
            return True, result.get("message")
        if result.get("success") is False:
            return False, result.get("message") or result.get("error")
        if "code" in result and result.get("code") not in (0, "0", None):
            return False, result.get("message") or result.get("error")
        return True, result.get("message")
    if result:
        return True, None
    return False, "SendMsg returned falsy result"


def send_message(
    wx: "WeChat", chat_name: str, text: str, bot_cfg: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """Send a plain text message with retry and current-chat fallback."""
    retry_count = 2
    last_error = None
    logging.info(
        build_stage_log_message(
            "SEND.CALL",
            target=chat_name,
            length=len(str(text or "")),
            exact=bool(bot_cfg.get("send_exact_match", False)),
        )
    )

    for attempt in range(retry_count):
        logging.info(
            build_stage_log_message(
                "SEND.ATTEMPT",
                target=chat_name,
                attempt=attempt + 1,
                total=retry_count,
            )
        )
        result = wx.SendMsg(
            text,
            chat_name,
            exact=bool(bot_cfg.get("send_exact_match", False)),
        )
        ok, err_msg = parse_send_result(result)

        if ok:
            logging.info(
                build_stage_log_message(
                    "SEND.SUCCESS",
                    target=chat_name,
                    attempt=attempt + 1,
                )
            )
            return True, err_msg

        last_error = err_msg
        if attempt < retry_count - 1:
            logging.warning(
                "发送消息失败，尝试重试 (%d/%d): %s",
                attempt + 1,
                retry_count,
                err_msg,
            )
            time.sleep(0.5)

    if bot_cfg.get("send_fallback_current_chat", True):
        logging.warning(
            "发送失败，尝试当前聊天窗口重试 | 会话=%s | 错误=%s",
            chat_name,
            last_error,
        )
        logging.warning(
            build_stage_log_message(
                "SEND.FALLBACK_CURRENT_CHAT",
                target=chat_name,
                error=last_error,
            )
        )
        result = wx.SendMsg(text)
        ok, err_msg = parse_send_result(result)
        if ok:
            logging.info(build_stage_log_message("SEND.FALLBACK_SUCCESS", target=chat_name))
        else:
            logging.error(
                build_stage_log_message(
                    "SEND.FALLBACK_FAILED",
                    target=chat_name,
                    error=err_msg,
                )
            )
        return ok, err_msg

    logging.error(
        build_stage_log_message(
            "SEND.FAILED",
            target=chat_name,
            error=last_error,
        )
    )
    return False, last_error

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
) -> Tuple[bool, Optional[str]]:
    """Send a reply in chunks."""
    chunks = split_reply_chunks(text, chunk_size)
    logging.info(
        build_stage_log_message(
            "SEND.CHUNKS_START",
            target=chat_name,
            chunks=len(chunks),
            chunk_size=chunk_size,
        )
    )
    random_delay = bot_cfg.get("random_delay_range_sec")
    random_delay_min = as_float(
        random_delay[0]
        if isinstance(random_delay, (list, tuple)) and len(random_delay) > 0
        else 0.0,
        0.0,
        min_value=0.0,
    )
    random_delay_max = as_float(
        random_delay[1]
        if isinstance(random_delay, (list, tuple)) and len(random_delay) > 1
        else random_delay_min,
        random_delay_min,
        min_value=0.0,
    )
    if random_delay_max < random_delay_min:
        random_delay_min, random_delay_max = random_delay_max, random_delay_min
    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        logging.info(
            build_stage_log_message(
                "SEND.CHUNK_ATTEMPT",
                target=chat_name,
                chunk_index=idx + 1,
                chunk_total=len(chunks),
                length=len(chunk),
            )
        )
        async with wx_lock:
            elapsed = time.time() - last_reply_ts.get("ts", 0.0)
            if elapsed < min_reply_interval:
                await asyncio.sleep(min_reply_interval - elapsed)
            if random_delay_max > 0:
                await asyncio.sleep(random.uniform(random_delay_min, random_delay_max))
            ok, err_msg = await asyncio.to_thread(
                send_message,
                wx,
                chat_name,
                chunk,
                bot_cfg,
            )
            if not ok:
                logging.error(
                    build_stage_log_message(
                        "SEND.CHUNK_FAILED",
                        target=chat_name,
                        chunk_index=idx + 1,
                        chunk_total=len(chunks),
                        error=err_msg,
                    )
                )
                return False, err_msg
            last_reply_ts["ts"] = time.time()
        logging.info(
            build_stage_log_message(
                "SEND.CHUNK_DONE",
                target=chat_name,
                chunk_index=idx + 1,
                chunk_total=len(chunks),
            )
        )
        if idx < len(chunks) - 1 and chunk_delay_sec > 0:
            await asyncio.sleep(chunk_delay_sec)
    logging.info(
        build_stage_log_message(
            "SEND.CHUNKS_DONE",
            target=chat_name,
            chunks=len(chunks),
        )
    )
    return True, None
