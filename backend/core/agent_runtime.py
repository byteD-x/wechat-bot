from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
import httpx

from ..schemas import EmotionResult
from ..utils.common import as_float, as_int
from ..utils.config import is_placeholder_key, resolve_system_prompt
from ..utils.image_processing import process_image_for_api
from ..utils.logging import build_stage_log_message
from .provider_compat import (
    build_openai_chat_payload,
    extract_reasoning_text as compat_extract_reasoning_text,
    extract_visible_text as compat_extract_visible_text,
    normalize_chat_result,
    normalize_provider_error,
)
from .emotion import (
    detect_emotion_keywords,
    get_emotion_analysis_prompt,
    get_fact_extraction_prompt,
    get_relationship_evolution_hint,
    parse_emotion_ai_response,
    parse_fact_extraction_response,
)

logger = logging.getLogger(__name__)
_ALLOW_EMPTY_KEY_PLACEHOLDER = "wechat-chat-allow-empty-key"
_QWEN_RUNTIME_MIN_TIMEOUT_SEC = 15.0
_BACKGROUND_GLOBAL_CHAT_ID = "__global__"
_TASK_EMOTION = "emotion"
_TASK_CONTACT_PROMPT = "contact_prompt"
_TASK_VECTOR_MEMORY = "vector_memory"
_TASK_FACTS = "facts"
_TASK_EXPORT_RAG_SYNC = "export_rag_sync"
_BACKGROUND_TASK_ORDER = {
    _TASK_EXPORT_RAG_SYNC: 10,
    _TASK_EMOTION: 20,
    _TASK_FACTS: 30,
    _TASK_VECTOR_MEMORY: 40,
    _TASK_CONTACT_PROMPT: 50,
}
_BACKGROUND_TASK_TYPES = frozenset(_BACKGROUND_TASK_ORDER)


@dataclass(slots=True)
class AgentPreparedRequest:
    chat_id: str
    user_text: str
    system_prompt: str
    prompt_messages: List[Any]
    event: Any = None
    memory_context: List[dict] = field(default_factory=list)
    user_profile: Optional[Any] = None
    current_emotion: Optional[EmotionResult] = None
    timings: Dict[str, float] = field(default_factory=dict)
    trace: Dict[str, Any] = field(default_factory=dict)
    response_metadata: Dict[str, Any] = field(default_factory=dict)
    image_path: Optional[str] = None


def _extract_message_text(message: Any) -> str:
    return compat_extract_visible_text(message)


