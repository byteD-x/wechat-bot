import json

import pytest

from backend.core.ai_client import AIClient


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, payload: dict, observed_payloads: list):
        self._payload = payload
        self._observed_payloads = observed_payloads

    async def post(self, url, headers=None, json=None, timeout=None):
        self._observed_payloads.append(json or {})
        return _FakeResp(self._payload)


class _FakeProbeResp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload, ensure_ascii=False) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class _FastProbeHttpClient:
    def __init__(self, *, get_response, post_response=None, observed_get=None, observed_post=None):
        self._get_response = get_response
        self._post_response = post_response
        self._observed_get = observed_get if observed_get is not None else []
        self._observed_post = observed_post if observed_post is not None else []

    async def get(self, url, headers=None, timeout=None):
        self._observed_get.append({"url": url, "headers": headers, "timeout": timeout})
        return self._get_response

    async def post(self, url, headers=None, json=None, timeout=None):
        self._observed_post.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self._post_response is None:
            raise AssertionError("unexpected post probe")
        return self._post_response


@pytest.mark.asyncio
async def test_ai_client_internal_task_uses_reasoning_content_when_content_empty(monkeypatch):
    observed = []
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "{\"emotion\":\"happy\",\"confidence\":0.9,\"intensity\":4,\"suggested_tone\":\"light\"}",
                }
            }
        ]
    }
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        max_retries=0,
    )
    monkeypatch.setattr(
        client, "_get_http_client", lambda: _FakeHttpClient(payload, observed)
    )

    reply = await client.generate_reply("__emotion__friend:alice", "hello")
    assert reply is not None
    assert "\"emotion\"" in reply


@pytest.mark.asyncio
async def test_ai_client_user_task_does_not_use_reasoning_content_fallback(monkeypatch):
    observed = []
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "{\"emotion\":\"happy\"}",
                }
            }
        ]
    }
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        max_retries=0,
    )
    monkeypatch.setattr(
        client, "_get_http_client", lambda: _FakeHttpClient(payload, observed)
    )

    reply = await client.generate_reply("friend:alice", "hello")
    assert reply is None


@pytest.mark.asyncio
async def test_ai_client_sanitizes_non_positive_token_limits(monkeypatch):
    observed = []
    payload = {
        "choices": [
            {
                "message": {"content": "ok"},
            }
        ]
    }
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        max_retries=0,
        max_tokens="0",
        max_completion_tokens=-1,
    )
    monkeypatch.setattr(
        client, "_get_http_client", lambda: _FakeHttpClient(payload, observed)
    )

    reply = await client.generate_reply("friend:alice", "hello")
    assert reply == "ok"
    assert observed, "expected payload capture"
    sent = observed[0]
    assert "max_tokens" not in sent
    assert "max_completion_tokens" not in sent


@pytest.mark.asyncio
async def test_ai_client_probe_fast_prefers_models_endpoint(monkeypatch):
    observed_get = []
    observed_post = []
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        max_retries=0,
        timeout_sec=20,
    )
    http_client = _FastProbeHttpClient(
        get_response=_FakeProbeResp(200, {"data": [{"id": "test-model"}]}),
        observed_get=observed_get,
        observed_post=observed_post,
    )
    monkeypatch.setattr(client, "_get_http_client", lambda: http_client)

    ok, mode = await client.probe_fast()

    assert ok is True
    assert mode == "models"
    assert observed_get and observed_get[0]["url"].endswith("/models")
    assert observed_post == []


@pytest.mark.asyncio
async def test_ai_client_probe_fast_falls_back_to_completion(monkeypatch):
    observed_post = []
    client = AIClient(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        max_retries=0,
        timeout_sec=20,
    )
    http_client = _FastProbeHttpClient(
        get_response=_FakeProbeResp(404, {"error": "not found"}),
        post_response=_FakeProbeResp(200, {"choices": [{"message": {"content": "ok"}}]}),
        observed_post=observed_post,
    )
    monkeypatch.setattr(client, "_get_http_client", lambda: http_client)

    ok, mode = await client.probe_fast()

    assert ok is True
    assert mode == "completion"
    assert observed_post


@pytest.mark.asyncio
async def test_ai_client_anthropic_native_uses_messages_endpoint_and_headers(monkeypatch):
    observed = []
    payload = {
        "type": "message",
        "content": [{"type": "text", "text": "anthropic ok"}],
        "stop_reason": "end_turn",
    }
    client = AIClient(
        base_url="https://api.anthropic.com/v1",
        api_key="anthropic-test-key",
        auth_transport="anthropic_native",
        model="claude-sonnet-4-5",
        max_retries=0,
    )

    class _AnthropicHttpClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            observed.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return _FakeResp(payload)

    monkeypatch.setattr(client, "_get_http_client", lambda: _AnthropicHttpClient())

    reply = await client.generate_reply("friend:alice", "hello anthropic")

    assert reply == "anthropic ok"
    assert observed[0]["url"].endswith("/messages")
    assert observed[0]["headers"]["x-api-key"] == "anthropic-test-key"
    assert observed[0]["headers"]["anthropic-version"] == "2023-06-01"
    assert observed[0]["json"]["messages"][0]["role"] == "user"
    assert observed[0]["json"]["messages"][0]["content"][0]["text"] == "hello anthropic"


