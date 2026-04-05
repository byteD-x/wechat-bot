from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from .types import MessageEvent
from .utils.common import as_float
from .core.reply_policy import build_chat_id


def mark_deadline_missed(
    prepared: Any,
    reply_deadline_sec: float,
    *,
    reason: str,
) -> None:
    prepared.response_metadata["deadline_missed"] = True
    prepared.response_metadata["delayed_reply"] = True
    prepared.response_metadata["response_deadline_sec"] = reply_deadline_sec
    prepared.response_metadata["deadline_reason"] = reason


def build_outgoing_broadcast_payload(
    *,
    chat_id: str,
    event: MessageEvent,
    reply_text: str,
    response_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "direction": "outgoing",
        "chat_id": chat_id,
        "chat_name": event.chat_name,
        "sender": "Bot",
        "content": reply_text,
        "recipient": event.chat_name,
        "timestamp": time.time(),
        "metadata": response_metadata,
    }


async def maybe_queue_manual_reply(
    bot: Any,
    *,
    prepared: Any,
    event: MessageEvent,
    user_text: str,
    chat_id: str,
    reply_text: str,
    trace_id: Optional[str],
) -> bool:
    policy_result = await bot.evaluate_outgoing_reply_policy(
        event=event,
        user_text=user_text,
        reply_text=reply_text,
    )
    if not bool(policy_result.get("should_queue")):
        return False

    bot._log_flow(
        logging.INFO,
        "AI.REPLY_QUEUED_FOR_APPROVAL",
        event=event,
        trace_id=trace_id,
        chat_id=chat_id,
        reason=str(policy_result.get("trigger_reason") or "manual_review"),
    )
    await bot.queue_pending_reply(
        prepared=prepared,
        event=event,
        chat_id=chat_id,
        user_text=user_text,
        reply_text=reply_text,
        trace_id=trace_id,
        policy_result=policy_result,
    )
    return True


async def finalize_reply_delivery(
    bot: Any,
    *,
    prepared: Any,
    event: MessageEvent,
    chat_id: str,
    user_text: str,
    reply_text: str,
    trace_id: Optional[str],
    streamed: bool,
) -> str:
    if not reply_text:
        bot._log_flow(
            logging.WARNING,
            "AI.REPLY_EMPTY",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
        )
        return ""

    timings = dict(getattr(prepared, "timings", {}) or {})
    latency_sec = 0.0
    for key in ("stream_sec", "invoke_sec", "prepare_total_sec"):
        value = timings.get(key)
        if value:
            latency_sec = float(value)
            break

    deadline_missed = bool(prepared.response_metadata.get("deadline_missed"))
    delayed_reply = bool(prepared.response_metadata.get("delayed_reply"))
    if deadline_missed:
        detail = (
            f"Last AI call missed {prepared.response_metadata.get('response_deadline_sec', bot.bot_cfg.get('reply_deadline_sec', 0.0))}s "
            f"deadline on preset {bot.runtime_preset_name or 'unknown'}"
        )
        if delayed_reply:
            detail = f"{detail} and was sent later"
        bot._set_ai_health("degraded", detail, success=True)
    elif latency_sec > 0:
        detail = (
            f"Last AI call succeeded on preset {bot.runtime_preset_name or 'unknown'} "
            f"in {round(latency_sec * 1000)} ms"
        )
        bot._set_ai_health("healthy", detail, success=True)
    else:
        detail = f"Last AI call succeeded on preset {bot.runtime_preset_name or 'unknown'}"
        bot._set_ai_health("healthy", detail, success=True)

    response_metadata = bot._build_reply_metadata(
        prepared=prepared,
        event=event,
        chat_id=chat_id,
        user_text=user_text,
        reply_text=reply_text,
        streamed=streamed,
    )
    prepared.response_metadata = response_metadata
    bot._log_flow(
        logging.INFO,
        "AI.REPLY_READY",
        event=event,
        trace_id=trace_id,
        chat_id=chat_id,
        streamed=streamed,
        reply=bot._reply_preview(reply_text),
    )

    bot.ipc.log_message("Bot", reply_text, "outgoing", event.sender)
    asyncio.create_task(
        bot.bot_manager.broadcast_event(
            "message",
            build_outgoing_broadcast_payload(
                chat_id=chat_id,
                event=event,
                reply_text=reply_text,
                response_metadata=response_metadata,
            ),
        )
    )

    bot._log_flow(
        logging.INFO,
        "AI.FINALIZE_START",
        event=event,
        trace_id=trace_id,
        chat_id=chat_id,
    )
    await bot.ai_client.finalize_request(
        prepared,
        reply_text,
        bot._runtime_dependencies(),
    )
    bot._record_reply_success(response_metadata)
    bot._log_flow(
        logging.INFO,
        "AI.FINALIZE_DONE",
        event=event,
        trace_id=trace_id,
        chat_id=chat_id,
    )
    bot._record_reply_stats(user_text, reply_text)
    return reply_text


