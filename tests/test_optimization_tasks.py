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
from backend.model_auth.services.migration import (
    ensure_provider_auth_center_config,
    hydrate_runtime_settings,
    project_provider_auth_center,
)
from backend.model_auth.storage.credential_store import CredentialStore
from backend.transports import BaseTransport, WcferryTransport
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


def _build_provider_auth_openai_api_cfg(tmp_path, *, selection_mode="auto", selected_method="api_key"):
    store = CredentialStore(str(tmp_path / "provider-auth-creds.json"))
    config = ensure_provider_auth_center_config(
        {
            "api": {
                "active_preset": "OpenAI",
                "presets": [
                    {
                        "name": "OpenAI",
                        "provider_id": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "demo-openai-test-key-123456",
                        "auth_mode": "api_key",
                        "model": "gpt-5-mini",
                    }
                ],
            }
        },
        credential_store=store,
    )
    entry = config["api"]["provider_auth_center"]["providers"]["openai"]
    api_profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "api_key")
    oauth_profile = {
        "id": "openai:codex_local:chatgpt",
        "provider_id": "openai",
        "method_id": "codex_local",
        "method_type": "local_import",
        "label": "ChatGPT OAuth",
        "credential_ref": "",
        "credential_source": "local_config_file",
        "binding": {
            "source": "codex_auth_json",
            "source_type": "openai_codex",
            "credential_source": "local_config_file",
            "sync_policy": "follow",
            "follow_local_auth": True,
        },
        "metadata": {
            "runtime_ready": True,
            "base_url": "https://chatgpt.com/backend-api",
            "model": "gpt-5.4",
        },
    }
    entry["auth_profiles"].append(oauth_profile)
    entry.setdefault("metadata", {})
    entry["metadata"]["selection_mode"] = selection_mode
    entry["selected_profile_id"] = oauth_profile["id"] if selected_method == "oauth" else api_profile["id"]
    return project_provider_auth_center(config["api"]), api_profile["id"], oauth_profile["id"], store


def _build_provider_auth_qwen_coding_api_cfg(tmp_path, *, base_url="https://coding.dashscope.aliyuncs.com/v1/chat/completions"):
    store = CredentialStore(str(tmp_path / "provider-auth-creds.json"))
    config = ensure_provider_auth_center_config(
        {
            "api": {
                "active_preset": "Qwen Coding Plan",
                "presets": [
                    {
                        "name": "Qwen Coding Plan",
                        "provider_id": "qwen",
                        "base_url": base_url,
                        "api_key": "demo-qwen-coding-key-123456",
                        "auth_mode": "api_key",
                        "model": "qwen3-coder-plus",
                    }
                ],
            }
        },
        credential_store=store,
    )
    return project_provider_auth_center(config["api"]), store


def _build_provider_auth_qwen_oauth_api_cfg():
    return project_provider_auth_center(
        {
            "active_preset": "Qwen OAuth",
            "provider_auth_center": {
                "active_provider_id": "qwen",
                "providers": {
                    "qwen": {
                        "provider_id": "qwen",
                        "legacy_preset_name": "Qwen OAuth",
                        "alias": "",
                        "default_model": "qwen3.5-plus",
                        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "selected_profile_id": "qwen:qwen_oauth:work",
                        "auth_profiles": [
                            {
                                "id": "qwen:qwen_oauth:work",
                                "provider_id": "qwen",
                                "method_id": "qwen_oauth",
                                "method_type": "oauth",
                                "label": "Qwen OAuth",
                                "credential_ref": "",
                                "credential_source": "local_config_file",
                                "binding": {
                                    "source": "qwen_oauth_creds",
                                    "source_type": "qwen_oauth",
                                    "credential_source": "local_config_file",
                                    "sync_policy": "follow",
                                    "follow_local_auth": True,
                                },
                                "metadata": {
                                    "runtime_ready": True,
                                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                    "model": "qwen3.5-plus",
                                },
                            }
                        ],
                        "metadata": {"project_to_runtime": True},
                    }
                },
            },
        }
    )