@pytest.mark.asyncio
async def test_ai_client_anthropic_native_refreshes_auth_on_401(monkeypatch):
    observed = []
    auth_state = {"api_key": "anthropic-stale-key", "refresh_calls": 0}

    def _refresh_auth():
        auth_state["refresh_calls"] += 1
        auth_state["api_key"] = "anthropic-fresh-key"

    client = AIClient(
        base_url="https://api.anthropic.com/v1",
        api_key=lambda: auth_state["api_key"],
        auth_transport="anthropic_native",
        auth_refresh_hook=_refresh_auth,
        model="claude-sonnet-4-5",
        max_retries=0,
    )

    class _AnthropicHttpClient:
        def __init__(self):
            self.calls = 0

        async def post(self, url, headers=None, json=None, timeout=None):
            self.calls += 1
            observed.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            if self.calls == 1:
                return _FakeResp({"error": {"message": "expired"}}, status_code=401)
            return _FakeResp({"type": "message", "content": [{"type": "text", "text": "anthropic refreshed"}]})

    http_client = _AnthropicHttpClient()
    monkeypatch.setattr(client, "_get_http_client", lambda: http_client)

    reply = await client.generate_reply("friend:alice", "refresh anthropic")

    assert reply == "anthropic refreshed"
    assert auth_state["refresh_calls"] == 1
    assert observed[0]["headers"]["x-api-key"] == "anthropic-stale-key"
    assert observed[1]["headers"]["x-api-key"] == "anthropic-fresh-key"


@pytest.mark.asyncio
async def test_ai_client_anthropic_probe_fast_uses_messages_mode(monkeypatch):
    observed = []
    client = AIClient(
        base_url="https://api.anthropic.com/v1",
        api_key="anthropic-test-key",
        auth_transport="anthropic_native",
        model="claude-sonnet-4-5",
        max_retries=0,
        timeout_sec=20,
    )

    class _AnthropicHttpClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            observed.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return _FakeResp({"type": "message", "content": [{"type": "text", "text": "pong"}]})

    monkeypatch.setattr(client, "_get_http_client", lambda: _AnthropicHttpClient())

    ok, mode = await client.probe_fast()

    assert ok is True
    assert mode == "messages"
    assert observed[0]["url"].endswith("/messages")


@pytest.mark.asyncio
async def test_ai_client_anthropic_vertex_uses_raw_predict_and_bearer_headers(monkeypatch):
    observed = []
    payload = {
        "type": "message",
        "content": [{"type": "text", "text": "vertex ok"}],
        "stop_reason": "end_turn",
    }
    client = AIClient(
        base_url="https://global-aiplatform.googleapis.com/v1/projects/demo/locations/global/publishers/anthropic/models",
        api_key="ya29.vertex-token",
        auth_transport="anthropic_vertex",
        transport_metadata={"project_id": "demo"},
        model="claude-sonnet-4-0",
        max_retries=0,
    )

    class _VertexHttpClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            observed.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return _FakeResp(payload)

    monkeypatch.setattr(client, "_get_http_client", lambda: _VertexHttpClient())

    reply = await client.generate_reply("friend:alice", "hello vertex")
    ok, mode = await client.probe_fast()

    assert reply == "vertex ok"
    assert ok is True
    assert mode == "rawPredict"
    assert observed[0]["url"].endswith("/claude-sonnet-4@20250514:rawPredict")
    assert observed[0]["headers"]["Authorization"] == "Bearer ya29.vertex-token"
    assert observed[0]["headers"]["X-Goog-User-Project"] == "demo"
    assert observed[0]["json"]["anthropic_version"] == "vertex-2023-10-16"
    assert "model" not in observed[0]["json"]


@pytest.mark.asyncio
async def test_ai_client_codex_oauth_generate_reply_uses_responses_transport(monkeypatch):
    observed = {}
    client = AIClient(
        base_url="https://chatgpt.com/backend-api",
        api_key="codex-access-token",
        auth_transport="openai_codex_responses",
        model="gpt-5.4",
        max_retries=0,
    )

    async def _fake_request(messages, *, timeout_sec=None):
        observed["messages"] = list(messages)
        observed["timeout_sec"] = timeout_sec
        return {
            "content": [{"type": "output_text", "text": "codex ok"}],
            "reasoning_content": [{"type": "output_text", "text": "reasoning"}],
            "finish_reason": "completed",
        }

    monkeypatch.setattr(client, "_request_openai_codex_response", _fake_request)

    reply = await client.generate_reply("friend:alice", "hello codex")
    ok, mode = await client.probe_fast()

    assert reply == "codex ok"
    assert ok is True
    assert mode == "responses"
    assert observed["messages"][-1]["content"] == "ping"


@pytest.mark.asyncio
async def test_ai_client_google_code_assist_generate_reply_uses_native_transport(monkeypatch):
    observed = {}
    client = AIClient(
        base_url="https://cloudcode-pa.googleapis.com",
        api_key="google-access-token",
        auth_transport="google_code_assist",
        transport_metadata={"project_id": "gemini-project-001"},
        model="gemini-2.5-flash",
        max_retries=0,
    )

    async def _fake_request(messages, *, timeout_sec=None):
        observed["messages"] = list(messages)
        observed["timeout_sec"] = timeout_sec
        return {
            "content": [{"type": "text", "text": "gemini ok"}],
            "finish_reason": "STOP",
        }

    monkeypatch.setattr(client, "_request_google_code_assist_response", _fake_request)

    reply = await client.generate_reply("friend:alice", "hello gemini")
    ok, mode = await client.probe_fast()

    assert reply == "gemini ok"
    assert ok is True
    assert mode == "code_assist"
    assert observed["messages"][-1]["content"] == "ping"
