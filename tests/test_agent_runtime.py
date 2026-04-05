import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.core.agent_runtime import AgentRuntime


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _ReasoningMessage:
    def __init__(self, content, reasoning_content):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning_content}


class _ReasoningBlockMessage:
    def __init__(self, text):
        self.content = [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": text}],
            }
        ]
        self.additional_kwargs = {}


class _ReasoningAndAnswerBlockMessage:
    def __init__(self, reasoning_text, answer_text):
        self.content = [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": reasoning_text}],
            },
            {
                "type": "text",
                "text": answer_text,
            },
        ]
        self.additional_kwargs = {}


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def ainvoke(self, messages, config=None):
        return _FakeMessage("ok")

    async def astream(self, messages, config=None):
        for chunk in ("he", "llo"):
            yield _FakeMessage(chunk)


class _FakeOpenAIEmbeddings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def aembed_query(self, query):
        return [float(len(query))]


class _FakeCompiledGraph:
    def __init__(self, nodes):
        self.nodes = nodes

    async def ainvoke(self, state):
        current = dict(state)
        for name in ("load_context", "build_prompt"):
            updates = await self.nodes[name](current)
            current.update(updates or {})
        return current


class _FakeStateGraph:
    def __init__(self, _state_type):
        self.nodes = {}

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, _src, _dst):
        return None

    def compile(self):
        return _FakeCompiledGraph(self.nodes)


class _DummyMemory:
    def __init__(self):
        self.saved_messages = []
        self.updated_emotion = None
        self.profile_updates = []
        self.context_facts = []
        self.profile_message_count = 3
        self.saved_contact_prompt = ""
        self.saved_contact_prompt_source = ""
        self.saved_contact_prompt_updated_at = 0
        self.saved_contact_prompt_last_message_count = 0
        self.background_backlog = {}
        self._backlog_updated_at = 0

    async def get_recent_context(self, chat_id, limit):
        return [{"role": "assistant", "content": "history reply"}]

    async def get_user_profile(self, chat_id):
        return SimpleNamespace(
            wx_id=chat_id,
            context_facts=["old fact"],
            personality="calm",
            relationship="unknown",
            message_count=self.profile_message_count,
            profile_summary="关系：普通朋友；偏好：直接一点；事实：喜欢猫",
            last_emotion="neutral",
            contact_prompt=self.saved_contact_prompt,
            contact_prompt_source=self.saved_contact_prompt_source,
            contact_prompt_updated_at=self.saved_contact_prompt_updated_at,
            contact_prompt_last_message_count=self.saved_contact_prompt_last_message_count,
        )

    async def increment_message_count(self, chat_id):
        self.profile_message_count += 1
        return self.profile_message_count

    async def get_profile_prompt_snapshot(self, chat_id):
        return {
            "wx_id": chat_id,
            "relationship": "unknown",
            "message_count": self.profile_message_count,
            "last_emotion": "neutral",
            "profile_summary": "关系：普通朋友；偏好：直接一点；事实：喜欢猫",
            "contact_prompt": self.saved_contact_prompt,
            "contact_prompt_source": self.saved_contact_prompt_source,
            "contact_prompt_updated_at": self.saved_contact_prompt_updated_at,
            "contact_prompt_last_message_count": self.saved_contact_prompt_last_message_count,
        }

    async def add_messages(self, chat_id, messages):
        self.saved_messages.append((chat_id, list(messages)))

    async def update_emotion(self, chat_id, emotion):
        self.updated_emotion = (chat_id, emotion)

    async def add_context_fact(self, chat_id, fact, max_facts=20):
        self.context_facts.append((chat_id, fact, max_facts))
        return None

    async def update_user_profile(self, chat_id, **fields):
        self.profile_updates.append((chat_id, dict(fields)))
        return None

    async def save_contact_prompt(self, chat_id, contact_prompt, *, source="user_edit", last_message_count=None):
        self.saved_contact_prompt = str(contact_prompt or "")
        self.saved_contact_prompt_source = str(source or "")
        self.saved_contact_prompt_updated_at = 1710000000
        self.saved_contact_prompt_last_message_count = int(last_message_count or 0)
        return {
            "chat_id": chat_id,
            "contact_prompt": self.saved_contact_prompt,
            "contact_prompt_source": self.saved_contact_prompt_source,
            "contact_prompt_updated_at": self.saved_contact_prompt_updated_at,
            "contact_prompt_last_message_count": self.saved_contact_prompt_last_message_count,
            "profile_summary": "关系：普通朋友；偏好：直接一点；事实：喜欢猫",
        }


    async def upsert_background_backlog(self, chat_id, task_type, payload=None):
        self._backlog_updated_at += 1
        self.background_backlog[(chat_id, task_type)] = {
            "chat_id": chat_id,
            "task_type": task_type,
            "payload": dict(payload or {}),
            "updated_at": self._backlog_updated_at,
        }

    async def list_background_backlog(self, limit=None):
        items = sorted(self.background_backlog.values(), key=lambda item: int(item["updated_at"]))
        if limit is not None:
            items = items[:limit]
        return [dict(item) for item in items]

    async def delete_background_backlog(self, chat_id, task_type):
        self.background_backlog.pop((chat_id, task_type), None)

    async def get_background_backlog_stats(self):
        by_task_type = {}
        latest_updated_at = 0
        for item in self.background_backlog.values():
            by_task_type[item["task_type"]] = by_task_type.get(item["task_type"], 0) + 1
            latest_updated_at = max(latest_updated_at, int(item["updated_at"]))
        return {
            "total": len(self.background_backlog),
            "by_task_type": by_task_type,
            "latest_updated_at": latest_updated_at,
        }