async def complete_delayed_reply(
    bot: Any,
    *,
    wx: Any,
    event: MessageEvent,
    prepared: Any,
    user_text: str,
    chat_id: str,
    trace_id: Optional[str],
    invoke_task: asyncio.Task,
    reply_deadline_sec: float,
) -> None:
    try:
        invoke_reply = await invoke_task
    except Exception as exc:
        prepared.response_metadata["response_error"] = str(exc)
        bot._set_ai_health("error", f"Delayed AI call failed: {exc}", error=True)
        bot._record_reply_failure()
        bot._log_flow(
            logging.ERROR,
            "AI.DELAYED_REPLY_FAILED",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
            error=str(exc),
        )
        return

    if not str(invoke_reply or "").strip():
        prepared.response_metadata["empty_reply"] = True
        bot._record_reply_empty()
        bot._set_ai_health(
            "degraded",
            (
                f"Last AI call returned empty reply after missing {reply_deadline_sec}s "
                f"deadline on preset {bot.runtime_preset_name or 'unknown'}"
            ),
            success=True,
        )
        bot._log_flow(
            logging.WARNING,
            "AI.DELAYED_REPLY_SKIPPED_EMPTY",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
            tool_call_only=bool(prepared.response_metadata.get("tool_call_only_response")),
        )
        return

    bot._log_flow(
        logging.INFO,
        "CONV.AI_DONE",
        event=event,
        trace_id=trace_id,
        chat_id=chat_id,
        reply=bot._reply_preview(invoke_reply),
    )

    try:
        async with bot._get_chat_lock(chat_id):
            if await maybe_queue_manual_reply(
                bot,
                prepared=prepared,
                event=event,
                user_text=user_text,
                chat_id=chat_id,
                reply_text=invoke_reply,
                trace_id=trace_id,
            ):
                return
            reply_text = await bot._send_smart_reply(
                wx,
                event,
                invoke_reply,
                trace_id=trace_id,
            )
            await finalize_reply_delivery(
                bot,
                prepared=prepared,
                event=event,
                chat_id=chat_id,
                user_text=user_text,
                reply_text=reply_text,
                trace_id=trace_id,
                streamed=False,
            )
    except Exception as exc:
        bot._set_ai_health("error", f"Delayed reply delivery failed: {exc}", error=True)
        bot._record_reply_failure()
        bot._log_flow(
            logging.ERROR,
            "AI.DELAYED_REPLY_DELIVERY_FAILED",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
            error=str(exc),
        )


def schedule_delayed_reply(
    bot: Any,
    *,
    wx: Any,
    event: MessageEvent,
    prepared: Any,
    user_text: str,
    chat_id: str,
    trace_id: Optional[str],
    invoke_task: asyncio.Task,
    reply_deadline_sec: float,
) -> None:
    task = asyncio.create_task(
        complete_delayed_reply(
            bot,
            wx=wx,
            event=event,
            prepared=prepared,
            user_text=user_text,
            chat_id=chat_id,
            trace_id=trace_id,
            invoke_task=invoke_task,
            reply_deadline_sec=reply_deadline_sec,
        )
    )
    bot._track_pending_task(task)
    task.add_done_callback(bot.pending_tasks.discard)


