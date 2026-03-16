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