class _DummyExportRag:
    async def search(
        self,
        ai_client,
        chat_id,
        query_text,
        *,
        chat_id_aliases=None,
        priority="foreground",
    ):
        return [{"text": "style snippet"}]

    def build_memory_message(self, results):
        return {"role": "system", "content": "style snippet"}

    def __init__(self):
        self.sync_calls = 0

    async def sync(self, ai_client, force=False, *, priority="foreground"):
        self.sync_calls += 1
        return {"success": True, "synced": True, "force": force, "priority": priority}


class _SlowProfileMemory(_DummyMemory):
    async def get_profile_prompt_snapshot(self, chat_id):
        await asyncio.sleep(0.2)
        return await super().get_profile_prompt_snapshot(chat_id)


class _SlowExportRag(_DummyExportRag):
    async def search(
        self,
        ai_client,
        chat_id,
        query_text,
        *,
        chat_id_aliases=None,
        priority="foreground",
    ):
        await asyncio.sleep(0.2)
        return await super().search(
            ai_client,
            chat_id,
            query_text,
            chat_id_aliases=chat_id_aliases,
            priority=priority,
        )


class _DummyVectorMemory:
    def __init__(self):
        self.inserted = []

    def search(self, query=None, n_results=5, filter_meta=None, query_embedding=None):
        return [{"text": "runtime memory", "distance": 0.2}]

    def add_text(self, text, metadata, id, embedding=None):
        self.inserted.append(
            {
                "text": text,
                "metadata": metadata,
                "id": id,
                "embedding": embedding,
            }
        )


class _CrossEncoderVectorMemory:
    def search(self, query=None, n_results=5, filter_meta=None, query_embedding=None):
        return [
            {"text": "irrelevant chatter", "distance": 0.05},
            {"text": "tonight release plan and rollback steps", "distance": 0.35},
        ]


class _FakeCrossEncoder:
    def predict(self, pairs):
        scores = []
        for query, text in pairs:
            if "release plan" in query and "release plan" in text:
                scores.append(0.98)
            else:
                scores.append(0.05)
        return scores


def _fake_integrations(self):
    return {
        "AIMessage": _FakeMessage,
        "HumanMessage": _FakeMessage,
        "SystemMessage": _FakeMessage,
        "ChatOpenAI": _FakeChatOpenAI,
        "OpenAIEmbeddings": _FakeOpenAIEmbeddings,
        "START": "__start__",
        "END": "__end__",
        "StateGraph": _FakeStateGraph,
    }


@pytest.mark.asyncio
async def test_agent_runtime_prepare_request_aggregates_context(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    class _UnexpectedExportRag(_DummyExportRag):
        async def search(self, ai_client, chat_id, query_text):
            raise AssertionError("prepare_request 不应再执行实时 export_rag.search")

    class _UnexpectedVectorMemory(_DummyVectorMemory):
        def search(self, query=None, n_results=5, filter_meta=None, query_embedding=None):
            raise AssertionError("prepare_request 不应再执行实时 runtime_rag.search")

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "system_prompt": "base prompt\n{user_profile}",
            "memory_context_limit": 5,
            "personalization_enabled": True,
            "profile_inject_in_prompt": True,
            "emotion_detection_enabled": False,
            "rag_enabled": True,
            "remember_facts_enabled": True,
        },
        agent_cfg={"enabled": True},
    )

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Alice", sender="User", content="hello"),
        chat_id="friend:alice",
        user_text="hello",
        dependencies={
            "memory": _DummyMemory(),
            "export_rag": _UnexpectedExportRag(),
            "vector_memory": _UnexpectedVectorMemory(),
        },
    )

    assert "base prompt" in prepared.system_prompt
    assert "关系：普通朋友；偏好：直接一点；事实：喜欢猫" in prepared.system_prompt
    assert prepared.memory_context == [{"role": "assistant", "content": "history reply"}]
    assert prepared.trace["context_summary"]["growth_mode"] == "deferred_until_batch"
    assert len(prepared.prompt_messages) >= 2