def _build_provider_auth_glm_coding_api_cfg(tmp_path, *, base_url="https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"):
    store = CredentialStore(str(tmp_path / "provider-auth-creds.json"))
    config = ensure_provider_auth_center_config(
        {
            "api": {
                "active_preset": "GLM Coding Plan",
                "presets": [
                    {
                        "name": "GLM Coding Plan",
                        "base_url": base_url,
                        "api_key": "demo-glm-coding-key-123456",
                        "auth_mode": "api_key",
                        "model": "glm-5",
                    }
                ],
            }
        },
        credential_store=store,
    )
    return project_provider_auth_center(config["api"]), store


def _build_provider_auth_kimi_local_api_cfg():
    return project_provider_auth_center(
        {
            "active_preset": "Kimi",
            "provider_auth_center": {
                "active_provider_id": "kimi",
                "providers": {
                    "kimi": {
                        "provider_id": "kimi",
                        "legacy_preset_name": "Kimi",
                        "alias": "",
                        "default_model": "kimi-thinking-preview",
                        "default_base_url": "https://api.moonshot.cn/v1",
                        "selected_profile_id": "kimi:kimi_code_local:work",
                        "auth_profiles": [
                            {
                                "id": "kimi:kimi_code_local:work",
                                "provider_id": "kimi",
                                "method_id": "kimi_code_local",
                                "method_type": "local_import",
                                "label": "Kimi Local",
                                "credential_ref": "",
                                "credential_source": "local_config_file",
                                "binding": {
                                    "source": "kimi_code_credentials",
                                    "source_type": "kimi_code_local",
                                    "credential_source": "local_config_file",
                                    "sync_policy": "follow",
                                    "follow_local_auth": True,
                                },
                                "metadata": {
                                    "runtime_ready": True,
                                    "base_url": "https://api.kimi.com/coding/v1",
                                    "model": "kimi-k2-turbo-preview",
                                },
                            }
                        ],
                        "metadata": {"project_to_runtime": True},
                    }
                },
            },
        }
    )


def _build_provider_auth_kimi_legacy_api_fallback_cfg(
    tmp_path,
    *,
    selection_mode="manual",
    selected_method="local",
):
    store = CredentialStore(str(tmp_path / "provider-auth-creds.json"))
    config = ensure_provider_auth_center_config(
        {
            "api": {
                "active_preset": "Moonshot",
                "presets": [
                    {
                        "name": "Moonshot",
                        "provider_id": "moonshot",
                        "base_url": "https://api.moonshot.cn/v1",
                        "api_key": "ms-test-key-1234567890",
                        "auth_mode": "api_key",
                        "model": "kimi-k2-turbo-preview",
                    }
                ],
            }
        },
        credential_store=store,
    )
    entry = config["api"]["provider_auth_center"]["providers"]["kimi"]
    api_profile = next(item for item in entry["auth_profiles"] if item["method_id"] == "api_key")
    local_profile = {
        "id": "kimi:kimi_code_local:work",
        "provider_id": "kimi",
        "method_id": "kimi_code_local",
        "method_type": "local_import",
        "label": "Kimi Local",
        "credential_ref": "",
        "credential_source": "local_config_file",
        "binding": {
            "source": "kimi_code_credentials",
            "source_type": "kimi_code_local",
            "credential_source": "local_config_file",
            "sync_policy": "follow",
            "follow_local_auth": True,
        },
        "metadata": {
            "runtime_ready": True,
            "base_url": "https://api.kimi.com/coding/v1",
            "model": "kimi-k2-turbo-preview",
        },
    }
    entry["auth_profiles"].append(local_profile)
    entry.setdefault("metadata", {})
    entry["metadata"]["selection_mode"] = selection_mode
    entry["selected_profile_id"] = local_profile["id"] if selected_method == "local" else api_profile["id"]
    return project_provider_auth_center(config["api"]), api_profile["id"], local_profile["id"], store


