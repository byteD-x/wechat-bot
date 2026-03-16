from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

from ..schemas import EmotionResult
from ..utils.common import as_float, as_int
from ..utils.config import is_placeholder_key, resolve_system_prompt
from ..utils.image_processing import process_image_for_api
from .emotion import (
    detect_emotion_keywords,
    get_emotion_analysis_prompt,
    get_fact_extraction_prompt,
    get_relationship_evolution_hint,
    parse_emotion_ai_response,
    parse_fact_extraction_response,
)

logger = logging.getLogger(__name__)


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
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text).strip())
            elif item:
                parts.append(str(item).strip())
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _extract_reasoning_text(message: Any) -> str:
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        reasoning = additional_kwargs.get("reasoning_content") or additional_kwargs.get("reasoning")
        if reasoning:
            return str(reasoning).strip()

    if isinstance(message, dict):
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if reasoning:
            return str(reasoning).strip()

    reasoning = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
    return str(reasoning or "").strip()


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
        self.runtime_api_key = self.api_key or ("ollama" if self.allow_empty_key else None)
        self.model = str(settings.get("model") or "").strip()
        self.model_alias = str(settings.get("alias") or "").strip()
        self.provider_id = str(settings.get("provider_id") or "").strip().lower()
        embedding_model = str(settings.get("embedding_model") or "").strip()
        self.embedding_model = None if is_placeholder_key(embedding_model) else (embedding_model or None)
        self.timeout_sec = as_float(settings.get("timeout_sec", 10.0), 10.0, min_value=0.1)
        self.max_retries = as_int(settings.get("max_retries", 1), 1, min_value=0)
        self.temperature = settings.get("temperature")
        self.max_tokens = settings.get("max_tokens")
        self.max_completion_tokens = settings.get("max_completion_tokens")
        self.reasoning_effort = settings.get("reasoning_effort")

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

        self._chat_locks: Dict[str, asyncio.Lock] = {}
        self._embedding_cache: Dict[str, tuple[float, List[float]]] = {}
        self._embedding_pending: Dict[str, asyncio.Future] = {}
        self._background_tasks: set[asyncio.Task] = set()

        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "embedding_cache_hits": 0,
            "embedding_cache_misses": 0,
            "retriever_hits": 0,
            "retriever_rerank_fallbacks": 0,
            "last_timings": {},
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

    def _build_chat_model(self, *, streaming: bool) -> Any:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "api_key": self.runtime_api_key,
            "base_url": self.base_url or None,
            "timeout": self.timeout_sec,
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
        self._stats["last_timings"] = dict(timings)
        return prepared

    async def invoke(self, prepared: AgentPreparedRequest) -> str:
        self._stats["requests"] += 1
        started = time.perf_counter()
        try:
            response = await self._chat_model.ainvoke(
                prepared.prompt_messages,
                config={
                    "tags": ["wechat-chat", "agent-runtime", "invoke"],
                    "metadata": {"chat_id": prepared.chat_id, "engine": "langgraph"},
                },
            )
            reply_text = _extract_message_text(response)
            if not reply_text and self._should_use_reasoning_fallback(prepared.chat_id):
                reply_text = _extract_reasoning_text(response)
                if reply_text:
                    prepared.response_metadata["used_reasoning_content"] = True
            if not reply_text:
                raise RuntimeError("LangChain 返回空内容")
            prepared.timings["invoke_sec"] = round(time.perf_counter() - started, 4)
            self._stats["successes"] += 1
            self._stats["last_timings"] = dict(prepared.timings)
            return reply_text
        except Exception:
            self._stats["failures"] += 1
            raise

    async def stream_reply(self, prepared: AgentPreparedRequest) -> AsyncIterator[str]:
        self._stats["requests"] += 1
        started = time.perf_counter()
        try:
            async for chunk in self._stream_model.astream(
                prepared.prompt_messages,
                config={
                    "tags": ["wechat-chat", "agent-runtime", "stream"],
                    "metadata": {"chat_id": prepared.chat_id, "engine": "langgraph"},
                },
            ):
                text = _extract_message_text(chunk)
                if not text and self._should_use_reasoning_fallback(prepared.chat_id):
                    text = _extract_reasoning_text(chunk)
                    if text:
                        prepared.response_metadata["used_reasoning_content"] = True
                if text:
                    yield text
            prepared.timings["stream_sec"] = round(time.perf_counter() - started, 4)
            self._stats["successes"] += 1
            self._stats["last_timings"] = dict(prepared.timings)
        except Exception:
            self._stats["failures"] += 1
            raise

    async def finalize_request(
        self,
        prepared: AgentPreparedRequest,
        reply_text: str,
        dependencies: Dict[str, Any],
    ) -> None:
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
            if prepared.current_emotion:
                await memory.update_emotion(
                    prepared.chat_id, prepared.current_emotion.emotion
                )

        vector_memory = dependencies.get("vector_memory")
        if vector_memory is not None:
            self._spawn_background(
                self._update_vector_memory(
                    prepared.chat_id,
                    prepared.user_text,
                    reply_text,
                    vector_memory,
                )
            )

        if (
            prepared.user_profile is not None
            and self.bot_cfg.get("remember_facts_enabled", False)
            and self.background_fact_extraction_enabled
        ):
            self._spawn_background(
                self._extract_facts_background(
                    prepared.chat_id,
                    prepared.user_text,
                    reply_text,
                    prepared.user_profile,
                    memory,
                )
            )

    async def get_embedding(self, text: str) -> Optional[List[float]]:
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
            vector = await self._embedding_client.aembed_query(query)
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
        return await self.invoke(prepared)

    async def close(self) -> None:
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

    async def _load_context_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        event = state["event"]
        chat_id = state["chat_id"]
        user_text = state["user_text"]
        dependencies = state.get("dependencies") or {}
        memory = dependencies.get("memory")
        export_rag = dependencies.get("export_rag")
        vector_memory = dependencies.get("vector_memory")

        started = time.perf_counter()
        memory_context: List[dict] = []
        short_term_preview: List[str] = []
        user_profile = None
        current_emotion: Optional[EmotionResult] = None
        export_results: List[dict] = []
        runtime_memory_snippets: List[str] = []

        tasks: List[asyncio.Task] = []
        context_task: Optional[asyncio.Task] = None
        profile_task: Optional[asyncio.Task] = None
        counter_task: Optional[asyncio.Task] = None
        export_task: Optional[asyncio.Task] = None
        vector_task: Optional[asyncio.Task] = None
        emotion_task: Optional[asyncio.Task] = None

        limit = as_int(self.bot_cfg.get("memory_context_limit", 5), 5, min_value=0)
        if memory and limit > 0:
            context_task = asyncio.create_task(memory.get_recent_context(chat_id, limit))
            tasks.append(context_task)
        if memory and self.bot_cfg.get("personalization_enabled", False):
            profile_task = asyncio.create_task(memory.get_user_profile(chat_id))
            counter_task = asyncio.create_task(memory.increment_message_count(chat_id))
            tasks.extend([profile_task, counter_task])
        if export_rag is not None:
            export_task = asyncio.create_task(export_rag.search(self, chat_id, user_text))
            tasks.append(export_task)
        if vector_memory is not None and self.bot_cfg.get("rag_enabled", False):
            vector_task = asyncio.create_task(self._search_runtime_memory(chat_id, user_text, vector_memory))
            tasks.append(vector_task)
        if self.bot_cfg.get("emotion_detection_enabled", False):
            emotion_task = asyncio.create_task(self._analyze_emotion(chat_id, user_text))
            tasks.append(emotion_task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if context_task is not None and not context_task.cancelled():
            try:
                memory_context = list(context_task.result() or [])
                short_term_preview = [
                    str(item.get("content") or "").strip()
                    for item in memory_context[:3]
                    if isinstance(item, dict) and str(item.get("content") or "").strip()
                ]
            except Exception as exc:
                logger.warning("短期记忆加载失败 [%s]: %s", chat_id, exc)
        if profile_task is not None and not profile_task.cancelled():
            try:
                user_profile = profile_task.result()
            except Exception as exc:
                logger.warning("用户画像加载失败 [%s]: %s", chat_id, exc)
        if export_task is not None and not export_task.cancelled():
            try:
                export_results = export_task.result() or []
            except Exception as exc:
                logger.warning("导出语料检索失败 [%s]: %s", chat_id, exc)
                export_results = []
            export_message = export_rag.build_memory_message(export_results) if export_rag else None
            if export_message:
                memory_context.insert(0, export_message)
                self._stats["retriever_hits"] += len(export_results)
        if vector_task is not None and not vector_task.cancelled():
            try:
                rag_message = vector_task.result()
            except Exception as exc:
                logger.warning("运行记忆检索失败 [%s]: %s", chat_id, exc)
                rag_message = None
            if rag_message:
                memory_context.insert(0, rag_message)
                runtime_memory_snippets = list(rag_message.get("trace_snippets") or [])
        if emotion_task is not None and not emotion_task.cancelled():
            try:
                current_emotion = emotion_task.result()
            except Exception as exc:
                logger.warning("情绪分析失败 [%s]: %s", chat_id, exc)

        timings = dict(state.get("timings") or {})
        timings["load_context_sec"] = round(time.perf_counter() - started, 4)
        trace = {
            "context_summary": {
                "short_term_messages": len(memory_context),
                "short_term_preview": short_term_preview,
                "export_rag_hits": len(export_results),
                "export_rag_snippets": [
                    str(item.get("text") or "").strip()
                    for item in export_results[:3]
                    if isinstance(item, dict) and str(item.get("text") or "").strip()
                ],
                "runtime_memory_hits": len(runtime_memory_snippets),
                "runtime_memory_snippets": runtime_memory_snippets[:3],
            },
            "emotion": self._serialize_emotion(current_emotion),
            "profile": self._serialize_profile(user_profile),
        }
        return {
            "memory_context": memory_context,
            "user_profile": user_profile,
            "current_emotion": current_emotion,
            "timings": timings,
            "trace": trace,
            "event": event,
            "chat_id": chat_id,
            "user_text": user_text,
            "dependencies": dependencies,
            "image_path": state.get("image_path"),
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

    def _should_use_reasoning_fallback(self, chat_id: str) -> bool:
        normalized_chat_id = str(chat_id or "").strip()
        if normalized_chat_id.startswith("__"):
            return True
        if self.provider_id == "ollama":
            return True
        return "127.0.0.1:11434" in self.base_url or "localhost:11434" in self.base_url

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
        response = await self.generate_reply(
            f"__emotion__{chat_id}",
            prompt,
            system_prompt="你是一个情感分析助手，只返回 JSON 格式的分析结果。",
        )
        if not response:
            return detect_emotion_keywords(text)

        parsed = parse_emotion_ai_response(response)
        return parsed or detect_emotion_keywords(text)

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
        return {
            "nickname": str(getattr(profile, "nickname", "") or ""),
            "relationship": str(getattr(profile, "relationship", "unknown") or "unknown"),
            "message_count": int(getattr(profile, "message_count", 0) or 0),
        }

    @staticmethod
    def _build_user_message_metadata(prepared: AgentPreparedRequest) -> Dict[str, Any]:
        event = prepared.event
        if event is None:
            return {}
        return {
            "kind": "incoming_message",
            "chat_name": str(getattr(event, "chat_name", "") or ""),
            "sender": str(getattr(event, "sender", "") or ""),
            "is_group": bool(getattr(event, "is_group", False)),
            "message_type": int(getattr(event, "msg_type", 0) or 0),
            "emotion": dict(prepared.trace.get("emotion") or {}) or None,
        }

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
