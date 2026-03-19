import json

import pytest

from backend.core.ai_client import AIClient


class _FakeResp:
    def __init__(self, payload: dict):
        self.status_code = 200
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