def _build_provider_auth_minimax_coding_api_cfg(
    tmp_path,
    *,
    base_url="https://api.minimaxi.com/anthropic/messages",
):
    store = CredentialStore(str(tmp_path / "provider-auth-creds.json"))
    config = ensure_provider_auth_center_config(
        {
            "api": {
                "active_preset": "MiniMax Coding Plan",
                "presets": [
                    {
                        "name": "MiniMax Coding Plan",
                        "base_url": base_url,
                        "api_key": "demo-minimax-coding-key-123456",
                        "auth_mode": "api_key",
                        "model": "MiniMax-M2.5",
                    }
                ],
            }
        },
        credential_store=store,
    )
    return project_provider_auth_center(config["api"]), store


class _ChatProbeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = "ok"

    def json(self):
        return self._payload


class _ChatProbeHttpClient:
    def __init__(self, payload, observed):
        self._payload = payload
        self._observed = observed

    async def post(self, url, headers=None, json=None, timeout=None):
        self._observed.append({"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout})
        return _ChatProbeResponse(self._payload)


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
    assert issubclass(WcferryTransport, BaseTransport)


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
    client = object.__new__(WcferryTransport)
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
    client = object.__new__(WcferryTransport)
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
    monkeypatch.setattr(
        factory_module,
        "_fetch_ollama_models",
        lambda _base_url, timeout_sec=3.0: [{"name": "qwen3:8b", "model": "qwen3:8b"}],
    )

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
    monkeypatch.setattr(
        factory_module,
        "_fetch_ollama_models",
        lambda _base_url, timeout_sec=3.0: [{"name": "qwen3", "model": "qwen3"}],
    )

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
async def test_select_ai_client_falls_back_to_other_presets(monkeypatch):
    attempted = []

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            attempted.append(self.settings["name"])
            return self.settings["name"] == "Healthy"

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)

    client, preset_name = await factory_module.select_ai_client(
        {
            "active_preset": "Broken",
            "presets": [
                {
                    "name": "Broken",
                    "base_url": "https://broken.example/v1",
                    "api_key": "demo-broken-key-123456",
                    "model": "broken-model",
                },
                {
                    "name": "Healthy",
                    "base_url": "https://healthy.example/v1",
                    "api_key": "demo-healthy-key-123456",
                    "model": "healthy-model",
                },
            ],
        },
        {},
        {"enabled": True},
    )

    assert client is not None
    assert preset_name == "Healthy"
    assert attempted == ["Broken", "Healthy"]


@pytest.mark.asyncio
async def test_select_ai_client_falls_back_to_api_key_when_same_provider_oauth_resolution_fails(tmp_path, monkeypatch):
    api_cfg, api_profile_id, oauth_profile_id, store = _build_provider_auth_openai_api_cfg(
        tmp_path,
        selection_mode="auto",
        selected_method="api_key",
    )
    attempted = []

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            attempted.append(self.settings["provider_auth_profile_id"])
            return True

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    def _resolve_fake_oauth(settings):
        if settings.get("provider_auth_profile_id") == oauth_profile_id:
            raise factory_module.OAuthSupportError("oauth unavailable")
        return SimpleNamespace(settings=dict(settings))

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)
    monkeypatch.setattr(factory_module, "resolve_oauth_settings", _resolve_fake_oauth)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_ai_client(
        api_cfg,
        {},
        {"enabled": True},
    )

    assert client is not None
    assert preset_name == "OpenAI"
    assert attempted == [api_profile_id]