async def process_and_reply(
    bot: Any,
    wx: Any,
    event: MessageEvent,
    user_text: str,
    message_log: str,
    *,
    image_path: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    del message_log
    bot._ensure_event_defaults(event)
    chat_id = await bot._reconcile_event_chat_identity(event)
    if not bot.ai_client:
        bot._log_flow(
            logging.WARNING,
            "AI.SKIP_UNAVAILABLE",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
        )
        return

    bot._record_reply_attempt()
    try:
        async with bot._get_chat_lock(chat_id):
            started = time.perf_counter()
            bot._log_flow(
                logging.INFO,
                "AI.PREPARE_START",
                event=event,
                trace_id=trace_id,
                chat_id=chat_id,
                user_text=bot._message_preview(user_text),
            )
            prepared = await bot.ai_client.prepare_request(
                event=event,
                chat_id=chat_id,
                user_text=user_text,
                dependencies=bot._runtime_dependencies(),
                image_path=image_path,
            )
            bot._log_flow(
                logging.INFO,
                "CONV.PREPARE_DONE",
                event=event,
                trace_id=trace_id,
                chat_id=chat_id,
                has_image=bool(image_path),
            )

            reply_text = ""
            should_stream = False
            reply_deadline_sec = as_float(
                bot.bot_cfg.get("reply_deadline_sec", 0.0),
                0.0,
                min_value=0.0,
            )
            invoke_task = asyncio.create_task(bot.ai_client.invoke(prepared))
            if reply_deadline_sec <= 0:
                bot._log_flow(
                    logging.INFO,
                    "AI.INVOKE_START",
                    event=event,
                    trace_id=trace_id,
                    chat_id=chat_id,
                    mode="sync",
                    deadline_disabled=True,
                )
                try:
                    invoke_reply = await invoke_task
                except Exception as exc:
                    prepared.response_metadata["response_error"] = str(exc)
                    bot._log_flow(
                        logging.ERROR,
                        "AI.INVOKE_FAILED",
                        event=event,
                        trace_id=trace_id,
                        chat_id=chat_id,
                        error=str(exc),
                    )
                    raise
            else:
                elapsed_before_invoke = time.perf_counter() - started
                remaining_budget = max(0.0, reply_deadline_sec - elapsed_before_invoke)

                if remaining_budget <= 0:
                    mark_deadline_missed(
                        prepared,
                        reply_deadline_sec,
                        reason="deadline_exhausted_before_invoke",
                    )
                    bot._log_flow(
                        logging.WARNING,
                        "AI.DEADLINE_EXHAUSTED",
                        event=event,
                        trace_id=trace_id,
                        chat_id=chat_id,
                        deadline_sec=reply_deadline_sec,
                    )
                    schedule_delayed_reply(
                        bot,
                        wx=wx,
                        event=event,
                        prepared=prepared,
                        user_text=user_text,
                        chat_id=chat_id,
                        trace_id=trace_id,
                        invoke_task=invoke_task,
                        reply_deadline_sec=reply_deadline_sec,
                    )
                    return

                bot._log_flow(
                    logging.INFO,
                    "AI.INVOKE_START",
                    event=event,
                    trace_id=trace_id,
                    chat_id=chat_id,
                    mode="sync",
                    deadline_ms=round(remaining_budget * 1000),
                )
                try:
                    invoke_reply = await asyncio.wait_for(
                        asyncio.shield(invoke_task),
                        timeout=remaining_budget,
                    )
                except asyncio.TimeoutError:
                    mark_deadline_missed(
                        prepared,
                        reply_deadline_sec,
                        reason="timeout",
                    )
                    bot._log_flow(
                        logging.WARNING,
                        "AI.DELAYED_REPLY_SCHEDULED",
                        event=event,
                        trace_id=trace_id,
                        chat_id=chat_id,
                        deadline_sec=reply_deadline_sec,
                    )
                    schedule_delayed_reply(
                        bot,
                        wx=wx,
                        event=event,
                        prepared=prepared,
                        user_text=user_text,
                        chat_id=chat_id,
                        trace_id=trace_id,
                        invoke_task=invoke_task,
                        reply_deadline_sec=reply_deadline_sec,
                    )
                    return
                except Exception as exc:
                    prepared.response_metadata["response_error"] = str(exc)
                    bot._log_flow(
                        logging.ERROR,
                        "AI.INVOKE_FAILED",
                        event=event,
                        trace_id=trace_id,
                        chat_id=chat_id,
                        error=str(exc),
                    )
                    raise

            if not str(invoke_reply or "").strip():
                prepared.response_metadata["empty_reply"] = True
                bot._record_reply_empty()
                bot._set_ai_health(
                    "degraded",
                    f"Last AI call returned empty reply on preset {bot.runtime_preset_name or 'unknown'}",
                    success=True,
                )
                bot._log_flow(
                    logging.WARNING,
                    "AI.REPLY_SKIPPED_EMPTY",
                    event=event,
                    trace_id=trace_id,
                    chat_id=chat_id,
                    tool_call_only=bool(prepared.response_metadata.get("tool_call_only_response")),
                )
                return

            bot._log_flow(
                logging.INFO,
                "CONV.AI_DONE",
                event=event,
                trace_id=trace_id,
                chat_id=chat_id,
                reply=bot._reply_preview(invoke_reply),
            )
            if await maybe_queue_manual_reply(
                bot,
                prepared=prepared,
                event=event,
                user_text=user_text,
                chat_id=chat_id,
                reply_text=invoke_reply,
                trace_id=trace_id,
            ):
                return
            reply_text = await bot._send_smart_reply(
                wx,
                event,
                invoke_reply,
                trace_id=trace_id,
            )
    except Exception as exc:
        bot._set_ai_health("error", f"Last AI call failed: {exc}", error=True)
        bot._record_reply_failure()
        bot._log_flow(
            logging.ERROR,
            "AI.FAILED",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
            error=str(exc),
        )
        raise

    try:
        await finalize_reply_delivery(
            bot,
            prepared=prepared,
            event=event,
            chat_id=chat_id,
            user_text=user_text,
            reply_text=reply_text,
            trace_id=trace_id,
            streamed=should_stream,
        )
    finally:
        if image_path and os.path.exists(image_path):
            await asyncio.to_thread(os.remove, image_path)


__all__ = [
    "build_outgoing_broadcast_payload",
    "complete_delayed_reply",
    "finalize_reply_delivery",
    "mark_deadline_missed",
    "process_and_reply",
    "schedule_delayed_reply",
]
