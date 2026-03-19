"""
OpenAI 兼容 /chat/completions 的 AI 客户端封装。

本模块提供了一个轻量级的 OpenAI 兼容 API 客户端，支持：
- 同步和流式（SSE）响应
- 按会话管理对话历史
- 自动重试和退避策略
- Token 估算和历史裁剪

主要类:
    AIClient: 核心客户端类，封装了 API 调用和历史管理

使用示例:
    >>> client = AIClient(
    ...     base_url="https://api.openai.com/v1",
    ...     api_key="your-api-key",
    ...     model="gpt-4o-mini",
    ... )
    >>> reply = await client.generate_reply("chat_123", "你好！")

依赖:
    - httpx: 异步 HTTP 客户端（不依赖官方 OpenAI SDK）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict, deque
from functools import lru_cache
from threading import Lock
from typing import AsyncIterator, Deque, Dict, Iterable, List, Optional, Tuple

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

from .provider_compat import (
    build_openai_chat_payload,
    normalize_chat_result,
    normalize_provider_error,
)
from ..utils.common import as_optional_int, as_optional_str

try:
    import tiktoken
except Exception:  # pragma: no cover - 可选依赖
    tiktoken = None


# ═══════════════════════════════════════════════════════════════════════════════
#                               常量定义
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT_SEC = 60.0  # 默认超时时间（秒）；本地模型/推理模型可能需要更长时间
FAST_PROBE_TIMEOUT_SEC = 8.0
MAX_RETRIES = 2             # 最大重试次数

_tiktoken_encoder = None
_tiktoken_probe_done = False


def _is_internal_task_chat_id(chat_id: str) -> bool:
    # Internal augmentation tasks (emotion/facts/etc.) use a "__xxx__" prefix.
    return str(chat_id or "").startswith("__")


def _extract_text(value: object) -> str:
    """Extract human-readable text from OpenAI-compatible content payloads."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text).strip())
            elif item:
                parts.append(str(item).strip())
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


