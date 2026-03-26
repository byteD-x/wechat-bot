from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

from .core.bot_control import is_command_message, parse_control_command
from .handlers.sender import send_message
from .types import MessageEvent
from .utils.message import is_image_message
from .utils.runtime_artifacts import runtime_path


async def maybe_save_event_image(
    event: MessageEvent,
    *,
    save_root: Optional[str] = None,
    trace_id: Optional[str] = None,
    log_flow: Optional[Any] = None,
) -> Optional[str]:
    if not (is_image_message(event.msg_type) and "[图片]" in str(event.content or "")):
        return None
    if not getattr(event, "raw_item", None):
        return None

    try:
        filename = f"{int(time.time())}_{hash(getattr(event, 'sender', ''))}.jpg"
        save_path = save_root or runtime_path("event-images", filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        await asyncio.to_thread(event.raw_item.save_file, save_path)
        if callable(log_flow):
            log_flow(
                20,
                "EVENT.IMAGE_SAVED",
                event=event,
                trace_id=trace_id,
                path=save_path,
            )
        return save_path
    except Exception as exc:
        if callable(log_flow):
            log_flow(
                40,
                "EVENT.IMAGE_SAVE_FAILED",
                event=event,
                trace_id=trace_id,
                error=str(exc),
            )
        return None


def build_incoming_recipient(event: MessageEvent) -> str:
    return f"group:{event.chat_name}" if event.is_group else "Bot"


def build_incoming_broadcast_payload(
    event: MessageEvent,
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "direction": "incoming",
        "chat_id": f"group:{event.chat_name}" if event.is_group else f"friend:{event.chat_name}",
        "chat_name": event.chat_name,
        "sender": event.sender,
        "content": event.content,
        "recipient": build_incoming_recipient(event),
        "timestamp": event.timestamp or (now if now is not None else time.time()),
    }


def record_incoming_event(ipc: Any, event: MessageEvent) -> str:
    recipient = build_incoming_recipient(event)
    ipc.log_message(event.sender, event.content, "incoming", recipient)
    return recipient


def schedule_incoming_broadcast(bot_manager: Any, event: MessageEvent) -> None:
    asyncio.create_task(
        bot_manager.broadcast_event(
            "message",
            build_incoming_broadcast_payload(event),
        )
    )


async def handle_control_command(
    *,
    wx: Any,
    event: MessageEvent,
    trace_id: Optional[str],
    bot_cfg: Dict[str, Any],
    log_flow: Any,
    bot_manager: Any,
    wx_lock: asyncio.Lock,
) -> bool:
    cmd_prefix = bot_cfg.get("control_command_prefix", "/")
    if not is_command_message(event.content, cmd_prefix):
        return False

    allowed = bot_cfg.get("control_allowed_users", [])
    result = await asyncio.to_thread(
        parse_control_command,
        event.content,
        cmd_prefix,
        allowed,
        event.sender,
    )

    if not result or not result.should_reply:
        return False

    log_flow(
        20,
        "CONTROL.MATCHED",
        event=event,
        trace_id=trace_id,
        command=result.command,
        args=result.args,
    )
    if result.command in ("pause", "resume"):
        await bot_manager.apply_pause_state(
            result.command == "pause",
            reason=(" ".join(result.args) or "手动暂停") if result.command == "pause" else "",
            propagate_to_bot=False,
        )
    if bot_cfg.get("control_reply_visible", True):
        async with wx_lock:
            await asyncio.to_thread(
                send_message, wx, event.chat_name, result.response, bot_cfg
            )
    log_flow(
        20,
        "CONTROL.DONE",
        event=event,
        trace_id=trace_id,
        command=result.command,
    )
    return True


async def maybe_send_quiet_reply(
    *,
    wx: Any,
    event: MessageEvent,
    quiet_reply: str,
    bot_cfg: Dict[str, Any],
    wx_lock: asyncio.Lock,
) -> None:
    if not str(quiet_reply or "").strip():
        return
    async with wx_lock:
        await asyncio.to_thread(
            send_message, wx, event.chat_name, quiet_reply, bot_cfg
        )


__all__ = [
    "build_incoming_broadcast_payload",
    "build_incoming_recipient",
    "handle_control_command",
    "maybe_save_event_image",
    "maybe_send_quiet_reply",
    "record_incoming_event",
    "schedule_incoming_broadcast",
]
