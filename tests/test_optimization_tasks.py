import os
import tempfile
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("aiosqlite")

import backend.core.ai_client as ai_client_module
import backend.core.factory as factory_module
import backend.utils.runtime_artifacts as runtime_artifacts_module
from backend.config_schemas import BotConfig
from backend.core.agent_runtime import AgentRuntime
from backend.core.ai_client import AIClient
from backend.core.memory import MemoryManager
from backend.transports import BaseTransport, WcferryWeChatClient
from backend.transports.wcferry_adapter import (
    TransportUnavailableError,
    _best_effort_wcf_call,
    _build_local_wcferry_recovery_hint,
    _cleanup_stale_wcferry_ports,
    _extract_supported_wechat_versions,
)
from backend.wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION


class _FakeAsyncClient:
    instances = []
    closed_count = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.is_closed = False
        type(self).instances.append(self)

    async def aclose(self):
        if not self.is_closed:
            self.is_closed = True
            type(self).closed_count += 1


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def ainvoke(self, messages, config=None):
        return _FakeMessage("ok")

    async def astream(self, messages, config=None):
        yield _FakeMessage("ok")


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


class _DummyVectorMemory:
    def search(self, query=None, n_results=5, filter_meta=None, query_embedding=None):
        return [
            {"text": "完全无关的闲聊", "distance": 0.05},
            {"text": "今晚发布计划和回滚安排", "distance": 0.35},
        ]


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
async def test_ai_client_pool_reuses_http_clients(monkeypatch):
    _FakeAsyncClient.instances = []
    _FakeAsyncClient.closed_count = 0
    monkeypatch.setattr(ai_client_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ai_client_module, "_client_pool", ai_client_module.AIClientPool())

    client_a = AIClient(
        base_url="https://example.com/v1",
        api_key="",
        model="test-model",
        timeout_sec=12,
    )
    client_b = AIClient(
        base_url="https://example.com/v1",
        api_key="",
        model="test-model",
        timeout_sec=12,
    )

    assert client_a._get_http_client() is client_b._get_http_client()
    assert len(_FakeAsyncClient.instances) == 1

    await client_a.close()
    assert _FakeAsyncClient.closed_count == 0

    await client_b.close()
    assert _FakeAsyncClient.closed_count == 1


@pytest.mark.asyncio
async def test_memory_manager_get_recent_context_batch_returns_grouped_rows():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "memory.db")
        manager = MemoryManager(db_path)
        try:
            await manager.add_messages(
                "friend:alice",
                [
                    {"role": "user", "content": "A1"},
                    {"role": "assistant", "content": "A2"},
                    {"role": "user", "content": "A3"},
                ],
            )
            await manager.add_messages(
                "friend:bob",
                [
                    {"role": "user", "content": "B1"},
                    {"role": "assistant", "content": "B2"},
                ],
            )

            batch = await manager.get_recent_context_batch(
                ["friend:alice", "friend:bob"],
                limit=2,
            )

            assert batch["friend:alice"] == [
                {"role": "assistant", "content": "A2"},
                {"role": "user", "content": "A3"},
            ]
            assert batch["friend:bob"] == [
                {"role": "user", "content": "B1"},
                {"role": "assistant", "content": "B2"},
            ]
        finally:
            await manager.close()


@pytest.mark.asyncio
async def test_agent_runtime_reranks_runtime_memory_results(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

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
        agent_cfg={"enabled": True, "retriever_top_k": 1},
    )

    result = await runtime._search_runtime_memory(
        "friend:alice",
        "发布计划",
        _DummyVectorMemory(),
    )

    assert result is not None
    assert result["trace_snippets"][0] == "今晚发布计划和回滚安排"
    assert "今晚发布计划和回滚安排" in result["content"]


def test_wcferry_transport_implements_base_transport():
    assert issubclass(WcferryWeChatClient, BaseTransport)