@pytest.mark.asyncio
async def test_select_ai_client_honors_manual_profile_then_falls_back_to_other_auth(tmp_path, monkeypatch):
    api_cfg, api_profile_id, oauth_profile_id, store = _build_provider_auth_openai_api_cfg(
        tmp_path,
        selection_mode="manual",
        selected_method="api_key",
    )
    attempted = []

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            attempted.append(self.settings["provider_auth_profile_id"])
            return self.settings["provider_auth_profile_id"] == oauth_profile_id

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)
    monkeypatch.setattr(
        factory_module,
        "resolve_oauth_settings",
        lambda settings: SimpleNamespace(settings=dict(settings)),
    )
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_ai_client(
        api_cfg,
        {},
        {"enabled": True},
    )

    assert client is not None
    assert preset_name == "OpenAI"
    assert attempted == [api_profile_id, oauth_profile_id]


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_same_provider_fallback_chain(tmp_path, monkeypatch):
    api_cfg, api_profile_id, oauth_profile_id, store = _build_provider_auth_openai_api_cfg(
        tmp_path,
        selection_mode="auto",
        selected_method="api_key",
    )
    attempted = []

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            attempted.append(self.settings["provider_auth_profile_id"])
            return self.settings["provider_auth_profile_id"] == api_profile_id

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    def _resolve_fake_oauth(settings):
        if settings.get("provider_auth_profile_id") == oauth_profile_id:
            raise factory_module.OAuthSupportError("oauth unavailable")
        return SimpleNamespace(settings=dict(settings))

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)
    monkeypatch.setattr(factory_module, "resolve_oauth_settings", _resolve_fake_oauth)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "OpenAI",
        {"enabled": True},
    )

    assert client is not None
    assert preset_name == "OpenAI"
    assert attempted == [api_profile_id]


@pytest.mark.asyncio
async def test_select_specific_ai_client_falls_back_from_kimi_local_to_canonicalized_api_key(tmp_path, monkeypatch):
    api_cfg, api_profile_id, local_profile_id, store = _build_provider_auth_kimi_legacy_api_fallback_cfg(
        tmp_path,
        selection_mode="manual",
        selected_method="local",
    )
    preset_name = api_cfg["presets"][0]["name"]
    attempted = []

    class _FakeRuntimeClient:
        def __init__(self, settings):
            self.settings = dict(settings)

        async def probe(self):
            attempted.append(self.settings["provider_auth_profile_id"])
            return True

    def _build_fake_runtime(settings, bot_cfg, agent_cfg=None):
        return _FakeRuntimeClient(settings)

    def _resolve_fake_oauth(settings):
        if settings.get("provider_auth_profile_id") == local_profile_id:
            raise factory_module.OAuthSupportError("oauth unavailable")
        return SimpleNamespace(settings=dict(settings))

    monkeypatch.setattr(factory_module, "build_agent_runtime", _build_fake_runtime)
    monkeypatch.setattr(factory_module, "resolve_oauth_settings", _resolve_fake_oauth)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, resolved_preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        preset_name,
        {"enabled": True},
    )

    assert client is not None
    assert resolved_preset_name == preset_name
    assert api_cfg["presets"][0]["provider_id"] == "kimi"
    assert attempted == [api_profile_id]