def _extract_reasoning_fragments(value: Any, *, inside_reasoning: bool = False) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text and inside_reasoning else []
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            parts.extend(_extract_reasoning_fragments(item, inside_reasoning=inside_reasoning))
        return parts
    if isinstance(value, dict):
        parts: List[str] = []
        block_type = str(value.get("type") or "").strip().lower()
        if block_type == "summary_text":
            text = str(value.get("text") or "").strip()
            if text and inside_reasoning:
                parts.append(text)
            return parts
        if block_type == "reasoning":
            parts.extend(_extract_reasoning_fragments(value.get("reasoning"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("summary"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("content"), inside_reasoning=True))
        else:
            parts.extend(_extract_reasoning_fragments(value.get("reasoning_content"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("reasoning"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("summary"), inside_reasoning=True))
            if inside_reasoning and block_type in {"text", "output_text", "input_text", ""}:
                text = str(value.get("text") or "").strip()
                if text:
                    parts.append(text)
        content = value.get("content")
        if isinstance(content, list):
            parts.extend(_extract_reasoning_fragments(content, inside_reasoning=inside_reasoning))
        deduped: List[str] = []
        for item in parts:
            if item and item not in deduped:
                deduped.append(item)
        return deduped
    return []


def _extract_reasoning_text(message: Any) -> str:
    return compat_extract_reasoning_text(message)


def _detect_message_role(message: Any) -> str:
    role = str(
        getattr(message, "type", None)
        or getattr(message, "role", None)
        or getattr(message, "message_type", None)
        or ""
    ).strip().lower()
    if role in {"human", "user"}:
        return "user"
    if role in {"ai", "assistant"}:
        return "assistant"
    if role in {"system"}:
        return "system"
    return "user"


class AgentRuntime:
    """基于 LangChain/LangGraph 的统一编排运行时。"""

    def __init__(
        self,
        settings: Dict[str, Any],
        bot_cfg: Dict[str, Any],
        agent_cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.settings = dict(settings)
        self.bot_cfg = dict(bot_cfg)
        self.agent_cfg = dict(agent_cfg or {})
        self.base_url = str(settings.get("base_url") or "").strip().rstrip("/")
        self.api_key = str(settings.get("api_key") or "").strip()
        self.allow_empty_key = bool(settings.get("allow_empty_key", False))
        self.runtime_api_key = self.api_key or (
            _ALLOW_EMPTY_KEY_PLACEHOLDER if self.allow_empty_key else None
        )
        self.model = str(settings.get("model") or "").strip()
        self.model_alias = str(settings.get("alias") or "").strip()
        self.provider_id = str(settings.get("provider_id") or "").strip().lower()
        embedding_model = str(settings.get("embedding_model") or "").strip()
        self.embedding_model = None if is_placeholder_key(embedding_model) else (embedding_model or None)
        self.timeout_sec = as_float(settings.get("timeout_sec", 10.0), 10.0, min_value=0.1)
        self.effective_timeout_sec = self._resolve_effective_timeout_sec(self.timeout_sec)
        self.max_retries = as_int(settings.get("max_retries", 1), 1, min_value=0)
        self.temperature = settings.get("temperature")
        self.max_tokens = settings.get("max_tokens")
        self.max_completion_tokens = settings.get("max_completion_tokens")
        self.reasoning_effort = settings.get("reasoning_effort")
        self.reply_deadline_sec = as_float(
            self.bot_cfg.get("reply_deadline_sec", 0.0), 0.0, min_value=0.0
        )
        prepare_budget_basis_sec = self.reply_deadline_sec
        self.prepare_soft_budget_sec = max(
            0.15,
            min(0.8, round(prepare_budget_basis_sec * 0.35, 4)),
        )
        self.prepare_optional_timeout_sec = max(
            0.05,
            min(0.25, round(self.prepare_soft_budget_sec * 0.5, 4)),
        )

        self.graph_mode = str(self.agent_cfg.get("graph_mode") or "state_graph").strip() or "state_graph"
        self.langsmith_enabled = bool(self.agent_cfg.get("langsmith_enabled", False))
        self.langsmith_project = str(self.agent_cfg.get("langsmith_project") or "wechat-chat").strip() or "wechat-chat"
        self.embedding_cache_ttl_sec = as_float(
            self.agent_cfg.get("embedding_cache_ttl_sec", 300.0), 300.0, min_value=0.0
        )
        self.retriever_top_k = as_int(self.agent_cfg.get("retriever_top_k", 3), 3, min_value=1)
        self.retriever_fetch_k = max(self.retriever_top_k, self.retriever_top_k * 3)
        self.retriever_score_threshold = as_float(
            self.agent_cfg.get("retriever_score_threshold", 1.0), 1.0, min_value=0.0
        )
        self.retriever_rerank_mode = str(
            self.agent_cfg.get("retriever_rerank_mode") or "lightweight"
        ).strip().lower() or "lightweight"
        if self.retriever_rerank_mode not in {"auto", "lightweight", "cross_encoder"}:
            self.retriever_rerank_mode = "lightweight"
        self.retriever_cross_encoder_model = str(
            self.agent_cfg.get("retriever_cross_encoder_model") or ""
        ).strip()
        self.retriever_cross_encoder_device = str(
            self.agent_cfg.get("retriever_cross_encoder_device") or ""
        ).strip()
        self.max_parallel_retrievers = as_int(
            self.agent_cfg.get("max_parallel_retrievers", 3), 3, min_value=1
        )
        self.emotion_fast_path_enabled = bool(
            self.agent_cfg.get("emotion_fast_path_enabled", True)
        )
        self.background_fact_extraction_enabled = bool(
            self.agent_cfg.get("background_fact_extraction_enabled", True)
        )
        self.llm_foreground_max_concurrency = as_int(
            self.agent_cfg.get("llm_foreground_max_concurrency", 1),
            1,
            min_value=1,
        )
        self.background_ai_batch_time = str(
            self.agent_cfg.get("background_ai_batch_time") or "04:00"
        ).strip() or "04:00"
        self.background_ai_missed_window_policy = str(
            self.agent_cfg.get("background_ai_missed_window_policy")
            or "wait_until_next_day"
        ).strip() or "wait_until_next_day"
        self.background_ai_defer_mode = str(
            self.agent_cfg.get("background_ai_defer_mode") or "defer_all"
        ).strip() or "defer_all"

        self._chat_locks: Dict[str, asyncio.Lock] = {}
        self._embedding_cache: Dict[str, tuple[float, List[float]]] = {}
        self._embedding_pending: Dict[str, asyncio.Future] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._runtime_dependencies: Dict[str, Any] = {}
        self._llm_condition: Optional[asyncio.Condition] = None
        self._foreground_active = 0
        self._foreground_waiters = 0
        self._background_active = 0
        self._batch_scheduler_task: Optional[asyncio.Task] = None
        self._batch_runner_task: Optional[asyncio.Task] = None
        self._batch_lock = asyncio.Lock()

        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "embedding_cache_hits": 0,
            "embedding_cache_misses": 0,
            "retriever_hits": 0,
            "retriever_rerank_fallbacks": 0,
            "last_timings": {},
            "growth_mode": "deferred_until_batch",
            "last_growth_error": "",
            "foreground_active": 0,
            "foreground_waiters": 0,
            "background_active": 0,
            "background_backlog_count": 0,
            "background_backlog_by_task": {},
            "next_background_batch_at": None,
            "last_background_batch": {},
        }

        self._imports = self._load_integrations()
        self._configure_langsmith()
        self._cross_encoder_reranker = self._build_cross_encoder_reranker()
        self._rerank_backend = (
            "cross_encoder" if self._cross_encoder_reranker is not None else "lightweight"
        )
        self._chat_model = self._build_chat_model(streaming=False)
        self._stream_model = self._build_chat_model(streaming=True)
        self._embedding_client = self._build_embedding_client()
        self._prepare_graph = self._compile_prepare_graph()

        if self.effective_timeout_sec != self.timeout_sec:
            logger.info(
                "Applied runtime timeout floor for provider %s: configured=%.1fs effective=%.1fs",
                self.provider_id or "unknown",
                self.timeout_sec,
                self.effective_timeout_sec,
            )

    def _load_integrations(self) -> Dict[str, Any]:
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "LangChain/LangGraph 依赖未安装，请先安装 requirements.txt 中新增依赖。"
            ) from exc

        return {
            "AIMessage": AIMessage,
            "HumanMessage": HumanMessage,
            "SystemMessage": SystemMessage,
            "ChatOpenAI": ChatOpenAI,
            "OpenAIEmbeddings": OpenAIEmbeddings,
            "START": START,
            "END": END,
            "StateGraph": StateGraph,
        }

    def _configure_langsmith(self) -> None:
        if not self.langsmith_enabled:
            return

        api_key = str(self.agent_cfg.get("langsmith_api_key") or "").strip()
        endpoint = str(self.agent_cfg.get("langsmith_endpoint") or "").strip()
        if api_key:
            os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        if endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = endpoint

    def _build_model_kwargs(self) -> Dict[str, Any]:
        model_kwargs: Dict[str, Any] = {}
        if self.reasoning_effort:
            model_kwargs["reasoning_effort"] = self.reasoning_effort
        if self.max_completion_tokens is not None:
            model_kwargs["max_completion_tokens"] = self.max_completion_tokens
        return model_kwargs

    def _resolve_effective_timeout_sec(self, configured_timeout_sec: float) -> float:
        if self.provider_id == "qwen":
            return max(float(configured_timeout_sec), _QWEN_RUNTIME_MIN_TIMEOUT_SEC)
        return float(configured_timeout_sec)

    def _build_chat_model(self, *, streaming: bool) -> Any:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "api_key": self.runtime_api_key,
            "base_url": self.base_url or None,
            "timeout": self.effective_timeout_sec,
            "max_retries": self.max_retries,
            "streaming": streaming,
            "model_kwargs": self._build_model_kwargs(),
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return self._imports["ChatOpenAI"](**kwargs)

    def _build_embedding_client(self) -> Optional[Any]:
        if not self.embedding_model:
            return None
        return self._imports["OpenAIEmbeddings"](
            model=self.embedding_model,
            api_key=self.runtime_api_key,
            base_url=self.base_url or None,
            request_timeout=self.timeout_sec,
            max_retries=self.max_retries,
        )

    def _build_cross_encoder_reranker(self) -> Optional[Any]:
        if self.retriever_rerank_mode not in {"auto", "cross_encoder"}:
            return None

        model_path = str(self.retriever_cross_encoder_model or "").strip()
        if not model_path:
            return None

        resolved_model_path = os.path.abspath(os.path.expanduser(model_path))
        if not os.path.exists(resolved_model_path):
            logger.warning(
                "Cross-Encoder 精排已跳过：本地模型路径不存在 %s",
                model_path,
            )
            return None

        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.info("Cross-Encoder 精排未启用：缺少 sentence-transformers 依赖")
            return None

        kwargs: Dict[str, Any] = {}
        if self.retriever_cross_encoder_device:
            kwargs["device"] = self.retriever_cross_encoder_device

        try:
            return CrossEncoder(resolved_model_path, **kwargs)
        except Exception as exc:
            logger.warning("Cross-Encoder 精排初始化失败: %s", exc)
            return None

    def _compile_prepare_graph(self) -> Any:
        graph = self._imports["StateGraph"](dict)
        graph.add_node("load_context", self._load_context_node)
        graph.add_node("build_prompt", self._build_prompt_node)
        graph.add_edge(self._imports["START"], "load_context")
        graph.add_edge("load_context", "build_prompt")
        graph.add_edge("build_prompt", self._imports["END"])
        return graph.compile()

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
        return lock

    def update_runtime_dependencies(self, dependencies: Optional[Dict[str, Any]]) -> None:
        self._runtime_dependencies = dict(dependencies or {})
        self._ensure_background_scheduler()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._refresh_background_backlog_stats())

    def _get_llm_condition(self) -> asyncio.Condition:
        if self._llm_condition is None:
            self._llm_condition = asyncio.Condition()
        return self._llm_condition

    def _update_llm_stats_locked(self) -> None:
        self._stats["foreground_active"] = self._foreground_active
        self._stats["foreground_waiters"] = self._foreground_waiters
        self._stats["background_active"] = self._background_active

    async def _acquire_llm_slot(self, priority: str) -> None:
        condition = self._get_llm_condition()
        normalized = "background" if str(priority or "").strip().lower() == "background" else "foreground"
        if normalized == "foreground":
            async with condition:
                self._foreground_waiters += 1
                self._update_llm_stats_locked()
                try:
                    await condition.wait_for(
                        lambda: self._background_active == 0
                        and self._foreground_active < self.llm_foreground_max_concurrency
                    )
                except Exception:
                    self._foreground_waiters = max(0, self._foreground_waiters - 1)
                    self._update_llm_stats_locked()
                    condition.notify_all()
                    raise
                self._foreground_waiters = max(0, self._foreground_waiters - 1)
                self._foreground_active += 1
                self._update_llm_stats_locked()
                condition.notify_all()
            return

        async with condition:
            await condition.wait_for(
                lambda: self._background_active == 0
                and self._foreground_active == 0
                and self._foreground_waiters == 0
            )
            self._background_active += 1
            self._update_llm_stats_locked()
            condition.notify_all()

    async def _release_llm_slot(self, priority: str) -> None:
        condition = self._get_llm_condition()
        normalized = "background" if str(priority or "").strip().lower() == "background" else "foreground"
        async with condition:
            if normalized == "foreground":
                self._foreground_active = max(0, self._foreground_active - 1)
            else:
                self._background_active = max(0, self._background_active - 1)
            self._update_llm_stats_locked()
            condition.notify_all()

    @staticmethod
    def _parse_batch_time(value: str) -> tuple[int, int]:
        text = str(value or "").strip()
        try:
            hour_text, minute_text = text.split(":", 1)
            hour = max(0, min(23, int(hour_text)))
            minute = max(0, min(59, int(minute_text)))
            return hour, minute
        except (TypeError, ValueError):
            return 4, 0

    def _compute_next_background_batch_at(self, now: Optional[datetime] = None) -> datetime:
        current = now or datetime.now()
        hour, minute = self._parse_batch_time(self.background_ai_batch_time)
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    def _ensure_background_scheduler(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._batch_scheduler_task is not None and not self._batch_scheduler_task.done():
            return
        self._batch_scheduler_task = loop.create_task(self._background_batch_scheduler_loop())

    async def _background_batch_scheduler_loop(self) -> None:
        try:
            while True:
                next_run_at = self._compute_next_background_batch_at()
                self._stats["next_background_batch_at"] = next_run_at.timestamp()
                delay_sec = max(0.1, (next_run_at - datetime.now()).total_seconds())
                await asyncio.sleep(delay_sec)
                await self._run_background_batch_once()
        except asyncio.CancelledError:
            raise

    async def _refresh_background_backlog_stats(self) -> None:
        memory = self._runtime_dependencies.get("memory")
        if memory is None or not hasattr(memory, "get_background_backlog_stats"):
            self._stats["background_backlog_count"] = 0
            self._stats["background_backlog_by_task"] = {}
            return
        try:
            stats = await memory.get_background_backlog_stats()
        except Exception as exc:
            logger.warning("Failed to load background backlog stats: %s", exc)
            return
        self._stats["background_backlog_count"] = int(stats.get("total", 0) or 0)
        self._stats["background_backlog_by_task"] = dict(stats.get("by_task_type") or {})

    async def _enqueue_background_backlog(
        self,
        *,
        chat_id: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if task_type not in _BACKGROUND_TASK_TYPES:
            return False
        memory = self._runtime_dependencies.get("memory")
        if memory is None or not hasattr(memory, "upsert_background_backlog"):
            logger.warning("Background backlog skipped [%s]: memory unavailable", task_type)
            return False
        await memory.upsert_background_backlog(chat_id, task_type, payload or {})
        await self._refresh_background_backlog_stats()
        return True

    async def schedule_export_rag_sync(self, *, force: bool = False) -> bool:
        return await self._enqueue_background_backlog(
            chat_id=_BACKGROUND_GLOBAL_CHAT_ID,
            task_type=_TASK_EXPORT_RAG_SYNC,
            payload={"force": bool(force)},
        )

    def _sort_background_backlog_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                _BACKGROUND_TASK_ORDER.get(str(item.get("task_type") or "").strip(), 999),
                int(item.get("updated_at") or 0),
                str(item.get("chat_id") or ""),
            ),
        )

    async def _run_background_batch_once(self) -> None:
        async with self._batch_lock:
            memory = self._runtime_dependencies.get("memory")
            if memory is None or not hasattr(memory, "list_background_backlog"):
                self._stats["last_background_batch"] = {
                    "success": False,
                    "reason": "memory_unavailable",
                    "completed": 0,
                    "failed": 0,
                    "started_at": time.time(),
                }
                return
            started_at = time.time()
            completed = 0
            failed = 0
            attempted: set[tuple[str, str]] = set()
            while True:
                items = await memory.list_background_backlog()
                pending = [
                    item
                    for item in self._sort_background_backlog_items(list(items or []))
                    if (
                        str(item.get("chat_id") or ""),
                        str(item.get("task_type") or ""),
                    ) not in attempted
                ]
                if not pending:
                    break
                for item in pending:
                    key = (
                        str(item.get("chat_id") or ""),
                        str(item.get("task_type") or ""),
                    )
                    attempted.add(key)
                    try:
                        should_delete = await self._execute_background_backlog_item(item)
                    except Exception as exc:
                        failed += 1
                        logger.warning("Background backlog task failed [%s]: %s", key, exc)
                        continue
                    if should_delete:
                        await memory.delete_background_backlog(*key)
                        completed += 1
                        await self._refresh_background_backlog_stats()
                    else:
                        failed += 1
            self._stats["last_background_batch"] = {
                "success": failed == 0,
                "completed": completed,
                "failed": failed,
                "started_at": started_at,
                "finished_at": time.time(),
            }
            await self._refresh_background_backlog_stats()

    async def _execute_background_backlog_item(self, item: Dict[str, Any]) -> bool:
        task_type = str(item.get("task_type") or "").strip()
        chat_id = str(item.get("chat_id") or "").strip()
        payload = item.get("payload") or {}
        if task_type == _TASK_EMOTION:
            return await self._execute_emotion_backlog(chat_id, payload)
        if task_type == _TASK_CONTACT_PROMPT:
            return await self._execute_contact_prompt_backlog(chat_id, payload)
        if task_type == _TASK_VECTOR_MEMORY:
            return await self._execute_vector_memory_backlog(chat_id, payload)
        if task_type == _TASK_FACTS:
            return await self._execute_facts_backlog(chat_id, payload)
        if task_type == _TASK_EXPORT_RAG_SYNC:
            return await self._execute_export_rag_sync_backlog(payload)
        return True

    @staticmethod
    def _should_use_reasoning_as_reply(chat_id: str) -> bool:
        return str(chat_id or "").strip().startswith("__")

    def _build_openai_compatible_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _serialize_prompt_messages_for_openai(self, prompt_messages: Iterable[Any]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for item in prompt_messages or []:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if content is None:
                continue
            serialized.append(
                {
                    "role": _detect_message_role(item),
                    "content": content,
                }
            )
        return serialized

    def _build_openai_compatible_payload(
        self,
        prepared: AgentPreparedRequest,
        *,
        stream: bool,
    ) -> Dict[str, Any]:
        return build_openai_chat_payload(
            model=self.model,
            messages=self._serialize_prompt_messages_for_openai(prepared.prompt_messages),
            stream=stream,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_completion_tokens=self.max_completion_tokens,
            reasoning_effort=self.reasoning_effort,
        )

    async def _invoke_openai_compatible_reply(
        self,
        prepared: AgentPreparedRequest,
    ) -> Any:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_openai_compatible_payload(prepared, stream=False)
        headers = self._build_openai_compatible_headers()
        max_attempts = max(1, int(self.max_retries) + 1)
        last_error: Optional[RuntimeError] = None

        async with httpx.AsyncClient(timeout=self.effective_timeout_sec) as client:
            for attempt in range(1, max_attempts + 1):
                response = None
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    return normalize_chat_result(response.json())
                except ValueError as exc:
                    normalized_error = normalize_provider_error(
                        exc=exc,
                        response=response,
                        payload=(response.text[:200] if response is not None else None),
                    )
                except Exception as exc:
                    normalized_error = normalize_provider_error(exc=exc, response=response)

                last_error = RuntimeError(normalized_error.message)
                should_retry = normalized_error.retryable and attempt < max_attempts
                logger.warning(
                    "Compat fallback request failed (%s/%s) [%s]: %s",
                    attempt,
                    max_attempts,
                    prepared.chat_id,
                    normalized_error.message,
                )
                if not should_retry:
                    raise last_error
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 1.5))

        raise last_error or RuntimeError("provider request failed")

    def _record_normalized_response_metadata(
        self,
        prepared: AgentPreparedRequest,
        normalized: Any,
    ) -> None:
        tool_calls = [
            {
                "id": item.id,
                "name": item.name,
                "arguments": item.arguments,
                "type": item.type,
            }
            for item in getattr(normalized, "tool_calls", []) or []
        ]
        if tool_calls:
            prepared.response_metadata["tool_calls"] = tool_calls
            prepared.response_metadata["tool_call_count"] = len(tool_calls)
        finish_reason = str(getattr(normalized, "finish_reason", "") or "").strip()
        if finish_reason:
            prepared.response_metadata["finish_reason"] = finish_reason

    @staticmethod
    def _summarize_reasoning_for_log(reasoning_text: str, limit: int = 240) -> str:
        compact = " ".join(str(reasoning_text or "").strip().split())
        if len(compact) <= limit:
            return compact
        return f"{compact[:limit]}..."

    def _log_reasoning_output(
        self,
        prepared: AgentPreparedRequest,
        reasoning_text: str,
        *,
        source: str,
    ) -> None:
        cleaned = str(reasoning_text or "").strip()
        if not cleaned:
            return
        prepared.response_metadata["has_reasoning_output"] = True
        logger.info(
            "Model reasoning captured [%s][%s]: %s",
            prepared.chat_id,
            source,
            self._summarize_reasoning_for_log(cleaned),
        )

    def _consume_normalized_reply(
        self,
        prepared: AgentPreparedRequest,
        normalized: Any,
        *,
        source: str,
    ) -> tuple[str, str]:
        self._record_normalized_response_metadata(prepared, normalized)
        reply_text = str(getattr(normalized, "text", "") or "").strip()
        reasoning_text = str(getattr(normalized, "reasoning", "") or "").strip()
        if reasoning_text:
            self._log_reasoning_output(prepared, reasoning_text, source=source)
        if not reply_text and reasoning_text and self._should_use_reasoning_as_reply(prepared.chat_id):
            reply_text = reasoning_text
            prepared.response_metadata["used_reasoning_content"] = True
        if not reply_text and getattr(normalized, "tool_calls", None):
            prepared.response_metadata["tool_call_only_response"] = True
        return reply_text, reasoning_text

    @staticmethod
    def _should_attempt_empty_reply_fallback(
        normalized: Any,
        *,
        reply_text: str,
        reasoning_text: str,
    ) -> bool:
        if reply_text or reasoning_text:
            return False
        return not bool(getattr(normalized, "tool_calls", None))

    async def probe(self) -> bool:
        human = self._imports["HumanMessage"]
        try:
            await self._chat_model.ainvoke([human(content="ping")])
            return True
        except Exception as exc:
            logger.warning("LangChain runtime 探测失败: %s", exc)
            return False

    async def prepare_request(
        self,
        *,
        event: Any,
        chat_id: str,
        user_text: str,
        dependencies: Dict[str, Any],
        image_path: Optional[str] = None,
    ) -> AgentPreparedRequest:
        self.update_runtime_dependencies(dependencies)
        start_ts = time.perf_counter()
        state = {
            "event": event,
            "chat_id": chat_id,
            "user_text": user_text,
            "dependencies": dependencies,
            "image_path": image_path,
        }
        final_state = await self._prepare_graph.ainvoke(state)
        timings = dict(final_state.get("timings") or {})
        timings["prepare_total_sec"] = round(time.perf_counter() - start_ts, 4)
        prepared = AgentPreparedRequest(
            chat_id=chat_id,
            user_text=user_text,
            system_prompt=str(final_state.get("system_prompt") or ""),
            prompt_messages=list(final_state.get("prompt_messages") or []),
            event=event,
            memory_context=list(final_state.get("memory_context") or []),
            user_profile=final_state.get("user_profile"),
            current_emotion=final_state.get("current_emotion"),
            timings=timings,
            trace=dict(final_state.get("trace") or {}),
            image_path=image_path,
        )
        skipped_context_steps = list(final_state.get("skipped_context_steps") or [])
        if skipped_context_steps:
            prepared.response_metadata["skipped_context_steps"] = skipped_context_steps
        prepared.response_metadata["prepare_budget_sec"] = timings.get(
            "load_context_budget_sec",
            round(self.prepare_soft_budget_sec, 4),
        )
        prepared.response_metadata["effective_timeout_sec"] = self.effective_timeout_sec
        if self.effective_timeout_sec != self.timeout_sec:
            prepared.response_metadata["timeout_fallback_applied"] = True
        self._stats["last_timings"] = dict(timings)
        return prepared

    async def invoke(self, prepared: AgentPreparedRequest) -> str:
        return await self._invoke_prepared(prepared, priority="foreground")

    async def _invoke_prepared(
        self,
        prepared: AgentPreparedRequest,
        *,
        priority: str,
    ) -> str:
        self._stats["requests"] += 1
        started = time.perf_counter()
        await self._acquire_llm_slot(priority)
        try:
            response = await self._chat_model.ainvoke(
                prepared.prompt_messages,
                config={
                    "tags": ["wechat-chat", "agent-runtime", "invoke"],
                    "metadata": {"chat_id": prepared.chat_id, "engine": "langgraph"},
                },
            )
            normalized = normalize_chat_result(response)
            final_normalized = normalized
            fallback_error: Optional[Exception] = None
            reply_text, reasoning_text = self._consume_normalized_reply(
                prepared,
                normalized,
                source="invoke",
            )
            if self._should_attempt_empty_reply_fallback(
                normalized,
                reply_text=reply_text,
                reasoning_text=reasoning_text,
            ):
                try:
                    fallback_normalized = await self._invoke_openai_compatible_reply(prepared)
                    fallback_reply_text, fallback_reasoning_text = self._consume_normalized_reply(
                        prepared,
                        fallback_normalized,
                        source="compat_fallback",
                    )
                    if fallback_reply_text or fallback_reasoning_text:
                        prepared.response_metadata["compat_fallback"] = "openai_chat_completions"
                        logger.warning(
                            "LangChain empty reply fallback hit [%s][provider=%s]",
                            prepared.chat_id,
                            self.provider_id or "unknown",
                        )
                        final_normalized = fallback_normalized
                        reply_text = fallback_reply_text
                        reasoning_text = fallback_reasoning_text
                except Exception as exc:
                    fallback_error = exc
                    prepared.response_metadata["compat_fallback_error"] = str(exc)
                    logger.warning(
                        "LangChain empty reply fallback failed [%s][provider=%s]: %s",
                        prepared.chat_id,
                        self.provider_id or "unknown",
                        exc,
                    )

            if not reply_text and getattr(final_normalized, "tool_calls", None):
                prepared.response_metadata["tool_call_only_response"] = True
            elif not reply_text:
                if fallback_error is not None:
                    prepared.response_metadata["compat_fallback_failed"] = True
                    prepared.timings["invoke_sec"] = round(time.perf_counter() - started, 4)
                    self._stats["last_timings"] = dict(prepared.timings)
                    return ""
                raise RuntimeError("LangChain returned empty content.")
            prepared.timings["invoke_sec"] = round(time.perf_counter() - started, 4)
            self._stats["successes"] += 1
            self._stats["last_timings"] = dict(prepared.timings)
            return reply_text
        except Exception:
            self._stats["failures"] += 1
            raise
        finally:
            await self._release_llm_slot(priority)

    async def stream_reply(self, prepared: AgentPreparedRequest) -> AsyncIterator[str]:
        reply_text = await self.invoke(prepared)
        if reply_text:
            yield reply_text

    async def finalize_request(
        self,
        prepared: AgentPreparedRequest,
        reply_text: str,
        dependencies: Dict[str, Any],
    ) -> None:
        self.update_runtime_dependencies(dependencies)
        memory = dependencies.get("memory")
        if memory:
            user_metadata = self._build_user_message_metadata(prepared)
            assistant_metadata = dict(prepared.response_metadata or {})
            await memory.add_messages(
                prepared.chat_id,
                [
                    {
                        "role": "user",
                        "content": prepared.user_text,
                        "metadata": user_metadata,
                    },
                    {
                        "role": "assistant",
                        "content": reply_text,
                        "metadata": assistant_metadata,
                    },
                ],
            )
        self._spawn_background(
            self._run_growth_pipeline(
                prepared=prepared,
                reply_text=reply_text,
                dependencies=dependencies,
            )
        )

    async def _run_growth_pipeline(
        self,
        *,
        prepared: AgentPreparedRequest,
        reply_text: str,
        dependencies: Dict[str, Any],
    ) -> None:
        memory = dependencies.get("memory")
        vector_memory = dependencies.get("vector_memory")
        export_rag = dependencies.get("export_rag")
        chat_id = prepared.chat_id

        self._stats["last_growth_error"] = ""
        logger.info(build_stage_log_message("GROWTH.START", chat_id=chat_id))

        user_profile = prepared.user_profile
        if memory and self.bot_cfg.get("personalization_enabled", False):
            try:
                next_count = await memory.increment_message_count(chat_id)
                snapshot = getattr(memory, "get_profile_prompt_snapshot", None)
                if callable(snapshot):
                    user_profile = await snapshot(chat_id)
                else:
                    user_profile = await memory.get_user_profile(chat_id)
                prepared.response_metadata["growth_message_count"] = next_count
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.FAILED",
                        chat_id=chat_id,
                        step="profile",
                        error=str(exc),
                    )
                )

        if memory and self.bot_cfg.get("emotion_detection_enabled", False):
            try:
                await self._enqueue_background_backlog(
                    chat_id=chat_id,
                    task_type=_TASK_EMOTION,
                    payload={"user_text": prepared.user_text},
                )
                logger.info(build_stage_log_message("GROWTH.EMOTION_DEFERRED", chat_id=chat_id))
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.EMOTION_FAILED",
                        chat_id=chat_id,
                        error=str(exc),
                    )
                )

        if memory is not None and self.bot_cfg.get("personalization_enabled", False):
            try:
                refreshed_profile = user_profile
                if refreshed_profile is None or self._should_refresh_contact_prompt(refreshed_profile):
                    refreshed_profile = await memory.get_user_profile(chat_id)
                if self._should_refresh_contact_prompt(refreshed_profile):
                    await self._enqueue_background_backlog(
                        chat_id=chat_id,
                        task_type=_TASK_CONTACT_PROMPT,
                        payload={
                            "user_text": prepared.user_text,
                            "reply_text": reply_text,
                            "base_prompt": self._resolve_contact_prompt_base(
                                prepared.event,
                                refreshed_profile,
                            ),
                        },
                    )
                    logger.info(
                        build_stage_log_message("GROWTH.CONTACT_PROMPT_DEFERRED", chat_id=chat_id)
                    )
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.CONTACT_PROMPT_FAILED",
                        chat_id=chat_id,
                        error=str(exc),
                    )
                )

        if vector_memory is not None and self.bot_cfg.get("rag_enabled", False):
            try:
                await self._enqueue_background_backlog(
                    chat_id=chat_id,
                    task_type=_TASK_VECTOR_MEMORY,
                    payload={
                        "user_text": prepared.user_text,
                        "reply_text": reply_text,
                    },
                )
                logger.info(build_stage_log_message("GROWTH.VECTOR_DEFERRED", chat_id=chat_id))
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.VECTOR_FAILED",
                        chat_id=chat_id,
                        error=str(exc),
                    )
                )

        if (
            memory is not None
            and user_profile is not None
            and self.bot_cfg.get("remember_facts_enabled", False)
            and self.background_fact_extraction_enabled
        ):
            try:
                await self._enqueue_background_backlog(
                    chat_id=chat_id,
                    task_type=_TASK_FACTS,
                    payload={
                        "user_text": prepared.user_text,
                        "assistant_reply": reply_text,
                    },
                )
                logger.info(build_stage_log_message("GROWTH.FACTS_DEFERRED", chat_id=chat_id))
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.FACTS_FAILED",
                        chat_id=chat_id,
                        error=str(exc),
                    )
                )

        if export_rag is not None and self.bot_cfg.get("export_rag_enabled", False):
            try:
                await self._enqueue_background_backlog(
                    chat_id=_BACKGROUND_GLOBAL_CHAT_ID,
                    task_type=_TASK_EXPORT_RAG_SYNC,
                    payload={"force": False},
                )
                logger.info(build_stage_log_message("GROWTH.EXPORT_RAG_DEFERRED", chat_id=chat_id))
            except Exception as exc:
                self._stats["last_growth_error"] = str(exc)
                logger.warning(
                    build_stage_log_message(
                        "GROWTH.EXPORT_RAG_FAILED",
                        chat_id=chat_id,
                        error=str(exc),
                    )
                )

    async def _execute_emotion_backlog(self, chat_id: str, payload: Dict[str, Any]) -> bool:
        memory = self._runtime_dependencies.get("memory")
        if memory is None or not self.bot_cfg.get("emotion_detection_enabled", False):
            return True
        text = str(payload.get("user_text") or "").strip()
        if not chat_id or not text:
            return True
        if self.emotion_fast_path_enabled:
            fast_result = detect_emotion_keywords(text)
            if fast_result and fast_result.emotion != "neutral":
                await memory.update_emotion(chat_id, fast_result.emotion)
                return True
        mode = str(self.bot_cfg.get("emotion_detection_mode", "keywords")).lower()
        if mode != "ai":
            emotion = detect_emotion_keywords(text)
        else:
            prompt = get_emotion_analysis_prompt(text)
            try:
                response = await self.generate_reply(
                    f"__emotion__{chat_id}",
                    prompt,
                    system_prompt="你是一个情感分析助手，只返回 JSON 格式的分析结果。",
                    priority="background",
                )
            except Exception as exc:
                logger.warning(
                    "emotion AI analysis failed; falling back to keyword mode [%s]: %s",
                    chat_id,
                    exc,
                )
                response = ""
            emotion = parse_emotion_ai_response(response) if response else None
            if emotion is None:
                emotion = detect_emotion_keywords(text)
        if emotion is not None:
            await memory.update_emotion(chat_id, emotion.emotion)
        return True

    async def _execute_contact_prompt_backlog(self, chat_id: str, payload: Dict[str, Any]) -> bool:
        memory = self._runtime_dependencies.get("memory")
        export_rag = self._runtime_dependencies.get("export_rag")
        if memory is None or not self.bot_cfg.get("personalization_enabled", False):
            return True
        if not chat_id:
            return True
        user_profile = await memory.get_user_profile(chat_id)
        if not self._should_refresh_contact_prompt(user_profile):
            return True
        user_text = str(payload.get("user_text") or "")
        reply_text = str(payload.get("reply_text") or "")
        base_prompt = str(payload.get("base_prompt") or "").strip()
        recent_context = await memory.get_recent_context(chat_id, limit=12)
        export_results: List[Dict[str, Any]] = []
        if export_rag is not None and self.bot_cfg.get("export_rag_enabled", False):
            export_results = await export_rag.search(
                self,
                chat_id,
                user_text or reply_text,
                priority="background",
            )
        existing_prompt = str(getattr(user_profile, "contact_prompt", "") or "").strip()
        profile_summary = str(getattr(user_profile, "profile_summary", "") or "").strip()
        context_facts = list(getattr(user_profile, "context_facts", []) or [])
        last_emotion = str(getattr(user_profile, "last_emotion", "") or "").strip()
        history_lines: List[str] = []
        for item in recent_context[-12:]:
            if not isinstance(item, dict):
                continue
            role = "用户" if str(item.get("role") or "").strip().lower() == "user" else "我方"
            content = str(item.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content[:180]}")
        export_lines = [
            str(item.get("text") or "").strip()
            for item in export_results[:4]
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        source = "recent_chat"
        if export_lines and history_lines:
            source = "hybrid"
        elif export_lines:
            source = "export_chat"
        prompt_request = "\n\n".join(
            part
            for part in [
                "请为这个联系人生成一份可直接作为 system prompt 使用的专属提示词。",
                "要求：保留“像主人本人在微信回复”的设定，不要写解释，不要写分析，只输出最终 prompt 正文。",
                f"当前全局/覆盖基底 Prompt：\n{base_prompt}",
                f"当前联系人已有 Prompt（如为空表示首次生成）：\n{existing_prompt or '（首次生成）'}",
                f"联系人画像摘要：\n{profile_summary or '（暂无）'}",
                f"最近情绪趋势：\n{last_emotion or 'neutral'}",
                "高置信事实：\n" + ("\n".join(f"- {fact}" for fact in context_facts[:8]) if context_facts else "（暂无）"),
                "近期真实对话：\n" + ("\n".join(history_lines) if history_lines else "（暂无）"),
                "导出聊天记录中的风格片段：\n" + ("\n".join(f"- {item}" for item in export_lines) if export_lines else "（暂无）"),
                "生成要求：\n"
                "1. 在当前 prompt 基础上增量更新，不要丢掉已有稳定规则。\n"
                "2. 明确该联系人的称呼、语气、边界、话题偏好和表达节奏。\n"
                "3. 如果已有人工编辑内容，要尽量保留其意图。\n"
                "4. 不要伪造事实，不要输出 markdown 标题，不要返回 JSON。",
            ]
            if part
        )
        generated = await self.generate_reply(
            f"__contact_prompt__{chat_id}",
            prompt_request,
            system_prompt="你是联系人专属 Prompt 生成器。你只输出可直接保存的最终 prompt 文本。",
            priority="background",
        )
        cleaned = self._strip_prompt_response(generated or "")
        if not cleaned:
            return True
        message_count = int(getattr(user_profile, "message_count", 0) or 0)
        await memory.save_contact_prompt(
            chat_id,
            cleaned,
            source=source,
            last_message_count=message_count,
        )
        return True

    async def _execute_vector_memory_backlog(self, chat_id: str, payload: Dict[str, Any]) -> bool:
        vector_memory = self._runtime_dependencies.get("vector_memory")
        if vector_memory is None or not self.bot_cfg.get("rag_enabled", False):
            return True
        user_text = str(payload.get("user_text") or "").strip()
        reply_text = str(payload.get("reply_text") or "").strip()
        if not chat_id or not user_text or not reply_text:
            return True
        user_embedding = await self.get_embedding(user_text, priority="background")
        reply_embedding = await self.get_embedding(reply_text, priority="background")
        timestamp = time.time()
        await asyncio.to_thread(
            vector_memory.add_text,
            user_text,
            {
                "chat_id": chat_id,
                "role": "user",
                "timestamp": timestamp,
                "source": "runtime_chat",
            },
            f"{chat_id}_u_{timestamp}",
            user_embedding,
        )
        await asyncio.to_thread(
            vector_memory.add_text,
            reply_text,
            {
                "chat_id": chat_id,
                "role": "assistant",
                "timestamp": timestamp,
                "source": "runtime_chat",
            },
            f"{chat_id}_a_{timestamp}",
            reply_embedding,
        )
        return True

    async def _execute_facts_backlog(self, chat_id: str, payload: Dict[str, Any]) -> bool:
        memory = self._runtime_dependencies.get("memory")
        if (
            memory is None
            or not self.bot_cfg.get("remember_facts_enabled", False)
            or not self.background_fact_extraction_enabled
        ):
            return True
        if not chat_id:
            return True
        user_profile = await memory.get_user_profile(chat_id)
        user_text = str(payload.get("user_text") or "")
        assistant_reply = str(payload.get("assistant_reply") or "")
        existing_facts = list(getattr(user_profile, "context_facts", []) or [])
        prompt = get_fact_extraction_prompt(user_text, assistant_reply, existing_facts)
        response = await self.generate_reply(
            f"__facts__{chat_id}",
            prompt,
            system_prompt="你是一个信息提取助手，只返回 JSON 格式的结果。",
            priority="background",
        )
        if not response:
            return True
        new_facts, relationship_hint, traits = parse_fact_extraction_response(response)
        if new_facts:
            max_facts = as_int(self.bot_cfg.get("max_context_facts", 20), 20, min_value=1)
            for fact in new_facts:
                await memory.add_context_fact(chat_id, fact, max_facts=max_facts)
        if traits:
            current_traits = str(getattr(user_profile, "personality", "") or "").strip()
            updated_traits = f"{current_traits} {','.join(traits)}".strip()
            if len(updated_traits) > 200:
                updated_traits = updated_traits[-200:]
            await memory.update_user_profile(chat_id, personality=updated_traits)
        msg_count = int(getattr(user_profile, "message_count", 0) or 0)
        current_rel = str(getattr(user_profile, "relationship", "unknown") or "unknown")
        new_rel = relationship_hint or get_relationship_evolution_hint(msg_count, current_rel)
        if new_rel and new_rel != current_rel:
            await memory.update_user_profile(chat_id, relationship=new_rel)
        return True

    async def _execute_export_rag_sync_backlog(self, payload: Dict[str, Any]) -> bool:
        export_rag = self._runtime_dependencies.get("export_rag")
        if export_rag is None or not self.bot_cfg.get("export_rag_enabled", False):
            return True
        result = await export_rag.sync(
            self,
            force=bool(payload.get("force", False)),
            priority="background",
        )
        return bool(result.get("success", True))

    async def get_embedding(
        self,
        text: str,
        *,
        priority: str = "foreground",
    ) -> Optional[List[float]]:
        query = str(text or "").strip()
        if not query or self._embedding_client is None:
            return None

        now = time.time()
        cached = self._embedding_cache.get(query)
        if cached and (self.embedding_cache_ttl_sec <= 0 or now - cached[0] < self.embedding_cache_ttl_sec):
            self._stats["embedding_cache_hits"] += 1
            return list(cached[1])

        pending = self._embedding_pending.get(query)
        if pending is not None:
            try:
                return await pending
            except Exception:
                return None

        self._stats["embedding_cache_misses"] += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._embedding_pending[query] = future
        try:
            await self._acquire_llm_slot(priority)
            try:
                vector = await self._embedding_client.aembed_query(query)
            finally:
                await self._release_llm_slot(priority)
            self._embedding_cache[query] = (now, list(vector))
            future.set_result(list(vector))
            return list(vector)
        except Exception as exc:
            future.set_exception(exc)
            logger.warning("Embedding 生成失败: %s", exc)
            return None
        finally:
            self._embedding_pending.pop(query, None)

    async def generate_reply(
        self,
        chat_id: str,
        user_text: str,
        system_prompt: Optional[str] = None,
        memory_context: Optional[Iterable[dict]] = None,
        image_path: Optional[str] = None,
        *,
        priority: str = "foreground",
    ) -> Optional[str]:
        prompt_messages = self._build_prompt_messages(
            system_prompt=system_prompt or "",
            memory_context=list(memory_context or []),
            user_text=user_text,
            image_path=image_path,
            event=None,
        )
        prepared = AgentPreparedRequest(
            chat_id=chat_id,
            user_text=user_text,
            system_prompt=system_prompt or "",
            prompt_messages=prompt_messages,
            memory_context=list(memory_context or []),
            image_path=image_path,
        )
        return await self._invoke_prepared(prepared, priority=priority)

    async def close(self) -> None:
        if self._batch_runner_task and not self._batch_runner_task.done():
            self._batch_runner_task.cancel()
            await asyncio.gather(self._batch_runner_task, return_exceptions=True)
        if self._batch_scheduler_task and not self._batch_scheduler_task.done():
            self._batch_scheduler_task.cancel()
            await asyncio.gather(self._batch_scheduler_task, return_exceptions=True)
        if self._background_tasks:
            tasks = list(self._background_tasks)
            done, pending = await asyncio.wait(tasks, timeout=2.0)
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            if done:
                await asyncio.gather(*done, return_exceptions=True)
            self._background_tasks.clear()

    def get_status(self) -> Dict[str, Any]:
        return {
            "engine": "langgraph",
            "graph_mode": self.graph_mode,
            "langsmith_enabled": self.langsmith_enabled,
            "langsmith_project": self.langsmith_project,
            "growth_mode": self._stats["growth_mode"],
            "growth_tasks_pending": len(self._background_tasks),
            "last_growth_error": self._stats["last_growth_error"],
            "foreground_active": self._stats["foreground_active"],
            "foreground_waiters": self._stats["foreground_waiters"],
            "background_active": self._stats["background_active"],
            "background_backlog_count": self._stats["background_backlog_count"],
            "background_backlog_by_task": dict(self._stats["background_backlog_by_task"]),
            "next_background_batch_at": self._stats["next_background_batch_at"],
            "last_background_batch": dict(self._stats["last_background_batch"]),
            "retriever_stats": {
                "top_k": self.retriever_top_k,
                "fetch_k": self.retriever_fetch_k,
                "score_threshold": self.retriever_score_threshold,
                "hits": self._stats["retriever_hits"],
                "rerank_mode": self.retriever_rerank_mode,
                "rerank_backend": self._rerank_backend,
                "cross_encoder_configured": bool(self.retriever_cross_encoder_model),
                "rerank_fallbacks": self._stats["retriever_rerank_fallbacks"],
            },
            "cache_stats": {
                "embedding_cache_size": len(self._embedding_cache),
                "embedding_cache_hits": self._stats["embedding_cache_hits"],
                "embedding_cache_misses": self._stats["embedding_cache_misses"],
            },
            "runtime_timings": dict(self._stats["last_timings"]),
        }

    def _remaining_prepare_budget(self, started: float) -> float:
        return max(0.0, self.prepare_soft_budget_sec - (time.perf_counter() - started))

    async def _resolve_context_task(
        self,
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

        remaining_budget = self._remaining_prepare_budget(started)
        if timeout_sec is not None:
            remaining_budget = min(remaining_budget, timeout_sec)
        if remaining_budget <= 0:
            skipped_context_steps.append(step_name)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None

        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=remaining_budget)
        except asyncio.TimeoutError:
            skipped_context_steps.append(step_name)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.info(
                "Skipping %s for reply budget [%s] after %.0f ms",
                step_name,
                step_name,
                remaining_budget * 1000,
            )
            return None
        except Exception as exc:
            logger.warning("%s [%s]: %s", warning_message, step_name, exc)
            return None

    async def _load_context_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        event = state["event"]
        chat_id = state["chat_id"]
        user_text = state["user_text"]
        dependencies = state.get("dependencies") or {}
        memory = dependencies.get("memory")

        started = time.perf_counter()
        memory_context: List[dict] = []
        short_term_preview: List[str] = []
        user_profile = None
        skipped_context_steps: List[str] = []
        context_task: Optional[asyncio.Task] = None
        profile_task: Optional[asyncio.Task] = None

        limit = as_int(self.bot_cfg.get("memory_context_limit", 5), 5, min_value=0)
        if memory and limit > 0:
            context_task = asyncio.create_task(memory.get_recent_context(chat_id, limit))
        if memory and self.bot_cfg.get("personalization_enabled", False):
            get_snapshot = getattr(memory, "get_profile_prompt_snapshot", None)
            if callable(get_snapshot):
                profile_task = asyncio.create_task(get_snapshot(chat_id))
            else:
                profile_task = asyncio.create_task(memory.get_user_profile(chat_id))

        context_result = await self._resolve_context_task(
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

        user_profile = await self._resolve_context_task(
            profile_task,
            step_name="user_profile",
            started=started,
            skipped_context_steps=skipped_context_steps,
            warning_message=f"用户画像加载失败 [{chat_id}]",
            timeout_sec=self.prepare_optional_timeout_sec,
        )

        timings = dict(state.get("timings") or {})
        timings["load_context_budget_sec"] = round(self.prepare_soft_budget_sec, 4)
        timings["load_context_sec"] = round(time.perf_counter() - started, 4)
        trace = {
            "context_summary": {
                "short_term_messages": len(memory_context),
                "short_term_preview": short_term_preview,
                "skipped_context_steps": list(skipped_context_steps),
                "growth_mode": "deferred_until_batch",
            },
            "profile": self._serialize_profile(user_profile),
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

    async def _build_prompt_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        system_prompt = resolve_system_prompt(
            state["event"],
            self.bot_cfg,
            state.get("user_profile"),
            state.get("current_emotion"),
            list(state.get("memory_context") or []),
        )
        prompt_messages = self._build_prompt_messages(
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

    def _build_prompt_messages(
        self,
        *,
        system_prompt: str,
        memory_context: List[dict],
        user_text: str,
        image_path: Optional[str],
        event: Any = None,
    ) -> List[Any]:
        system_message = self._imports["SystemMessage"]
        human_message = self._imports["HumanMessage"]
        ai_message = self._imports["AIMessage"]

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
            and self.bot_cfg.get("group_include_sender", True)
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

    def _should_refresh_profile(self, profile: Any) -> bool:
        frequency = as_int(self.bot_cfg.get("profile_update_frequency", 10), 10, min_value=1)
        message_count = as_int(getattr(profile, "message_count", 0), 0, min_value=0)
        return message_count <= 0 or ((message_count + 1) % frequency == 0)

    async def _search_runtime_memory(self, chat_id: str, user_text: str, vector_memory: Any) -> Optional[dict]:
        if not str(user_text or "").strip():
            return None

        embedding = await self.get_embedding(user_text)
        results = await asyncio.to_thread(
            vector_memory.search,
            query=user_text if not embedding else None,
            n_results=self.retriever_fetch_k,
            filter_meta={"chat_id": chat_id, "source": "runtime_chat"},
            query_embedding=embedding,
        )
        if not results:
            return None

        ranked_results = await self._rerank_runtime_results(user_text, results)
        lines: List[str] = []
        for item in ranked_results:
            distance = item.get("distance")
            if distance is not None and float(distance) > self.retriever_score_threshold:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            lines.append(text)
            if len(lines) >= self.retriever_top_k:
                break

        if not lines:
            return None

        self._stats["retriever_hits"] += len(lines)
        return {
            "role": "system",
            "content": "Relevant past memories:\n" + "\n".join(lines),
            "hit_count": len(lines),
            "trace_snippets": lines[:5],
        }

    async def _rerank_runtime_results(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self._cross_encoder_reranker is not None:
            try:
                ranked = await asyncio.to_thread(
                    self._rerank_runtime_results_cross_encoder,
                    query_text,
                    results,
                )
                self._rerank_backend = "cross_encoder"
                return ranked
            except Exception as exc:
                self._stats["retriever_rerank_fallbacks"] += 1
                self._rerank_backend = "lightweight"
                logger.warning("Cross-Encoder 精排失败，已回退轻量重排: %s", exc)

        self._rerank_backend = "lightweight"
        return self._rerank_runtime_results_lightweight(query_text, results)

    def _rerank_runtime_results_cross_encoder(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        reranker = self._cross_encoder_reranker
        if reranker is None:
            return self._rerank_runtime_results_lightweight(query_text, results)

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

    def _rerank_runtime_results_lightweight(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        query_tokens = self._tokenize_rerank_text(query_text)
        if not query_tokens:
            return list(results)

        ranked: List[Dict[str, Any]] = []
        for index, item in enumerate(results):
            text = str(item.get("text") or "").strip()
            if not text:
                continue

            candidate_tokens = self._tokenize_rerank_text(text)
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

    @staticmethod
    def _tokenize_rerank_text(text: str) -> set[str]:
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

    async def _analyze_emotion(self, chat_id: str, text: str) -> Optional[EmotionResult]:
        if self.emotion_fast_path_enabled:
            fast_result = detect_emotion_keywords(text)
            if fast_result and fast_result.emotion != "neutral":
                return fast_result

        mode = str(self.bot_cfg.get("emotion_detection_mode", "keywords")).lower()
        if mode != "ai":
            return detect_emotion_keywords(text)

        prompt = get_emotion_analysis_prompt(text)
        try:
            response = await self.generate_reply(
                f"__emotion__{chat_id}",
                prompt,
                system_prompt="你是一个情感分析助手，只返回 JSON 格式的分析结果。",
            )
        except Exception as exc:
            logger.warning("emotion AI analysis failed; falling back to keyword mode [%s]: %s", chat_id, exc)
            return detect_emotion_keywords(text)

        if not response:
            return detect_emotion_keywords(text)

        parsed = parse_emotion_ai_response(response)
        return parsed or detect_emotion_keywords(text)

    async def _update_vector_memory(
        self,
        chat_id: str,
        user_text: str,
        reply_text: str,
        vector_memory: Any,
    ) -> None:
        try:
            user_embedding = await self.get_embedding(user_text)
            reply_embedding = await self.get_embedding(reply_text)
            timestamp = time.time()
            await asyncio.to_thread(
                vector_memory.add_text,
                user_text,
                {
                    "chat_id": chat_id,
                    "role": "user",
                    "timestamp": timestamp,
                    "source": "runtime_chat",
                },
                f"{chat_id}_u_{timestamp}",
                user_embedding,
            )
            await asyncio.to_thread(
                vector_memory.add_text,
                reply_text,
                {
                    "chat_id": chat_id,
                    "role": "assistant",
                    "timestamp": timestamp,
                    "source": "runtime_chat",
                },
                f"{chat_id}_a_{timestamp}",
                reply_embedding,
            )
        except Exception as exc:
            logger.warning("向量记忆更新失败: %s", exc)

    @staticmethod
    def _serialize_emotion(emotion: Optional[EmotionResult]) -> Optional[Dict[str, Any]]:
        if emotion is None:
            return None
        if hasattr(emotion, "model_dump"):
            return emotion.model_dump()
        if hasattr(emotion, "dict"):
            return emotion.dict()
        return {
            "emotion": getattr(emotion, "emotion", "neutral"),
            "confidence": getattr(emotion, "confidence", 0.0),
            "intensity": getattr(emotion, "intensity", 1),
            "keywords_matched": list(getattr(emotion, "keywords_matched", []) or []),
            "suggested_tone": getattr(emotion, "suggested_tone", ""),
        }

    @staticmethod
    def _serialize_profile(profile: Any) -> Optional[Dict[str, Any]]:
        if profile is None:
            return None
        serialized = {
            "nickname": str(getattr(profile, "nickname", "") or ""),
            "relationship": str(getattr(profile, "relationship", "unknown") or "unknown"),
            "message_count": int(getattr(profile, "message_count", 0) or 0),
        }
        summary = str(getattr(profile, "profile_summary", "") or "").strip()
        if not summary and isinstance(profile, dict):
            summary = str(profile.get("profile_summary") or "").strip()
        if summary:
            serialized["profile_summary"] = summary
        contact_prompt_source = str(getattr(profile, "contact_prompt_source", "") or "").strip()
        if not contact_prompt_source and isinstance(profile, dict):
            contact_prompt_source = str(profile.get("contact_prompt_source") or "").strip()
        if contact_prompt_source:
            serialized["contact_prompt_source"] = contact_prompt_source
        return serialized

    def _should_refresh_contact_prompt(self, profile: Any) -> bool:
        if profile is None:
            return False
        cadence = as_int(
            self.bot_cfg.get(
                "contact_prompt_update_frequency",
                self.bot_cfg.get("profile_update_frequency", 10),
            ),
            10,
            min_value=1,
        )
        message_count_raw = (
            profile.get("message_count", 0)
            if isinstance(profile, dict)
            else getattr(profile, "message_count", 0)
        )
        message_count = int(message_count_raw or 0)
        if message_count < cadence:
            return False
        existing_prompt_raw = (
            profile.get("contact_prompt", "")
            if isinstance(profile, dict)
            else getattr(profile, "contact_prompt", "")
        )
        existing_prompt = str(existing_prompt_raw or "").strip()
        last_count_raw = (
            profile.get("contact_prompt_last_message_count", 0)
            if isinstance(profile, dict)
            else getattr(profile, "contact_prompt_last_message_count", 0)
        )
        last_count = int(last_count_raw or 0)
        if not existing_prompt:
            return True
        return (message_count - last_count) >= cadence

    def _resolve_contact_prompt_base(self, event: Any, user_profile: Any) -> str:
        overrides = self.bot_cfg.get("system_prompt_overrides") or {}
        chat_name = str(getattr(event, "chat_name", "") or "").strip()
        base_prompt = str(self.bot_cfg.get("system_prompt") or "").strip()
        if chat_name and chat_name in overrides:
            base_prompt = str(overrides.get(chat_name) or "").strip()
        existing_prompt = str(
            getattr(user_profile, "contact_prompt", "")
            if not isinstance(user_profile, dict)
            else user_profile.get("contact_prompt", "")
            or ""
        ).strip()
        return existing_prompt or base_prompt

    @staticmethod
    def _strip_prompt_response(text: str) -> str:
        cleaned = str(text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if "\n" in cleaned:
                _, _, cleaned = cleaned.partition("\n")
                cleaned = cleaned.strip()
        cleaned = cleaned.replace("\r\n", "\n").strip()
        return cleaned

    async def _refresh_contact_prompt_background(
        self,
        *,
        prepared: AgentPreparedRequest,
        user_profile: Any,
        memory: Any,
        export_rag: Any,
        reply_text: str,
    ) -> Optional[Dict[str, Any]]:
        chat_id = prepared.chat_id
        recent_context = await memory.get_recent_context(chat_id, limit=12)
        export_results: List[Dict[str, Any]] = []
        if export_rag is not None and self.bot_cfg.get("export_rag_enabled", False):
            export_results = await export_rag.search(
                self,
                chat_id,
                prepared.user_text or reply_text,
            )

        base_prompt = self._resolve_contact_prompt_base(prepared.event, user_profile)
        existing_prompt = str(getattr(user_profile, "contact_prompt", "") or "").strip()
        profile_summary = str(getattr(user_profile, "profile_summary", "") or "").strip()
        context_facts = list(getattr(user_profile, "context_facts", []) or [])
        last_emotion = str(getattr(user_profile, "last_emotion", "") or "").strip()

        history_lines: List[str] = []
        for item in recent_context[-12:]:
            if not isinstance(item, dict):
                continue
            role = "用户" if str(item.get("role") or "").strip().lower() == "user" else "我方"
            content = str(item.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content[:180]}")

        export_lines = [
            str(item.get("text") or "").strip()
            for item in export_results[:4]
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        source = "recent_chat"
        if export_lines and history_lines:
            source = "hybrid"
        elif export_lines:
            source = "export_chat"

        prompt_request = "\n\n".join(
            part
            for part in [
                "请为这个联系人生成一份可直接作为 system prompt 使用的专属提示词。",
                "要求：保留“像主人本人在微信回复”的设定，不要写解释，不要写分析，只输出最终 prompt 正文。",
                f"当前全局/覆盖基底 Prompt：\n{base_prompt}",
                f"当前联系人已有 Prompt（如为空表示首次生成）：\n{existing_prompt or '（首次生成）'}",
                f"联系人轻量画像摘要：\n{profile_summary or '（暂无）'}",
                f"最近情绪趋势：\n{last_emotion or 'neutral'}",
                "高置信事实：\n" + ("\n".join(f"- {fact}" for fact in context_facts[:8]) if context_facts else "（暂无）"),
                "近期真实对话：\n" + ("\n".join(history_lines) if history_lines else "（暂无）"),
                "导出聊天记录中的风格片段：\n" + ("\n".join(f"- {item}" for item in export_lines) if export_lines else "（暂无）"),
                "生成要求：\n"
                "1. 在当前 prompt 基础上增量更新，不要丢掉已有稳定规则。\n"
                "2. 明确该联系人适合的称呼、语气、边界、话题偏好和表达节奏。\n"
                "3. 如果已有人工编辑内容，要尽量保留其意图。\n"
                "4. 不要伪造事实，不要输出 markdown 标题，不要返回 JSON。",
            ]
            if part
        )
        generated = await self.generate_reply(
            f"__contact_prompt__{chat_id}",
            prompt_request,
            system_prompt="你是联系人专属 Prompt 生成器。你只输出可直接保存的最终 prompt 文本。",
        )
        cleaned = self._strip_prompt_response(generated or "")
        if not cleaned:
            return None

        message_count = int(getattr(user_profile, "message_count", 0) or 0)
        return await memory.save_contact_prompt(
            chat_id,
            cleaned,
            source=source,
            last_message_count=message_count,
        )

    @staticmethod
    def _build_user_message_metadata(prepared: AgentPreparedRequest) -> Dict[str, Any]:
        event = prepared.event
        if event is None:
            return {}
        raw_message_type = getattr(event, "msg_type", 0)
        message_type = str(raw_message_type or "").strip() or "0"
        metadata = {
            "kind": "incoming_message",
            "chat_name": str(getattr(event, "chat_name", "") or ""),
            "sender": str(getattr(event, "sender", "") or ""),
            "is_group": bool(getattr(event, "is_group", False)),
            "message_type": message_type,
            "emotion": dict(prepared.trace.get("emotion") or {}) or None,
        }
        try:
            metadata["message_type_code"] = int(raw_message_type)
        except (TypeError, ValueError):
            pass
        return metadata

    async def _extract_facts_background(
        self,
        chat_id: str,
        user_text: str,
        assistant_reply: str,
        user_profile: Any,
        memory: Any,
    ) -> None:
        if memory is None:
            return

        try:
            existing_facts = list(getattr(user_profile, "context_facts", []) or [])
            prompt = get_fact_extraction_prompt(user_text, assistant_reply, existing_facts)
            response = await self.generate_reply(
                f"__facts__{chat_id}",
                prompt,
                system_prompt="你是一个信息提取助手，只返回 JSON 格式的结果。",
            )
            if not response:
                return

            new_facts, relationship_hint, traits = parse_fact_extraction_response(response)
            if new_facts:
                max_facts = as_int(self.bot_cfg.get("max_context_facts", 20), 20, min_value=1)
                for fact in new_facts:
                    await memory.add_context_fact(chat_id, fact, max_facts=max_facts)

            if traits:
                current_traits = str(getattr(user_profile, "personality", "") or "").strip()
                updated_traits = f"{current_traits} {','.join(traits)}".strip()
                if len(updated_traits) > 200:
                    updated_traits = updated_traits[-200:]
                await memory.update_user_profile(chat_id, personality=updated_traits)

            msg_count = int(getattr(user_profile, "message_count", 0) or 0)
            current_rel = str(getattr(user_profile, "relationship", "unknown") or "unknown")
            new_rel = relationship_hint or get_relationship_evolution_hint(msg_count, current_rel)
            if new_rel and new_rel != current_rel:
                await memory.update_user_profile(chat_id, relationship=new_rel)
        except Exception as exc:
            logger.warning("事实提取后台任务失败: %s", exc)

    def _spawn_background(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