def _build_client_pool_signature(base_url: str, timeout_sec: float) -> str:
    """Build a stable pool key for compatible HTTP clients."""
    payload = {
        "base_url": str(base_url or "").strip().rstrip("/"),
        "timeout_sec": _coerce_timeout(timeout_sec),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


class AIClientPool:
    """Reference-counted shared HTTP client pool."""

    def __init__(self) -> None:
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._ref_count: Dict[str, int] = {}
        self._lock = Lock()

    def acquire(self, signature: str, *, timeout_sec: float) -> httpx.AsyncClient:
        timeout = _coerce_timeout(timeout_sec)
        with self._lock:
            client = self._clients.get(signature)
            if client is None or client.is_closed:
                client = httpx.AsyncClient(
                    timeout=timeout,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
                self._clients[signature] = client
                self._ref_count[signature] = 0
            self._ref_count[signature] = self._ref_count.get(signature, 0) + 1
            return client

    async def release(self, signature: Optional[str]) -> None:
        if not signature:
            return

        client_to_close: Optional[httpx.AsyncClient] = None
        with self._lock:
            current = self._ref_count.get(signature, 0)
            if current <= 1:
                self._ref_count.pop(signature, None)
                client_to_close = self._clients.pop(signature, None)
            else:
                self._ref_count[signature] = current - 1

        if client_to_close is not None and not client_to_close.is_closed:
            try:
                await client_to_close.aclose()
            except Exception:
                pass


_client_pool = AIClientPool()


def _is_cjk_char(code: int) -> bool:
    """
    判断字符码点是否为 CJK 字符。
    
    包括：中日韩统一表意文字、扩展区、平假名、片假名、韩语字母。
    """
    return (
        0x4e00 <= code <= 0x9fff    # CJK 统一表意文字基本区
        or 0x3400 <= code <= 0x4dbf  # CJK 扩展区 A
        or 0x3040 <= code <= 0x30ff  # 日语平假名和片假名
        or 0xac00 <= code <= 0xd7af  # 韩语字母
    )


# ═══════════════════════════════════════════════════════════════════════════════
#                               辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _coerce_timeout(value: float) -> float:
    """将超时值规范化到有效范围内。

    不设上限，允许本地大模型（Ollama）及推理模型（DeepSeek-R1）
    配置较长的超时时间。
    """
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = DEFAULT_TIMEOUT_SEC
    if val <= 0:
        val = DEFAULT_TIMEOUT_SEC
    return val


def _coerce_retries(value: int) -> int:
    """将重试次数规范化到有效范围内。"""
    try:
        val = int(value)
    except (TypeError, ValueError):
        val = MAX_RETRIES
    if val < 0:
        val = 0
    return min(val, MAX_RETRIES)


def _get_tiktoken_encoder():
    """获取可复用的 tiktoken 编码器。"""
    global _tiktoken_encoder, _tiktoken_probe_done
    if _tiktoken_probe_done:
        return _tiktoken_encoder

    _tiktoken_probe_done = True
    if tiktoken is None:
        return None

    try:
        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _tiktoken_encoder = None
    return _tiktoken_encoder


# ═══════════════════════════════════════════════════════════════════════════════
#                               AI 客户端类
# ═══════════════════════════════════════════════════════════════════════════════

class AIClient:
    """
    OpenAI 兼容聊天接口的轻量封装。
    
    该类管理会话历史、构建 API 请求、处理重试，
    并统一兼容不同 OpenAI-compatible 提供方的响应结构。
    
    Attributes:
        base_url (str): API 接口基础 URL
        api_key (str): API 密钥
        model (str): 模型名称
        model_alias (str): 模型别名（用于日志和回复后缀）
        timeout_sec (float): 请求超时时间（秒）
        max_retries (int): 最大重试次数
        context_rounds (int): 保留的对话轮数
        context_max_tokens (int | None): 上下文最大 token 数
        system_prompt (str): 系统提示词
        temperature (float | None): 生成温度
        max_tokens (int | None): 最大输出 token 数
        history_max_chats (int): 内存中最多保留的会话数
        history_ttl_sec (float | None): 会话历史过期时间
    """

    # 类级别的请求计数器（用于生成唯一请求 ID）
    _request_counter: int = 0
    _request_counter_lock = asyncio.Lock()

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_retries: int = MAX_RETRIES,
        context_rounds: int = 5,
        context_max_tokens: Optional[int] = None,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_completion_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        model_alias: Optional[str] = None,
        embedding_model: Optional[str] = None, # 新增
        history_max_chats: int = 200,
        history_ttl_sec: Optional[float] = 24 * 60 * 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # Do not enable embeddings implicitly for local presets without keys.
        value = "" if embedding_model is None else str(embedding_model).strip()
        self.embedding_model = value if value else None
        self.model_alias = model_alias or ""
        self.timeout_sec = _coerce_timeout(timeout_sec)
        self.max_retries = _coerce_retries(max_retries)
        self.context_rounds = context_rounds
        if context_max_tokens is None:
            self.context_max_tokens = None
        else:
            self.context_max_tokens = max(1, int(context_max_tokens))
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = as_optional_int(max_tokens)
        if self.max_tokens is not None and self.max_tokens <= 0:
            self.max_tokens = None
        self.max_completion_tokens = as_optional_int(max_completion_tokens)
        if self.max_completion_tokens is not None and self.max_completion_tokens <= 0:
            self.max_completion_tokens = None
        self.reasoning_effort = as_optional_str(reasoning_effort)
        self.history_max_chats = max(1, int(history_max_chats))
        if history_ttl_sec is None:
            self.history_ttl_sec = None
        else:
            self.history_ttl_sec = float(history_ttl_sec)
            if self.history_ttl_sec <= 0:
                self.history_ttl_sec = None

        self._histories: "OrderedDict[str, Deque[dict]]" = OrderedDict()
        self._history_timestamps: Dict[str, float] = {}
        self._chat_locks: Dict[str, asyncio.Lock] = {}
        
        # 请求去重：存储正在处理的请求 {(chat_id, user_text_hash): Future}
        self._pending_requests: Dict[Tuple[str, int], asyncio.Future] = {}
        
        # 请求统计
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "deduplicated_requests": 0,
        }
        self._client_pool_signature = _build_client_pool_signature(
            self.base_url, self.timeout_sec
        )
        self._http_client = _client_pool.acquire(
            self._client_pool_signature,
            timeout_sec=self.timeout_sec,
        )
        self._closed = False

    def _get_http_client(self) -> httpx.AsyncClient:
        signature = _build_client_pool_signature(self.base_url, self.timeout_sec)
        client = self._http_client
        if (
            client is None
            or client.is_closed
            or signature != self._client_pool_signature
        ):
            previous_signature = self._client_pool_signature
            self._http_client = _client_pool.acquire(
                signature,
                timeout_sec=self.timeout_sec,
            )
            self._client_pool_signature = signature
            self._closed = False
            if previous_signature and previous_signature != signature:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_client_pool.release(previous_signature))
                except RuntimeError:
                    pass
        return self._http_client

    @classmethod
    async def _next_request_id(cls) -> str:
        """生成下一个请求 ID（线程安全）。"""
        async with cls._request_counter_lock:
            cls._request_counter += 1
            return f"req-{cls._request_counter:06d}"

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
        return lock

    async def _probe_completion(self, *, timeout_sec: Optional[float] = None) -> bool:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        if self.max_completion_tokens is not None:
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = 1
        client = self._get_http_client()
        try:
            resp = await client.post(
                url,
                headers=self._build_headers(),
                json=payload,
                timeout=timeout_sec or self.timeout_sec,
            )
            if resp.status_code >= 400:
                logging.warning(
                    "探测失败（HTTP %s）：%s", resp.status_code, resp.text[:200]
                )
                return False
            try:
                data = resp.json()
            except ValueError:
                logging.warning("探测失败：返回内容不是 JSON。")
                return False
            if not data.get("choices"):
                logging.warning("探测失败：返回内容缺少 choices。")
                return False
            return True
        except Exception as exc:
            logging.warning("探测失败：%s", exc)
            return False

    async def probe(self) -> bool:
        """探测接口是否可用、模型是否可调用。"""
        return await self._probe_completion()

    async def probe_fast(self) -> Tuple[bool, str]:
        """快速探测服务联通性，必要时回退到一次极小的补全请求。"""
        client = self._get_http_client()
        timeout_sec = min(self.timeout_sec, FAST_PROBE_TIMEOUT_SEC)

        try:
            resp = await client.get(
                f"{self.base_url}/models",
                headers=self._build_headers(),
                timeout=timeout_sec,
            )
        except Exception as exc:
            logging.warning("快速探测失败：%s", exc)
            return False, "network"

        if resp.status_code == 200:
            try:
                payload = resp.json()
                if isinstance(payload, (dict, list)):
                    return True, "models"
            except ValueError:
                logging.info("模型列表探测返回非 JSON，回退到补全探测")

            ok = await self._probe_completion(timeout_sec=timeout_sec)
            return ok, "completion"

        if resp.status_code in {404, 405, 501}:
            ok = await self._probe_completion(timeout_sec=timeout_sec)
            return ok, "completion"

        logging.warning(
            "快速探测失败（HTTP %s）：%s", resp.status_code, resp.text[:200]
        )
        return False, "models"

    async def generate_reply(
        self,
        chat_id: str,
        user_text: str,
        system_prompt: Optional[str] = None,
        memory_context: Optional[Iterable[dict]] = None,
        image_path: Optional[str] = None,
    ) -> Optional[str]:
        """调用模型并返回回复文本，失败返回 None。"""
        # 请求去重
        req_key = (chat_id, user_text)
        if req_key in self._pending_requests:
            self._stats["deduplicated_requests"] += 1
            logging.info("检测到重复请求（%s），等待现有任务完成...", chat_id)
            try:
                return await self._pending_requests[req_key]
            except Exception as exc:
                logging.warning("等待重复请求结果失败: %s", exc)
                return None

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_requests[req_key] = future
        
        try:
            self._stats["total_requests"] += 1
            lock = self._get_chat_lock(chat_id)
            async with lock:
                messages = self._build_messages(
                    chat_id, user_text, system_prompt, memory_context, image_path
                )
                payload = build_openai_chat_payload(
                    model=self.model,
                    messages=messages,
                    stream=False,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    max_completion_tokens=self.max_completion_tokens,
                    reasoning_effort=self.reasoning_effort,
                )

                url = f"{self.base_url}/chat/completions"
                headers = self._build_headers()
                client = self._get_http_client()

                try:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(self.max_retries + 1),
                        wait=wait_exponential(multiplier=0.6, max=10),
                        retry=retry_if_exception_type(Exception),
                        reraise=True,
                    ):
                        with attempt:
                            try:
                                resp = await client.post(
                                    url, headers=headers, json=payload, timeout=self.timeout_sec
                                )
                                if resp.status_code >= 400:
                                    normalized_error = normalize_provider_error(response=resp)
                                    raise RuntimeError(normalized_error.message)

                                try:
                                    data = resp.json()
                                except ValueError as exc:
                                    normalized_error = normalize_provider_error(
                                        exc=exc,
                                        response=resp,
                                        payload=resp.text[:200],
                                    )
                                    raise RuntimeError(normalized_error.message) from exc
                                normalized = normalize_chat_result(data)
                                reply = normalized.text
                                if not reply and _is_internal_task_chat_id(chat_id):
                                    reply = normalized.reasoning
                                    if reply:
                                        logging.info(
                                            "AI content empty; using normalized reasoning for internal task (%s, len=%s)",
                                            chat_id,
                                            len(reply),
                                        )
                                if not reply:
                                    raise RuntimeError("AI 返回内容为空。")

                                self._append_history(chat_id, user_text, reply)
                                self._stats["successful_requests"] += 1
                                if not future.done():
                                    future.set_result(reply)
                                return reply
                            except Exception as exc:
                                logging.warning("AI 请求失败（第 %s 次）：%s", attempt.retry_state.attempt_number, exc)
                                raise exc

                except Exception as last_error:
                    logging.error("AI 请求多次失败：%s", last_error)
                    self._stats["failed_requests"] += 1
                    if not future.done():
                        future.set_result(None)
                    return None
        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            self._pending_requests.pop(req_key, None)

    async def generate_reply_stream(
        self,
        chat_id: str,
        user_text: str,
        system_prompt: Optional[str] = None,
        memory_context: Optional[Iterable[dict]] = None,
    ) -> Optional[AsyncIterator[str]]:
        """兼容旧接口：内部退化为单次调用并只产出一个分段。"""

        async def _stream() -> AsyncIterator[str]:
            reply = await self.generate_reply(
                chat_id,
                user_text,
                system_prompt=system_prompt,
                memory_context=memory_context,
            )
            if reply:
                yield reply

        return _stream()

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本 Embedding 向量"""
        # 请求去重
        # ... (可以使用类似 generate_reply 的去重逻辑，但 embedding 通常很快)
        if not self.embedding_model:
            return None
        
        try:
            url = f"{self.base_url}/embeddings"
            headers = self._build_headers()
            payload = {
                "model": self.embedding_model, # 使用配置的模型
                "input": text
            }
            
            client = self._get_http_client()
            resp = await client.post(
                url, headers=headers, json=payload, timeout=self.timeout_sec
            )
            
            if resp.status_code >= 400:
                logging.warning(f"Embedding failed: {resp.status_code} {resp.text[:100]}")
                return None
                
            data = resp.json()
            return data["data"][0]["embedding"]
            
        except Exception as e:
            logging.error(f"Embedding error: {e}")
            return None

    def _normalize_memory_context(
        self, memory_context: Optional[Iterable[dict]]
    ) -> List[dict]:
        if not memory_context:
            return []
        cleaned: List[dict] = []
        for msg in memory_context:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "") or "").strip().lower()
            content = msg.get("content")
            if not role or content is None:
                continue
            content = str(content).strip()
            if not content:
                continue
            if role not in ("user", "assistant", "system"):
                role = "user"
            cleaned.append({"role": role, "content": content})
        return cleaned

    def _build_messages(
        self,
        chat_id: str,
        user_text: str,
        system_prompt: Optional[str] = None,
        memory_context: Optional[Iterable[dict]] = None,
        image_path: Optional[str] = None,
    ) -> List[dict]:
        self._prune_histories()
        history = list(self._histories.get(chat_id, deque()))
        if history:
            self._touch_history(chat_id)
        prompt = self.system_prompt if system_prompt is None else system_prompt
        memory_messages = self._normalize_memory_context(memory_context)
        memory_header = None
        if memory_messages:
            memory_header = {
                "role": "system",
                "content": "Previous conversation memory (from local db):",
            }
        if self.context_max_tokens:
            prompt_tokens = 0
            if prompt:
                prompt_tokens = self._estimate_message_tokens(
                    {"role": "system", "content": prompt}
                )
            user_tokens = self._estimate_message_tokens(
                {"role": "user", "content": user_text}
            )
            budget = max(0, self.context_max_tokens - prompt_tokens - user_tokens)
            if memory_header:
                header_tokens = self._estimate_message_tokens(memory_header)
                budget = max(0, budget - header_tokens)
            if memory_messages:
                memory_messages = self._trim_history_by_tokens(
                    memory_messages, budget
                )
                memory_tokens = self._estimate_messages_tokens(memory_messages)
                budget = max(0, budget - memory_tokens)
            history = self._trim_history_by_tokens(history, budget)
        messages: List[dict] = []
        if prompt:
            messages.append({"role": "system", "content": prompt})
        if memory_messages:
            if memory_header:
                messages.append(memory_header)
            messages.extend(memory_messages)
        messages.extend(history)

        if image_path:
            # 引入图片处理
            from ..utils.image_processing import process_image_for_api
            
            base64_image = process_image_for_api(image_path)
            
            if base64_image:
                content_payload = [
                    {"type": "text", "text": user_text or "这张图片里有什么？"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
                messages.append({"role": "user", "content": content_payload})
            else:
                messages.append({"role": "user", "content": user_text})
        else:
            messages.append({"role": "user", "content": user_text})
        return messages

    def _append_history(self, chat_id: str, user_text: str, reply: str) -> None:
        max_messages = max(1, self.context_rounds) * 2
        history = self._histories.get(chat_id)
        if history is None or history.maxlen != max_messages:
            history = deque(history or [], maxlen=max_messages)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

        if self.context_max_tokens:
            trimmed = self._trim_history_by_tokens(list(history), self.context_max_tokens)
            history = deque(trimmed, maxlen=max_messages)

        self._histories[chat_id] = history
        self._touch_history(chat_id)
        self._prune_histories()

    def _touch_history(self, chat_id: str) -> None:
        if chat_id in self._histories:
            self._histories.move_to_end(chat_id)
        self._history_timestamps[chat_id] = time.time()

    def _prune_histories(self) -> None:
        if self.history_ttl_sec:
            cutoff = time.time() - self.history_ttl_sec
            expired = [
                chat_id
                for chat_id, ts in self._history_timestamps.items()
                if ts < cutoff
            ]
            for chat_id in expired:
                self._history_timestamps.pop(chat_id, None)
                self._histories.pop(chat_id, None)
                self._chat_locks.pop(chat_id, None)

        while len(self._histories) > self.history_max_chats:
            oldest_chat_id, _ = self._histories.popitem(last=False)
            self._history_timestamps.pop(oldest_chat_id, None)
            self._chat_locks.pop(oldest_chat_id, None)

    @staticmethod
    @lru_cache(maxsize=1024)
    def _estimate_text_tokens_cached(text: str) -> int:
        """
        估算文本的 token 数量（带缓存）。
        
        使用 LRU 缓存避免重复计算相同文本。
        """
        if not text:
            return 0
        
        # 使用生成器表达式计算 CJK 字符数，更内存高效
        cjk = sum(
            1 for ch in text
            if _is_cjk_char(ord(ch))
        )
        
        ascii_count = len(text) - cjk
        ascii_tokens = max(1, ascii_count // 4) if ascii_count > 0 else 0
        return cjk + ascii_tokens

    @staticmethod
    @lru_cache(maxsize=1024)
    def _estimate_text_tokens_precise_cached(text: str) -> Optional[int]:
        """
        使用 tiktoken 进行更精确的 token 估算。

        返回 None 表示当前环境不可用，调用方应回退到启发式算法。
        """
        if not text:
            return 0
        encoder = _get_tiktoken_encoder()
        if encoder is None:
            return None
        try:
            return len(encoder.encode(text, disallowed_special=()))
        except Exception:
            return None

    def _estimate_text_tokens(self, text: str) -> int:
        """估算文本的 token 数量。"""
        precise = self._estimate_text_tokens_precise_cached(text)
        if precise is not None:
            return precise
        return self._estimate_text_tokens_cached(text)

    def _estimate_message_tokens(self, message: dict) -> int:
        """估算单条消息的 token 数量（内容 + 元数据开销）。"""
        content = str(message.get("content", "") or "")
        return self._estimate_text_tokens(content) + 4

    def _estimate_messages_tokens(self, messages: List[dict]) -> int:
        return sum(self._estimate_message_tokens(msg) for msg in messages)

    def _trim_history_by_tokens(
        self, history: List[dict], max_tokens: int
    ) -> List[dict]:
        if not history or max_tokens <= 0:
            return []
        total = 0
        kept: List[dict] = []
        for msg in reversed(history):
            msg_tokens = self._estimate_message_tokens(msg)
            if total + msg_tokens > max_tokens and kept:
                break
            kept.append(msg)
            total += msg_tokens
            if total >= max_tokens:
                break
        return list(reversed(kept))

    def prune_histories(self) -> None:
        self._prune_histories()

    def get_history_stats(self) -> Dict[str, int]:
        total_messages = sum(len(history) for history in self._histories.values())
        total_tokens = sum(
            self._estimate_messages_tokens(list(history))
            for history in self._histories.values()
        )
        return {
            "chats": len(self._histories),
            "messages": total_messages,
            "tokens": total_tokens,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await _client_pool.release(self._client_pool_signature)
        self._http_client = None