@pytest.mark.asyncio
async def test_select_specific_ai_client_normalizes_qwen_coding_plan_base_url_and_can_chat(tmp_path, monkeypatch):
    api_cfg, store = _build_provider_auth_qwen_coding_api_cfg(tmp_path)
    observed = []
    http_client = _ChatProbeHttpClient(
        {"choices": [{"message": {"content": "qwen coding ok"}}]},
        observed,
    )
    monkeypatch.setattr(ai_client_module.AIClient, "_get_http_client", lambda self: http_client)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Qwen Coding Plan",
        {"enabled": False},
    )

    assert isinstance(client, AIClient)
    assert preset_name == "Qwen Coding Plan"
    assert client.base_url == "https://coding.dashscope.aliyuncs.com/v1"

    reply = await client.generate_reply("friend:alice", "write a test")

    assert reply == "qwen coding ok"
    assert observed[0]["url"] == "https://coding.dashscope.aliyuncs.com/v1/chat/completions"
    assert observed[1]["url"] == "https://coding.dashscope.aliyuncs.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_qwen_coding_plan_with_agent_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    api_cfg, store = _build_provider_auth_qwen_coding_api_cfg(tmp_path)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Qwen Coding Plan",
        {"enabled": True},
    )

    assert isinstance(client, AgentRuntime)
    assert preset_name == "Qwen Coding Plan"
    assert client.base_url == "https://coding.dashscope.aliyuncs.com/v1"
    assert client.runtime_api_key == "demo-qwen-coding-key-123456"

    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("write a test")],
        chat_id="friend:alice",
        user_text="write a test",
        response_metadata={},
        timings={},
    )
    reply = await client.invoke(prepared)

    assert reply == "ok"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_qwen_oauth_for_chat(tmp_path, monkeypatch):
    oauth_path = tmp_path / "qwen-oauth.json"
    oauth_path.write_text(
        '{"access_token":"qwen-access-token-123","refresh_token":"qwen-refresh-token-456","expires_at":4102444800}',
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_QWEN_OAUTH_PATH", str(oauth_path))
    api_cfg = _build_provider_auth_qwen_oauth_api_cfg()
    observed = []
    http_client = _ChatProbeHttpClient(
        {"choices": [{"message": {"content": "qwen oauth ok"}}]},
        observed,
    )
    monkeypatch.setattr(ai_client_module.AIClient, "_get_http_client", lambda self: http_client)

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Qwen OAuth",
        {"enabled": False},
    )

    assert isinstance(client, AIClient)
    assert preset_name == "Qwen OAuth"
    assert client.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert client._resolve_api_key() == "qwen-access-token-123"

    reply = await client.generate_reply("friend:alice", "hello qwen")

    assert reply == "qwen oauth ok"
    assert observed[0]["headers"]["X-DashScope-AuthType"] == "qwen-oauth"
    assert observed[1]["headers"]["Authorization"] == "Bearer qwen-access-token-123"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_qwen_oauth_with_agent_runtime(tmp_path, monkeypatch):
    oauth_path = tmp_path / "qwen-oauth.json"
    oauth_path.write_text(
        '{"access_token":"qwen-access-token-123","refresh_token":"qwen-refresh-token-456","expires_at":4102444800}',
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_BOT_QWEN_OAUTH_PATH", str(oauth_path))
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    api_cfg = _build_provider_auth_qwen_oauth_api_cfg()

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Qwen OAuth",
        {"enabled": True},
    )

    assert isinstance(client, AgentRuntime)
    assert preset_name == "Qwen OAuth"
    assert client.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert client.runtime_api_key == "qwen-access-token-123"
    assert client._chat_model.kwargs["default_headers"]["X-DashScope-AuthType"] == "qwen-oauth"

    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello qwen")],
        chat_id="friend:alice",
        user_text="hello qwen",
        response_metadata={},
        timings={},
    )
    reply = await client.invoke(prepared)

    assert reply == "ok"


