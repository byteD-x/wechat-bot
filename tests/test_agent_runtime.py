import asyncio
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

    async def get_recent_context(self, chat_id, limit):
        return [{"role": "assistant", "content": "history reply"}]

    async def get_user_profile(self, chat_id):
        return SimpleNamespace(
            wx_id=chat_id,
            context_facts=["old fact"],
            personality="calm",
            relationship="unknown",
            message_count=3,
        )

    async def increment_message_count(self, chat_id):
        return 4

    async def add_messages(self, chat_id, messages):
        self.saved_messages.append((chat_id, list(messages)))

    async def update_emotion(self, chat_id, emotion):
        self.updated_emotion = (chat_id, emotion)

    async def add_context_fact(self, chat_id, fact, max_facts=20):
        return None

    async def update_user_profile(self, chat_id, **fields):
        return None


class _DummyExportRag:
    async def search(self, ai_client, chat_id, query_text):
        return [{"text": "style snippet"}]

    def build_memory_message(self, results):
        return {"role": "system", "content": "style snippet"}


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

    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "system_prompt": "base prompt",
            "memory_context_limit": 5,
            "personalization_enabled": True,
            "emotion_detection_enabled": False,
            "rag_enabled": True,
            "remember_facts_enabled": True,
        },
        agent_cfg={"enabled": True, "streaming_enabled": True},
    )

    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Alice", sender="User", content="hello"),
        chat_id="friend:alice",
        user_text="hello",
        dependencies={
            "memory": _DummyMemory(),
            "export_rag": _DummyExportRag(),
            "vector_memory": _DummyVectorMemory(),
        },
    )

    assert "base prompt" in prepared.system_prompt
    assert any(item["content"] == "style snippet" for item in prepared.memory_context)
    assert any(item["content"].startswith("Relevant past memories") for item in prepared.memory_context)
    assert len(prepared.prompt_messages) >= 3


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
async def test_agent_runtime_invoke_uses_reasoning_content_for_ollama_user_reply(monkeypatch):
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
        return _ReasoningMessage("", "这是通过 reasoning_content 返回的回复")

    runtime._chat_model.ainvoke = _ainvoke

    reply = await runtime.invoke(prepared)

    assert reply == "这是通过 reasoning_content 返回的回复"
    assert prepared.response_metadata["used_reasoning_content"] is True


@pytest.mark.asyncio
async def test_agent_runtime_stream_uses_reasoning_content_for_ollama_user_reply(monkeypatch):
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
        agent_cfg={"enabled": True, "streaming_enabled": True},
    )
    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello")],
        chat_id="friend:alice",
        response_metadata={},
        timings={},
    )

    async def _astream(messages, config=None):
        yield _ReasoningMessage("", "第一段")
        yield _ReasoningMessage("", "第二段")

    runtime._stream_model.astream = _astream

    chunks = [chunk async for chunk in runtime.stream_reply(prepared)]

    assert chunks == ["第一段", "第二段"]
    assert prepared.response_metadata["used_reasoning_content"] is True


@pytest.mark.asyncio
async def test_agent_runtime_finalize_request_persists_messages(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    memory = _DummyMemory()
    vector_memory = _DummyVectorMemory()
    runtime = AgentRuntime(
        settings={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "test-model",
            "embedding_model": "embed-model",
        },
        bot_cfg={
            "remember_facts_enabled": False,
        },
        agent_cfg={"enabled": True},
    )
    prepared = await runtime.prepare_request(
        event=SimpleNamespace(chat_name="Bob", sender="User", content="hi"),
        chat_id="friend:bob",
        user_text="hi",
        dependencies={
            "memory": memory,
            "export_rag": None,
            "vector_memory": vector_memory,
        },
    )

    await runtime.finalize_request(
        prepared,
        "received",
        {"memory": memory, "export_rag": None, "vector_memory": vector_memory},
    )
    await asyncio.sleep(0)
    await runtime.close()

    assert memory.saved_messages[0][0] == "friend:bob"
    saved_roles = [item["role"] for item in memory.saved_messages[0][1]]
    assert saved_roles == ["user", "assistant"]
    assert len(vector_memory.inserted) == 2


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