def test_bot_schema_defaults_to_official_wechat_version():
    assert BotConfig().required_wechat_version == OFFICIAL_SUPPORTED_WECHAT_VERSION


def test_bot_schema_allows_zero_reply_deadline():
    assert BotConfig(reply_deadline_sec=0).reply_deadline_sec == 0


@pytest.mark.asyncio
async def test_memory_manager_initialize_opens_connection(tmp_path):
    manager = MemoryManager(str(tmp_path / "chat_memory.db"))

    conn = await manager.initialize()

    assert conn is manager._conn
    await manager.close()


def test_extract_supported_wechat_versions_from_binary(tmp_path):
    binary = tmp_path / "spy.dll"
    binary.write_bytes(b"header\x003.9.12.51\x00tail\x003.9.12.17\x00")

    assert _extract_supported_wechat_versions(binary) == ["3.9.12.17", "3.9.12.51"]


def test_wcferry_version_gate_blocks_unsupported_runtime_version():
    client = object.__new__(WcferryWeChatClient)
    client.bot_cfg = {"silent_mode_required": False}
    client.configured_required_version = ""
    client.supported_wechat_versions = ["3.9.12.51"]
    client.wechat_version = "3.9.12.17"
    client.transport_status = SimpleNamespace(warning="")

    with pytest.raises(TransportUnavailableError, match="3.9.12.51"):
        client._validate_version_gate()


def test_best_effort_wcf_call_times_out_quickly():
    started = time.perf_counter()
    ok = _best_effort_wcf_call("cleanup", lambda: time.sleep(0.2), timeout_sec=0.05)
    elapsed = time.perf_counter() - started

    assert ok is False
    assert elapsed < 0.15


def test_wcferry_close_uses_best_effort_cleanup(monkeypatch):
    client = object.__new__(WcferryWeChatClient)
    client._uses_local_wcf_sdk = True
    client._wcf = SimpleNamespace(
        _is_receiving_msg=True,
        disable_recv_msg=lambda: None,
        cleanup=lambda: None,
    )

    calls = []
    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._best_effort_wcf_call",
        lambda label, func, timeout_sec=2.0: calls.append(label) or True,
    )
    monkeypatch.setattr(
        "backend.transports.wcferry_adapter.relocate_known_root_artifacts",
        lambda: calls.append("relocate"),
    )
    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._destroy_stale_local_wcf_session",
        lambda: calls.append("destroy") or True,
    )

    client.close()

    assert client._wcf._is_receiving_msg is False
    assert calls == ["disable_recv_msg", "cleanup", "destroy", "relocate"]


def test_cleanup_stale_wcferry_ports_destroys_existing_sdk(monkeypatch):
    state = {"active": True, "destroyed": 0}

    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._is_tcp_port_open",
        lambda host, port, timeout_sec=0.25: state["active"],
    )

    def _fake_destroy():
        state["destroyed"] += 1
        state["active"] = False
        return True

    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._destroy_stale_local_wcf_session",
        _fake_destroy,
    )

    assert _cleanup_stale_wcferry_ports(wait_timeout_sec=0.2) is True
    assert state["destroyed"] == 1


def test_build_local_wcferry_recovery_hint_reports_conflicts(monkeypatch):
    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._is_tcp_port_open",
        lambda host, port, timeout_sec=0.25: True,
    )
    monkeypatch.setattr(
        "backend.transports.wcferry_adapter._count_running_wechat_processes",
        lambda: 2,
    )

    hint = _build_local_wcferry_recovery_hint()

    assert "10086/10087" in hint
    assert "2 个 WeChat.exe" in hint