@pytest.mark.asyncio
async def test_agent_runtime_prepare_request_skips_slow_optional_context_steps(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "reply_deadline_sec": 0.4,
            "memory_context_limit": 5,
            "personalization_enabled": True,
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
            "rag_enabled": False,
        },
        agent_cfg={"enabled": True},
    )

    async def _slow_emotion(_chat_id, _text):
        await asyncio.sleep(0.2)
        return None

    monkeypatch.setattr(runtime, "_analyze_emotion", _slow_emotion)

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Alice", sender="User", content="hello"),
        chat_id="friend:alice",
        user_text="hello",
        dependencies={
            "memory": _SlowProfileMemory(),
            "export_rag": _SlowExportRag(),
            "vector_memory": None,
        },
    )

    skipped = prepared.response_metadata.get("skipped_context_steps") or []
    assert "recent_context" not in skipped
    assert "user_profile" in skipped
    assert "export_rag" not in skipped
    assert "emotion" not in skipped
    await runtime.close()


@pytest.mark.asyncio
async def test_agent_runtime_embedding_cache_hits(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={},
        agent_cfg={"enabled": True, "embedding_cache_ttl_sec": 300},
    )

    first = await runtime.get_embedding("hello")
    second = await runtime.get_embedding("hello")

    assert first == [5.0]
    assert second == [5.0]
    status = runtime.get_status()
    assert status["cache_stats"]["embedding_cache_hits"] == 1
    assert status["cache_stats"]["embedding_cache_misses"] == 1


@pytest.mark.asyncio
async def test_agent_runtime_emotion_ai_failure_falls_back_to_keywords(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
        },
        bot_cfg={
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
        },
        agent_cfg={"enabled": True},
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("LangChain 返回空内容")

    monkeypatch.setattr(runtime, "generate_reply", _boom)
    emotion = await runtime._analyze_emotion("friend:alice", "hello")
    assert emotion is not None
    assert emotion.emotion == "neutral"


@pytest.mark.asyncio
async def test_agent_runtime_emotion_ai_uses_reasoning_content_when_content_empty(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
        },
        bot_cfg={
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
        },
        agent_cfg={"enabled": True},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningMessage(
            "",
            '{"emotion":"happy","confidence":0.9,"intensity":4,"suggested_tone":"light"}',
        )

    runtime._chat_model.ainvoke = _ainvoke

    emotion = await runtime._analyze_emotion("friend:alice", "hello")
    assert emotion is not None
    assert emotion.emotion == "happy"


@pytest.mark.asyncio
async def test_agent_runtime_emotion_ai_uses_reasoning_summary_blocks_when_content_empty(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
        },
        bot_cfg={
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
        },
        agent_cfg={"enabled": True},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningBlockMessage(
            '{"emotion":"sad","confidence":0.8,"intensity":3,"suggested_tone":"gentle"}'
        )

    runtime._chat_model.ainvoke = _ainvoke

    emotion = await runtime._analyze_emotion("friend:alice", "hello")
    assert emotion is not None
    assert emotion.emotion == "sad"


