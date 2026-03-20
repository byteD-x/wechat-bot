from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..utils.common import as_int
from ..utils.config import resolve_system_prompt
from ..utils.image_processing import process_image_for_api

logger = logging.getLogger(__name__)


def remaining_prepare_budget(runtime: Any, started: float) -> float:
    return max(0.0, runtime.prepare_soft_budget_sec - (time.perf_counter() - started))


async def resolve_context_task(
    runtime: Any,
    task: Optional[asyncio.Task],
    *,
    step_name: str,
    started: float,
    skipped_context_steps: List[str],
    warning_message: str,
    timeout_sec: Optional[float] = None,
) -> Any:
    if task is None:
        return None

    budget = remaining_prepare_budget(runtime, started)
    if timeout_sec is not None:
        budget = min(budget, timeout_sec)
    if budget <= 0:
        skipped_context_steps.append(step_name)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return None

    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=budget)
    except asyncio.TimeoutError:
        skipped_context_steps.append(step_name)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.info(
            "Skipping %s for reply budget [%s] after %.0f ms",
            step_name,
            step_name,
            budget * 1000,
        )
        return None
    except Exception as exc:
        logger.warning("%s [%s]: %s", warning_message, step_name, exc)
        return None


async def load_context_node(runtime: Any, state: Dict[str, Any]) -> Dict[str, Any]:
    event = state["event"]
    chat_id = state["chat_id"]
    user_text = state["user_text"]
    dependencies = state.get("dependencies") or {}
    memory = dependencies.get("memory")

    started = time.perf_counter()
    memory_context: List[dict] = []
    short_term_preview: List[str] = []
    skipped_context_steps: List[str] = []
    context_task: Optional[asyncio.Task] = None
    profile_task: Optional[asyncio.Task] = None

    limit = as_int(runtime.bot_cfg.get("memory_context_limit", 5), 5, min_value=0)
    if memory and limit > 0:
        context_task = asyncio.create_task(memory.get_recent_context(chat_id, limit))
    if memory and runtime.bot_cfg.get("personalization_enabled", False):
        get_snapshot = getattr(memory, "get_profile_prompt_snapshot", None)
        if callable(get_snapshot):
            profile_task = asyncio.create_task(get_snapshot(chat_id))
        else:
            profile_task = asyncio.create_task(memory.get_user_profile(chat_id))

    context_result = await resolve_context_task(
        runtime,
        context_task,
        step_name="recent_context",
        started=started,
        skipped_context_steps=skipped_context_steps,
        warning_message=f"短期记忆加载失败 [{chat_id}]",
    )
    if context_result:
        memory_context = list(context_result or [])
        short_term_preview = [
            str(item.get("content") or "").strip()
            for item in memory_context[:3]
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]

    user_profile = await resolve_context_task(
        runtime,
        profile_task,
        step_name="user_profile",
        started=started,
        skipped_context_steps=skipped_context_steps,
        warning_message=f"用户画像加载失败 [{chat_id}]",
        timeout_sec=runtime.prepare_optional_timeout_sec,
    )

    timings = dict(state.get("timings") or {})
    timings["load_context_budget_sec"] = round(runtime.prepare_soft_budget_sec, 4)
    timings["load_context_sec"] = round(time.perf_counter() - started, 4)
    trace = {
        "context_summary": {
            "short_term_messages": len(memory_context),
            "short_term_preview": short_term_preview,
            "skipped_context_steps": list(skipped_context_steps),
            "growth_mode": "deferred_until_batch",
        },
        "profile": runtime._serialize_profile(user_profile),
    }
    return {
        "memory_context": memory_context,
        "user_profile": user_profile,
        "current_emotion": None,
        "timings": timings,
        "trace": trace,
        "event": event,
        "chat_id": chat_id,
        "user_text": user_text,
        "dependencies": dependencies,
        "image_path": state.get("image_path"),
        "skipped_context_steps": skipped_context_steps,
    }