def test_relocate_known_root_artifacts_moves_files(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    runtime_root = project_root / "data" / "runtime"
    wcferry_dir = runtime_root / "wcferry"
    lock_dir = runtime_root / "locks"
    coverage_dir = runtime_root / "test" / "coverage"

    monkeypatch.setattr(runtime_artifacts_module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(runtime_artifacts_module, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(runtime_artifacts_module, "WCFERRY_DIR", wcferry_dir)
    monkeypatch.setattr(runtime_artifacts_module, "LOCK_DIR", lock_dir)
    monkeypatch.setattr(runtime_artifacts_module, "COVERAGE_DIR", coverage_dir)

    (project_root / "injector.log").write_text("inject", encoding="utf-8")
    (project_root / ".ctx.lock").write_bytes(b"lock")
    (project_root / ".coverage").write_text("cov", encoding="utf-8")

    runtime_artifacts_module.relocate_known_root_artifacts()

    assert not (project_root / "injector.log").exists()
    assert not (project_root / ".ctx.lock").exists()
    assert not (project_root / ".coverage").exists()
    assert (wcferry_dir / "injector.log").exists()
    assert (lock_dir / ".ctx.lock").exists()
    assert (coverage_dir / ".coverage").exists()


def test_ai_client_without_embedding_model_disables_embeddings():
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="",
        model="test-model",
    )

    assert client.embedding_model is None


def test_agent_runtime_allow_empty_key_uses_dummy_runtime_key(monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)

    runtime = AgentRuntime(
        settings={
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model": "qwen3:8b",
            "embedding_model": "nomic-embed-text",
            "allow_empty_key": True,
        },
        bot_cfg={},
        agent_cfg={"enabled": True},
    )

    assert runtime._chat_model.kwargs["api_key"] == "wechat-chat-allow-empty-key"
    assert runtime._embedding_client.kwargs["api_key"] == "wechat-chat-allow-empty-key"


@pytest.mark.asyncio
async def test_select_specific_ai_client_ollama_does_not_inherit_root_embedding_model(monkeypatch):
    captured = {}

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            captured.update(self.settings)
            return True

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)

    client, preset_name = await factory_module.select_specific_ai_client(
        {
            "embedding_model": "text-embedding-3-small",
            "presets": [
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "",
                    "model": "qwen3:8b",
                    "allow_empty_key": True,
                }
            ],
        },
        {},
        "Ollama",
        {"enabled": True},
    )

    assert client is not None
    assert preset_name == "Ollama"
    assert captured["embedding_model"] is None


@pytest.mark.asyncio
async def test_select_specific_ai_client_prefers_vector_memory_embedding_override(monkeypatch):
    captured = {}

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            captured.update(self.settings)
            return True

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)

    client, preset_name = await factory_module.select_specific_ai_client(
        {
            "embedding_model": "text-embedding-3-small",
            "presets": [
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "",
                    "model": "qwen3",
                    "embedding_model": "nomic-embed-text",
                    "allow_empty_key": True,
                }
            ],
        },
        {"vector_memory_embedding_model": "bge-m3:latest"},
        "Ollama",
        agent_cfg={"enabled": True},
    )

    assert client is not None
    assert preset_name == "Ollama"
    assert captured["embedding_model"] == "bge-m3:latest"


@pytest.mark.asyncio
async def test_reconnect_wechat_retries_hook_transport(monkeypatch):
    attempts = {"count": 0}

    class _FakeTransportUnavailableError(RuntimeError):
        pass

    class _FakeTransport:
        backend_name = "hook_wcferry"

        def __init__(self, bot_cfg, ai_client=None):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise _FakeTransportUnavailableError("timed out")

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_sleep(_seconds):
        return None

    import backend.transports as transports_module

    monkeypatch.setattr(factory_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(factory_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(transports_module, "WcferryWeChatClient", _FakeTransport)
    monkeypatch.setattr(transports_module, "TransportUnavailableError", _FakeTransportUnavailableError)

    client = await factory_module.reconnect_wechat(
        "test",
        factory_module.ReconnectPolicy(
            max_retries=3,
            base_delay_sec=0.1,
            max_delay_sec=0.2,
        ),
        bot_cfg={"transport_backend": "hook_wcferry"},
    )

    assert client is not None
    assert attempts["count"] == 3