@pytest.mark.asyncio
async def test_agent_runtime_invoke_prefers_visible_answer_over_reasoning_for_user_reply(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningAndAnswerBlockMessage("这是推理摘要", "这是最终回答")

    runtime._chat_model.ainvoke = _ainvoke

    reply = await runtime.invoke(prepared)

    assert reply == "这是最终回答"
    assert prepared.response_metadata["has_reasoning_output"] is True
    assert prepared.response_metadata.get("used_reasoning_content") is not True


@pytest.mark.asyncio
async def test_agent_runtime_applies_qwen_timeout_floor(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-qwen",
            "model": "qwen3.5-flash",
            "provider_id": "qwen",
            "timeout_sec": 10,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )

    prepared = await runtime.prepare_request(
        event=None,
        chat_id="friend:alice",
        user_text="hello",
        dependencies={},
    )

    assert runtime.timeout_sec == 10.0
    assert runtime.effective_timeout_sec == 15.0
    assert runtime._chat_model.kwargs["timeout"] == 15.0
    assert prepared.response_metadata["effective_timeout_sec"] == 15.0
    assert prepared.response_metadata["timeout_fallback_applied"] is True


@pytest.mark.asyncio
async def test_agent_runtime_keeps_non_qwen_timeout(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "provider_id": "openai",
            "timeout_sec": 9,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )

    prepared = await runtime.prepare_request(
        event=None,
        chat_id="friend:alice",
        user_text="hello",
        dependencies={},
    )

    assert runtime.effective_timeout_sec == 9.0
    assert runtime._chat_model.kwargs["timeout"] == 9.0
    assert prepared.response_metadata["effective_timeout_sec"] == 9.0
    assert "timeout_fallback_applied" not in prepared.response_metadata


@pytest.mark.asyncio
async def test_agent_runtime_invoke_uses_reasoning_content_for_internal_task(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="__emotion__friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningMessage("", "这是通过 reasoning_content 返回的结构化结果")

    runtime._chat_model.ainvoke = _ainvoke

    reply = await runtime.invoke(prepared)

    assert reply == "这是通过 reasoning_content 返回的结构化结果"
    assert prepared.response_metadata["has_reasoning_output"] is True
    assert prepared.response_metadata["used_reasoning_content"] is True


@pytest.mark.asyncio
async def test_agent_runtime_invoke_falls_back_to_openai_compatible_reply_when_langchain_empty(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-v3.2:cloud",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _FakeMessage("")

    async def _fallback(prepared_request):
        return SimpleNamespace(
            text="fallback reply",
            reasoning="",
            tool_calls=[],
            finish_reason="stop",
        )

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr(runtime, "_invoke_openai_compatible_reply", _fallback)

    reply = await runtime.invoke(prepared)

    assert reply == "fallback reply"
    assert prepared.response_metadata["compat_fallback"] == "openai_chat_completions"
    assert prepared.response_metadata["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_agent_runtime_invoke_falls_back_to_openai_compatible_reply_when_langchain_raises_for_ollama(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-v3.2:cloud",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        raise RuntimeError("ollama handshake timeout")

    async def _fallback(prepared_request):
        return SimpleNamespace(
            text="fallback after exception",
            reasoning="",
            tool_calls=[],
            finish_reason="stop",
        )

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr(runtime, "_invoke_openai_compatible_reply", _fallback)

    reply = await runtime.invoke(prepared)

    assert reply == "fallback after exception"
    assert prepared.response_metadata["compat_fallback"] == "openai_chat_completions"
    assert prepared.response_metadata["compat_fallback_trigger"] == "langchain_exception"
    assert prepared.response_metadata["langchain_invoke_error"] == "ollama handshake timeout"


@pytest.mark.asyncio
async def test_agent_runtime_invoke_records_tool_call_only_response(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "test-model",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup_weather", "arguments": {"city": "Shanghai"}},
                }
            ],
            "finish_reason": "tool_calls",
        }

    runtime._chat_model.ainvoke = _ainvoke

    reply = await runtime.invoke(prepared)

    assert reply == ""
    assert prepared.response_metadata["tool_call_only_response"] is True
    assert prepared.response_metadata["tool_call_count"] == 1
    assert prepared.response_metadata["tool_calls"][0]["name"] == "lookup_weather"


@pytest.mark.asyncio
async def test_agent_runtime_invoke_does_not_fallback_for_tool_call_only_response(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "test-model",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup_weather", "arguments": {"city": "Shanghai"}},
                }
            ],
            "finish_reason": "tool_calls",
        }

    async def _unexpected_fallback(prepared_request):
        raise AssertionError("tool-call-only 响应不应触发兼容回退")

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr(runtime, "_invoke_openai_compatible_reply", _unexpected_fallback)

    reply = await runtime.invoke(prepared)

    assert reply == ""
    assert prepared.response_metadata["tool_call_only_response"] is True