@pytest.mark.asyncio
async def test_select_specific_ai_client_normalizes_glm_coding_plan_base_url_and_can_chat(tmp_path, monkeypatch):
    api_cfg, store = _build_provider_auth_glm_coding_api_cfg(tmp_path)
    observed = []
    http_client = _ChatProbeHttpClient(
        {"choices": [{"message": {"content": "glm coding ok"}}]},
        observed,
    )
    monkeypatch.setattr(ai_client_module.AIClient, "_get_http_client", lambda self: http_client)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "GLM Coding Plan",
        {"enabled": False},
    )

    assert isinstance(client, AIClient)
    assert preset_name == "GLM Coding Plan"
    assert client.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"

    reply = await client.generate_reply("friend:alice", "write a GLM test")

    assert reply == "glm coding ok"
    assert observed[0]["url"] == "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
    assert observed[1]["json"]["model"] == "glm-5"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_glm_coding_plan_with_agent_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    api_cfg, store = _build_provider_auth_glm_coding_api_cfg(tmp_path)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "GLM Coding Plan",
        {"enabled": True},
    )

    assert isinstance(client, AgentRuntime)
    assert preset_name == "GLM Coding Plan"
    assert client.provider_id == "zhipu"
    assert client.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert client.runtime_api_key == "demo-glm-coding-key-123456"

    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("write a GLM test")],
        chat_id="friend:alice",
        user_text="write a GLM test",
        response_metadata={},
        timings={},
    )
    reply = await client.invoke(prepared)

    assert reply == "ok"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_kimi_local_auth_for_chat(tmp_path, monkeypatch):
    share_dir = tmp_path / ".kimi"
    credentials_dir = share_dir / "credentials"
    credentials_dir.mkdir(parents=True)
    (share_dir / "config.toml").write_text(
        '\n'.join(
            [
                '[providers.kimi-for-coding]',
                'type = "kimi"',
                'base_url = "https://api.kimi.com/coding/v1"',
                'model = "kimi-k2-turbo-preview"',
            ]
        ),
        encoding="utf-8",
    )
    (credentials_dir / "kimi.json").write_text(
        '{"access_token":"kimi-access-token-1234567890"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))
    api_cfg = _build_provider_auth_kimi_local_api_cfg()
    observed = []
    http_client = _ChatProbeHttpClient(
        {"choices": [{"message": {"content": "kimi local ok"}}]},
        observed,
    )
    monkeypatch.setattr(ai_client_module.AIClient, "_get_http_client", lambda self: http_client)

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Kimi",
        {"enabled": False},
    )

    assert isinstance(client, AIClient)
    assert preset_name == "Kimi"
    assert client.base_url == "https://api.kimi.com/coding/v1"
    assert client._resolve_api_key() == "kimi-access-token-1234567890"

    reply = await client.generate_reply("friend:alice", "hello kimi")

    assert reply == "kimi local ok"
    assert observed[0]["url"] == "https://api.kimi.com/coding/v1/chat/completions"
    assert observed[1]["json"]["model"] == "kimi-k2-turbo-preview"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_kimi_local_auth_with_agent_runtime(tmp_path, monkeypatch):
    share_dir = tmp_path / ".kimi"
    credentials_dir = share_dir / "credentials"
    credentials_dir.mkdir(parents=True)
    (share_dir / "config.toml").write_text(
        '\n'.join(
            [
                '[providers.kimi-for-coding]',
                'type = "kimi"',
                'base_url = "https://api.kimi.com/coding/v1"',
                'model = "kimi-k2-turbo-preview"',
            ]
        ),
        encoding="utf-8",
    )
    (credentials_dir / "kimi.json").write_text(
        '{"access_token":"kimi-access-token-1234567890"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_SHARE_DIR", str(share_dir))
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    api_cfg = _build_provider_auth_kimi_local_api_cfg()

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "Kimi",
        {"enabled": True},
    )

    assert isinstance(client, AgentRuntime)
    assert preset_name == "Kimi"
    assert client.base_url == "https://api.kimi.com/coding/v1"
    assert client.runtime_api_key == "kimi-access-token-1234567890"

    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("hello kimi")],
        chat_id="friend:alice",
        user_text="hello kimi",
        response_metadata={},
        timings={},
    )
    reply = await client.invoke(prepared)

    assert reply == "ok"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_minimax_coding_plan_anthropic_endpoint_for_chat(tmp_path, monkeypatch):
    api_cfg, store = _build_provider_auth_minimax_coding_api_cfg(tmp_path)
    observed = []
    http_client = _ChatProbeHttpClient(
        {
            "type": "message",
            "content": [{"type": "text", "text": "minimax coding ok"}],
            "stop_reason": "end_turn",
        },
        observed,
    )
    monkeypatch.setattr(ai_client_module.AIClient, "_get_http_client", lambda self: http_client)
    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "MiniMax Coding Plan",
        {"enabled": False},
    )

    assert isinstance(client, AIClient)
    assert preset_name == "MiniMax Coding Plan"
    assert client.base_url == "https://api.minimaxi.com/anthropic"
    assert client.auth_transport == "anthropic_native"

    reply = await client.generate_reply("friend:alice", "write a MiniMax test")

    assert reply == "minimax coding ok"
    assert observed[0]["url"] == "https://api.minimaxi.com/anthropic/messages"
    assert observed[0]["headers"]["x-api-key"] == "demo-minimax-coding-key-123456"
    assert observed[0]["json"]["model"] == "MiniMax-M2.5"