async def build_prompt_node(runtime: Any, state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    system_prompt = resolve_system_prompt(
        state["event"],
        runtime.bot_cfg,
        state.get("user_profile"),
        state.get("current_emotion"),
        list(state.get("memory_context") or []),
    )
    prompt_messages = build_prompt_messages(
        runtime,
        system_prompt=system_prompt,
        memory_context=list(state.get("memory_context") or []),
        user_text=str(state.get("user_text") or ""),
        image_path=state.get("image_path"),
        event=state.get("event"),
    )
    timings = dict(state.get("timings") or {})
    timings["build_prompt_sec"] = round(time.perf_counter() - started, 4)
    return {
        **state,
        "system_prompt": system_prompt,
        "prompt_messages": prompt_messages,
        "timings": timings,
    }


def build_prompt_messages(
    runtime: Any,
    *,
    system_prompt: str,
    memory_context: List[dict],
    user_text: str,
    image_path: Optional[str],
    event: Any = None,
) -> List[Any]:
    system_message = runtime._imports["SystemMessage"]
    human_message = runtime._imports["HumanMessage"]
    ai_message = runtime._imports["AIMessage"]

    messages: List[Any] = []
    if system_prompt:
        messages.append(system_message(content=system_prompt))

    for item in memory_context:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        content = item.get("content")
        if content is None:
            continue
        text = str(content).strip()
        if not text:
            continue
        if role == "assistant":
            messages.append(ai_message(content=text))
        elif role == "system":
            messages.append(system_message(content=text))
        else:
            messages.append(human_message(content=text))

    final_user_text = str(user_text or "")
    if (
        event is not None
        and bool(getattr(event, "is_group", False))
        and runtime.bot_cfg.get("group_include_sender", True)
    ):
        sender = str(getattr(event, "sender", "") or "").strip()
        if sender:
            final_user_text = f"[{sender}] {final_user_text}".strip()

    if image_path:
        base64_image = process_image_for_api(image_path)
        if base64_image:
            messages.append(
                human_message(
                    content=[
                        {"type": "text", "text": user_text or "这张图片里有什么？"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ]
                )
            )
            return messages

    messages.append(human_message(content=final_user_text))
    return messages


async def search_runtime_memory(runtime: Any, chat_id: str, user_text: str, vector_memory: Any) -> Optional[dict]:
    if not str(user_text or "").strip():
        return None

    embedding = await runtime.get_embedding(user_text)
    results = await asyncio.to_thread(
        vector_memory.search,
        query=user_text if not embedding else None,
        n_results=runtime.retriever_fetch_k,
        filter_meta={"chat_id": chat_id, "source": "runtime_chat"},
        query_embedding=embedding,
    )
    if not results:
        return None

    ranked_results = await rerank_runtime_results(runtime, user_text, results)
    lines: List[str] = []
    for item in ranked_results:
        distance = item.get("distance")
        if distance is not None and float(distance) > runtime.retriever_score_threshold:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        lines.append(text)
        if len(lines) >= runtime.retriever_top_k:
            break

    if not lines:
        return None

    runtime._stats["retriever_hits"] += len(lines)
    return {
        "role": "system",
        "content": "Relevant past memories:\n" + "\n".join(lines),
        "hit_count": len(lines),
        "trace_snippets": lines[:5],
    }


async def rerank_runtime_results(
    runtime: Any,
    query_text: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if runtime._cross_encoder_reranker is not None:
        try:
            ranked = await asyncio.to_thread(
                rerank_runtime_results_cross_encoder,
                runtime,
                query_text,
                results,
            )
            runtime._rerank_backend = "cross_encoder"
            return ranked
        except Exception as exc:
            runtime._stats["retriever_rerank_fallbacks"] += 1
            runtime._rerank_backend = "lightweight"
            logger.warning("Cross-Encoder 精排失败，已回退轻量重排: %s", exc)

    runtime._rerank_backend = "lightweight"
    return rerank_runtime_results_lightweight(runtime, query_text, results)


def rerank_runtime_results_cross_encoder(
    runtime: Any,
    query_text: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    reranker = runtime._cross_encoder_reranker
    if reranker is None:
        return rerank_runtime_results_lightweight(runtime, query_text, results)

    pairs: List[List[str]] = []
    candidates: List[tuple[int, Dict[str, Any]]] = []
    for index, item in enumerate(results):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        pairs.append([query_text, text])
        candidates.append((index, item))

    if not pairs:
        return list(results)

    raw_scores = list(reranker.predict(pairs))
    ranked: List[Dict[str, Any]] = []
    for (index, item), raw_score in zip(candidates, raw_scores):
        try:
            cross_encoder_score = float(raw_score)
        except (TypeError, ValueError):
            cross_encoder_score = 0.0

        distance = item.get("distance")
        try:
            semantic_score = max(0.0, 1.0 - float(distance))
        except (TypeError, ValueError):
            semantic_score = 0.0

        ranked.append({
            **item,
            "cross_encoder_score": round(cross_encoder_score, 4),
            "semantic_score": round(semantic_score, 4),
            "rerank_score": round(cross_encoder_score, 4),
            "_original_index": index,
        })

    ranked.sort(
        key=lambda item: (
            item.get("cross_encoder_score", 0.0),
            item.get("semantic_score", 0.0),
            -item.get("_original_index", 0),
        ),
        reverse=True,
    )
    for item in ranked:
        item.pop("_original_index", None)
    return ranked


def rerank_runtime_results_lightweight(
    runtime: Any,
    query_text: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    query_tokens = tokenize_rerank_text(query_text)
    if not query_tokens:
        return list(results)

    ranked: List[Dict[str, Any]] = []
    for index, item in enumerate(results):
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        candidate_tokens = tokenize_rerank_text(text)
        overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
        distance = item.get("distance")
        try:
            semantic_score = max(0.0, 1.0 - float(distance))
        except (TypeError, ValueError):
            semantic_score = 0.0

        rerank_score = round((semantic_score * 0.7) + (overlap * 0.3), 4)
        ranked.append({
            **item,
            "rerank_score": rerank_score,
            "_original_index": index,
        })

    ranked.sort(
        key=lambda item: (
            item.get("rerank_score", 0.0),
            -item.get("_original_index", 0),
        ),
        reverse=True,
    )
    for item in ranked:
        item.pop("_original_index", None)
    return ranked


def tokenize_rerank_text(text: str) -> set[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return set()

    word_tokens = {
        part
        for part in re.findall(r"[0-9a-zA-Z\u4e00-\u9fff]+", normalized)
        if part
    }
    if len(word_tokens) > 1:
        return word_tokens

    return {
        char
        for char in normalized
        if char.strip() and re.match(r"[0-9a-zA-Z\u4e00-\u9fff]", char)
    }


__all__ = [
    "build_prompt_messages",
    "build_prompt_node",
    "load_context_node",
    "remaining_prepare_budget",
    "rerank_runtime_results",
    "rerank_runtime_results_cross_encoder",
    "rerank_runtime_results_lightweight",
    "resolve_context_task",
    "search_runtime_memory",
    "tokenize_rerank_text",
]