@pytest.mark.asyncio
async def test_agent_runtime_invoke_raises_when_fallback_is_still_empty(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-v3.2:cloud",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _FakeMessage("")

    async def _fallback(prepared_request):
        return SimpleNamespace(
            text="",
            reasoning="",
            tool_calls=[],
            finish_reason="stop",
        )

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr(runtime, "_invoke_openai_compatible_reply", _fallback)

    with pytest.raises(RuntimeError, match="LangChain returned empty content"):
        await runtime.invoke(prepared)

    assert "compat_fallback" not in prepared.response_metadata


@pytest.mark.asyncio
async def test_agent_runtime_invoke_downgrades_fallback_timeout_to_empty_reply(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-v3.2:cloud",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _FakeMessage("")

    async def _fallback(prepared_request):
        raise RuntimeError("compat timeout")

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr(runtime, "_invoke_openai_compatible_reply", _fallback)

    reply = await runtime.invoke(prepared)

    assert reply == ""
    assert prepared.response_metadata["compat_fallback_failed"] is True
    assert prepared.response_metadata["compat_fallback_error"] == "compat timeout"


@pytest.mark.asyncio
async def test_agent_runtime_probe_falls_back_to_compat_for_ollama(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-v3.2:cloud",
            "provider_id": "ollama",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )

    async def _ainvoke(messages, config=None):
        raise RuntimeError("langchain probe failed")

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": ""}}]}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            return _FakeResponse()

    runtime._chat_model.ainvoke = _ainvoke
    monkeypatch.setattr("backend.core.agent_runtime.httpx.AsyncClient", _FakeAsyncClient)

    ok = await runtime.probe()

    assert ok is True


@pytest.mark.asyncio
async def test_agent_runtime_anthropic_native_invokes_messages_endpoint(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "anthropic-test-key",
            "model": "claude-sonnet-4-5",
            "provider_id": "anthropic",
            "auth_transport": "anthropic_native",
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello anthropic")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )
    observed = {}

    class _FakeResponse:
        status_code = 200
        text = '{"type":"message"}'

        def json(self):
            return {
                "type": "message",
                "content": [{"type": "text", "text": "anthropic reply"}],
                "stop_reason": "end_turn",
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            observed["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            observed["url"] = url
            observed["headers"] = headers
            observed["json"] = json
            return _FakeResponse()

    monkeypatch.setattr("backend.core.agent_runtime.httpx.AsyncClient", _FakeAsyncClient)

    reply = await runtime.invoke(prepared)

    assert reply == "anthropic reply"
    assert observed["url"].endswith("/messages")
    assert observed["headers"]["x-api-key"] == "anthropic-test-key"
    assert observed["headers"]["anthropic-version"] == "2023-06-01"
    assert observed["json"]["messages"][0]["content"][0]["text"] == "hello anthropic"
    assert prepared.response_metadata["finish_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_agent_runtime_anthropic_native_refreshes_auth_on_401(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    auth_state = {"api_key": "anthropic-stale-key", "refresh_calls": 0}

    def _refresh_auth():
        auth_state["refresh_calls"] += 1
        auth_state["api_key"] = "anthropic-fresh-key"

    runtime = AgentRuntime(
        settings={
            "base_url": "https://api.anthropic.com/v1",
            "api_key": lambda: auth_state["api_key"],
            "model": "claude-sonnet-4-5",
            "provider_id": "anthropic",
            "auth_transport": "anthropic_native",
            "auth_refresh_hook": _refresh_auth,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("refresh claude")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )
    observed = []

    class _UnauthorizedResponse:
        status_code = 401
        text = '{"error":"expired"}'

        def json(self):
            return {"error": "expired"}

    class _SuccessResponse:
        status_code = 200
        text = '{"type":"message"}'

        def json(self):
            return {
                "type": "message",
                "content": [{"type": "text", "text": "anthropic refreshed"}],
                "stop_reason": "end_turn",
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            self.calls += 1
            observed.append({"url": url, "headers": headers, "json": json})
            if self.calls == 1:
                return _UnauthorizedResponse()
            return _SuccessResponse()

    monkeypatch.setattr("backend.core.agent_runtime.httpx.AsyncClient", _FakeAsyncClient)

    reply = await runtime.invoke(prepared)

    assert reply == "anthropic refreshed"
    assert auth_state["refresh_calls"] == 1
    assert observed[0]["headers"]["x-api-key"] == "anthropic-stale-key"
    assert observed[1]["headers"]["x-api-key"] == "anthropic-fresh-key"
    assert prepared.response_metadata["finish_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_agent_runtime_anthropic_vertex_invokes_raw_predict(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "https://global-aiplatform.googleapis.com/v1/projects/demo/locations/global/publishers/anthropic/models",
            "api_key": "ya29.vertex-token",
            "model": "claude-sonnet-4-0",
            "provider_id": "anthropic",
            "auth_transport": "anthropic_vertex",
            "resolved_auth_metadata": {"project_id": "demo", "location": "global"},
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello vertex")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )
    observed = {}

    class _FakeResponse:
        status_code = 200
        text = '{"type":"message"}'

        def json(self):
            return {
                "type": "message",
                "content": [{"type": "text", "text": "vertex reply"}],
                "stop_reason": "end_turn",
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            observed["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            observed["url"] = url
            observed["headers"] = headers
            observed["json"] = json
            return _FakeResponse()

    monkeypatch.setattr("backend.core.agent_runtime.httpx.AsyncClient", _FakeAsyncClient)

    reply = await runtime.invoke(prepared)

    assert reply == "vertex reply"
    assert observed["url"].endswith("/claude-sonnet-4@20250514:rawPredict")
    assert observed["headers"]["Authorization"] == "Bearer ya29.vertex-token"
    assert observed["headers"]["X-Goog-User-Project"] == "demo"
    assert observed["json"]["anthropic_version"] == "vertex-2023-10-16"
    assert "model" not in observed["json"]
    assert prepared.response_metadata["finish_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_agent_runtime_stream_prefers_visible_answer_over_reasoning_for_user_reply(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningAndAnswerBlockMessage("第一段推理", "这是最终回答")

    runtime._chat_model.ainvoke = _ainvoke

    chunks = [chunk async for chunk in runtime.stream_reply(prepared)]

    assert chunks == ["这是最终回答"]
    assert prepared.response_metadata["has_reasoning_output"] is True
    assert prepared.response_metadata.get("used_reasoning_content") is not True


@pytest.mark.asyncio
async def test_agent_runtime_stream_uses_single_shot_reasoning_fallback_for_internal_task(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="__emotion__friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningMessage("", "这是推理内容")

    runtime._chat_model.ainvoke = _ainvoke

    chunks = [chunk async for chunk in runtime.stream_reply(prepared)]

    assert chunks == ["这是推理内容"]
    assert prepared.response_metadata["has_reasoning_output"] is True


@pytest.mark.asyncio
async def test_agent_runtime_stream_uses_reasoning_content_for_internal_task(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="__emotion__friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningMessage("", "第一段\n第二段")

    runtime._chat_model.ainvoke = _ainvoke

    chunks = [chunk async for chunk in runtime.stream_reply(prepared)]

    assert chunks == ["第一段\n第二段"]
    assert prepared.response_metadata["has_reasoning_output"] is True
    assert prepared.response_metadata["used_reasoning_content"] is True


@pytest.mark.asyncio
async def test_agent_runtime_stream_prefers_visible_answer_over_reasoning_summary_blocks_for_user_reply(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "deepseek-r1",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _ainvoke(messages, config=None):
        return _ReasoningAndAnswerBlockMessage("第一段推理", "这是最终回答")

    runtime._chat_model.ainvoke = _ainvoke

    chunks = [chunk async for chunk in runtime.stream_reply(prepared)]

    assert chunks == ["这是最终回答"]
    assert prepared.response_metadata["has_reasoning_output"] is True
    assert prepared.response_metadata.get("used_reasoning_content") is not True


@pytest.mark.asyncio
async def test_agent_runtime_finalize_request_persists_messages(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    memory = _DummyMemory()
    vector_memory = _DummyVectorMemory()
    export_rag = _DummyExportRag()
    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "personalization_enabled": True,
            "profile_update_frequency": 4,
            "emotion_detection_enabled": True,
            "rag_enabled": True,
            "remember_facts_enabled": False,
            "export_rag_enabled": True,
        },
        agent_cfg={"enabled": True},
    )
    monkeypatch.setattr(
        runtime,
        "_analyze_emotion",
        lambda chat_id, text: asyncio.sleep(0, result=SimpleNamespace(emotion="happy")),
    )
    async def _fake_generate_reply(chat_id, user_text, system_prompt=None, memory_context=None, image_path=None):
        if str(chat_id).startswith("__contact_prompt__"):
            return "这是联系人专属 Prompt"
        return "ignored"
    monkeypatch.setattr(runtime, "generate_reply", _fake_generate_reply)
    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Bob", sender="User", content="hi"),
        chat_id="friend:bob",
        user_text="hi",
        dependencies={
            "memory": memory,
            "export_rag": export_rag,
            "vector_memory": vector_memory,
        },
    )

    await runtime.finalize_request(
        prepared,
        "received",
        {"memory": memory, "export_rag": export_rag, "vector_memory": vector_memory},
    )
    await asyncio.sleep(0)
    await runtime.close()

    assert memory.saved_messages[0][0] == "friend:bob"
    saved_roles = [item["role"] for item in memory.saved_messages[0][1]]
    assert saved_roles == ["user", "assistant"]
    assert ("friend:bob", {"nickname": "Bob"}) in memory.profile_updates
    assert prepared.response_metadata["growth_message_count"] == 4
    assert len(memory.background_backlog) == 4
    assert ("friend:bob", "emotion") in memory.background_backlog
    assert ("friend:bob", "contact_prompt") in memory.background_backlog
    assert ("friend:bob", "vector_memory") in memory.background_backlog
    assert ("__global__", "export_rag_sync") in memory.background_backlog
    status = runtime.get_status()
    assert status["growth_mode"] == "deferred_until_batch"
    assert status["growth_tasks_pending"] == 0
    assert status["background_backlog_count"] == 4


@pytest.mark.asyncio
async def test_agent_runtime_background_batch_executes_deferred_tasks(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    memory = _DummyMemory()
    vector_memory = _DummyVectorMemory()
    export_rag = _DummyExportRag()
    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "personalization_enabled": True,
            "profile_update_frequency": 4,
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
            "rag_enabled": True,
            "remember_facts_enabled": True,
            "export_rag_enabled": True,
        },
        agent_cfg={"enabled": True},
    )

    async def _fake_generate_reply(
        chat_id,
        user_text,
        system_prompt=None,
        memory_context=None,
        image_path=None,
        priority="foreground",
    ):
        if str(chat_id).startswith("__emotion__"):
            return '{"emotion":"happy","confidence":0.9,"intensity":4,"keywords_matched":[],"suggested_tone":"warm"}'
        if str(chat_id).startswith("__contact_prompt__"):
            return "这是联系人专属 Prompt"
        if str(chat_id).startswith("__facts__"):
            return '{"new_facts":["喜欢科技"],"relationship_hint":"friend","personality_traits":["direct"]}'
        return "ignored"

    monkeypatch.setattr(runtime, "generate_reply", _fake_generate_reply)

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Bob", sender="User", content="hi"),
        chat_id="friend:bob",
        user_text="hi",
        dependencies={
            "memory": memory,
            "export_rag": export_rag,
            "vector_memory": vector_memory,
        },
    )

    await runtime.finalize_request(
        prepared,
        "received",
        {"memory": memory, "export_rag": export_rag, "vector_memory": vector_memory},
    )
    await asyncio.sleep(0)
    await runtime._run_background_batch_once()
    await runtime.close()

    assert prepared.response_metadata["growth_message_count"] == 4
    assert memory.updated_emotion == ("friend:bob", "happy")
    assert len(vector_memory.inserted) == 2
    assert memory.context_facts == [("friend:bob", "喜欢科技", 20)]
    assert export_rag.sync_calls == 1
    assert memory.saved_contact_prompt == "这是联系人专属 Prompt"
    assert memory.saved_contact_prompt_source == "hybrid"
    assert memory.background_backlog == {}


@pytest.mark.asyncio
async def test_agent_runtime_supports_task_level_growth_controls(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    memory = _DummyMemory()
    vector_memory = _DummyVectorMemory()
    export_rag = _DummyExportRag()
    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "personalization_enabled": True,
            "profile_update_frequency": 4,
            "emotion_detection_enabled": True,
            "emotion_detection_mode": "ai",
            "rag_enabled": True,
            "export_rag_enabled": True,
        },
        agent_cfg={"enabled": True},
    )

    async def _fake_generate_reply(
        chat_id,
        user_text,
        system_prompt=None,
        memory_context=None,
        image_path=None,
        priority="foreground",
    ):
        if str(chat_id).startswith("__emotion__"):
            return '{"emotion":"happy","confidence":0.9,"intensity":4,"keywords_matched":[],"suggested_tone":"warm"}'
        if str(chat_id).startswith("__contact_prompt__"):
            return "这是联系人专属 Prompt"
        return "ignored"

    monkeypatch.setattr(runtime, "generate_reply", _fake_generate_reply)

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Bob", sender="User", content="hi"),
        chat_id="friend:bob",
        user_text="hi",
        dependencies={
            "memory": memory,
            "export_rag": export_rag,
            "vector_memory": vector_memory,
        },
    )

    await runtime.finalize_request(
        prepared,
        "received",
        {"memory": memory, "export_rag": export_rag, "vector_memory": vector_memory},
    )
    await asyncio.sleep(0)

    cleared = await runtime.clear_background_backlog(task_type="contact_prompt")
    assert cleared == 1

    paused = runtime.pause_background_task_type("emotion")
    assert paused == ["emotion"]
    assert runtime.get_status()["paused_growth_task_types"] == ["emotion"]

    await runtime._run_background_batch_once()
    assert ("friend:bob", "emotion") in memory.background_backlog
    assert ("friend:bob", "contact_prompt") not in memory.background_backlog

    manual_result = await runtime.run_background_backlog_now(task_type="emotion")
    assert manual_result["completed"] == 1
    assert manual_result["trigger"] == "manual"
    assert ("friend:bob", "emotion") not in memory.background_backlog

    resumed = runtime.resume_background_task_type("emotion")
    assert resumed == []
    await runtime.close()


@pytest.mark.asyncio
async def test_agent_runtime_prepare_request_uses_contact_prompt_as_effective_base(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    memory = _DummyMemory()
    memory.saved_contact_prompt = "你要像老朋友一样回复，但保持简短。"
    memory.saved_contact_prompt_source = "user_edit"
    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
        },
        bot_cfg={
            "system_prompt": "base prompt\n{user_profile}",
            "system_prompt_overrides": {"Alice": "override prompt"},
            "memory_context_limit": 5,
            "personalization_enabled": True,
            "profile_inject_in_prompt": True,
        },
        agent_cfg={"enabled": True},
    )

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Alice", sender="User", content="hello"),
        chat_id="friend:alice",
        user_text="hello",
        dependencies={"memory": memory, "export_rag": None, "vector_memory": None},
    )

    assert "你要像老朋友一样回复，但保持简短。" in prepared.system_prompt
    assert "override prompt" not in prepared.system_prompt


@pytest.mark.asyncio
async def test_agent_runtime_uses_cross_encoder_reranker_when_available(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    monkeypatch.setattr(
        AgentRuntime,
        "_build_cross_encoder_reranker",
        lambda self: _FakeCrossEncoder(),
    )

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "rag_enabled": True,
            "emotion_detection_enabled": False,
        },
        agent_cfg={
            "enabled": True,
            "retriever_top_k": 1,
            "retriever_rerank_mode": "cross_encoder",
            "retriever_cross_encoder_model": "./models/bge-reranker-base",
        },
    )

    result = await runtime._search_runtime_memory(
        "friend:alice",
        "release plan",
        _CrossEncoderVectorMemory(),
    )

    assert result is not None
    assert "release plan" in result["trace_snippets"][0]
    status = runtime.get_status()
    assert status["retriever_stats"]["rerank_backend"] == "cross_encoder"
    assert status["retriever_stats"]["cross_encoder_configured"] is True


def test_agent_runtime_group_include_sender_injects_sender(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "test-model"},
        bot_cfg={"group_include_sender": True},
        agent_cfg={"enabled": True},
    )

    messages = runtime._build_prompt_messages(
        system_prompt="",
        memory_context=[],
        user_text="今晚发版吗",
        image_path=None,
        event=SimpleNamespace(is_group=True, sender="小王"),
    )

    assert messages[0].content == "[小王] 今晚发版吗"


def test_agent_runtime_profile_update_frequency_controls_refresh(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "test-model"},
        bot_cfg={"profile_update_frequency": 5},
        agent_cfg={"enabled": True},
    )

    assert runtime._should_refresh_profile(SimpleNamespace(message_count=4)) is True
    assert runtime._should_refresh_profile(SimpleNamespace(message_count=3)) is False


def test_agent_runtime_contact_prompt_update_frequency_uses_dedicated_config(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "test-model"},
        bot_cfg={"profile_update_frequency": 10, "contact_prompt_update_frequency": 4},
        agent_cfg={"enabled": True},
    )

    assert runtime._should_refresh_contact_prompt(
        SimpleNamespace(message_count=4, contact_prompt="", contact_prompt_last_message_count=0)
    ) is True
    assert runtime._should_refresh_contact_prompt(
        SimpleNamespace(message_count=3, contact_prompt="", contact_prompt_last_message_count=0)
    ) is False


def test_agent_runtime_next_background_batch_skips_missed_today(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "test-model"},
        bot_cfg={},
        agent_cfg={"enabled": True, "background_ai_batch_time": "04:00"},
    )

    next_run = runtime._compute_next_background_batch_at(datetime(2026, 3, 17, 5, 30, 0))

    assert next_run == datetime(2026, 3, 18, 4, 0, 0)


def test_agent_runtime_build_user_message_metadata_accepts_string_msg_type():
    prepared = SimpleNamespace(
        event=SimpleNamespace(
            chat_name="文件传输助手",
            sender="Alice",
            is_group=False,
            msg_type="text",
        ),
        trace={},
    )

    metadata = AgentRuntime._build_user_message_metadata(prepared)

    assert metadata["message_type"] == "text"
    assert "message_type_code" not in metadata