@pytest.mark.asyncio
async def test_select_specific_ai_client_uses_minimax_coding_plan_with_agent_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentRuntime, "_load_integrations", _fake_integrations)
    api_cfg, store = _build_provider_auth_minimax_coding_api_cfg(tmp_path)
    observed = []

    class _MinimaxAnthropicAsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            observed.append({"url": url, "headers": headers or {}, "json": json or {}})
            return _ChatProbeResponse(
                {
                    "type": "message",
                    "content": [{"type": "text", "text": "minimax runtime ok"}],
                    "stop_reason": "end_turn",
                }
            )

    monkeypatch.setattr(
        factory_module,
        "hydrate_runtime_settings",
        lambda settings: hydrate_runtime_settings(settings, credential_store=store),
    )
    monkeypatch.setattr("backend.core.agent_runtime.httpx.AsyncClient", _MinimaxAnthropicAsyncClient)

    client, preset_name = await factory_module.select_specific_ai_client(
        api_cfg,
        {},
        "MiniMax Coding Plan",
        {"enabled": True},
    )

    assert isinstance(client, AgentRuntime)
    assert preset_name == "MiniMax Coding Plan"
    assert client.provider_id == "minimax"
    assert client.base_url == "https://api.minimaxi.com/anthropic"
    assert client.runtime_api_key == "demo-minimax-coding-key-123456"
    assert client.auth_transport == "anthropic_native"

    prepared = SimpleNamespace(
        prompt_messages=[_FakeMessage("write a MiniMax test")],
        chat_id="friend:alice",
        user_text="write a MiniMax test",
        response_metadata={},
        timings={},
    )
    reply = await client.invoke(prepared)

    assert reply == "minimax runtime ok"
    assert observed[0]["url"] == "https://api.minimaxi.com/anthropic/messages"
    assert observed[0]["headers"]["x-api-key"] == "demo-minimax-coding-key-123456"
    assert observed[0]["json"]["model"] == "MiniMax-M2.5"


@pytest.mark.asyncio
async def test_select_specific_ai_client_allows_ollama_cloud_model(monkeypatch):
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
    monkeypatch.setattr(
        factory_module,
        "_fetch_ollama_models",
        lambda _base_url, timeout_sec=3.0: [
            {
                "name": "deepseek-v3.2:cloud",
                "model": "deepseek-v3.2:cloud",
                "remote_host": "https://ollama.com:443",
            }
        ],
    )

    client, preset_name = await factory_module.select_specific_ai_client(
        {
            "presets": [
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "",
                    "model": "deepseek-v3.2:cloud",
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
    assert captured["model"] == "deepseek-v3.2:cloud"


@pytest.mark.asyncio
async def test_reconnect_wechat_retries_wcferry_transport(monkeypatch):
    attempts = {"count": 0}

    class _FakeTransportUnavailableError(RuntimeError):
        pass

    class _FakeTransport:
        backend_name = "wcferry"

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
    monkeypatch.setattr(transports_module, "WcferryTransport", _FakeTransport)
    monkeypatch.setattr(transports_module, "TransportUnavailableError", _FakeTransportUnavailableError)

    client = await factory_module.reconnect_wechat(
        "test",
        factory_module.ReconnectPolicy(
            max_retries=3,
            base_delay_sec=0.1,
            max_delay_sec=0.2,
        ),
    )

    assert client is not None
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_memory_manager_background_backlog_persists_across_reopen(tmp_path):
    db_path = tmp_path / "chat_memory.db"
    manager = MemoryManager(str(db_path))
    await manager.initialize()
    await manager.upsert_background_backlog(
        "friend:bob",
        "facts",
        {"user_text": "hi", "assistant_reply": "hello"},
    )
    await manager.close()

    reopened = MemoryManager(str(db_path))
    await reopened.initialize()
    items = await reopened.list_background_backlog()
    stats = await reopened.get_background_backlog_stats()
    await reopened.delete_background_backlog("friend:bob", "facts")
    remaining = await reopened.list_background_backlog()
    await reopened.close()

    assert len(items) == 1
    assert items[0]["chat_id"] == "friend:bob"
    assert items[0]["task_type"] == "facts"
    assert items[0]["payload"] == {"user_text": "hi", "assistant_reply": "hello"}
    assert stats["total"] == 1
    assert stats["by_task_type"] == {"facts": 1}
    assert remaining == []
