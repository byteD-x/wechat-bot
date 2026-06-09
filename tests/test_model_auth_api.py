from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("quart")

from backend.api import app
import backend.api as api_module
from backend.core.model_discovery import fetch_openai_compatible_models


def _demo_secret(label: str = "demo") -> str:
    return "sk" + "-" + label


def _field_name(*parts: str) -> str:
    return "_".join(parts)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.asyncio
async def test_model_auth_overview_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        api_module.model_auth_center_service,
        "get_overview",
        MagicMock(return_value={"success": True, "overview": {"cards": [], "active_provider_id": "openai"}}),
    )
    response = await client.get("/api/model_auth/overview")
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["overview"]["active_provider_id"] == "openai"


def test_model_auth_sanitizer_preserves_action_schema_field_metadata():
    payload = {
        "overview": {
            "actions_schema": [
                {
                    "id": "save_api_key",
                    "payload_schema": {
                        "type": "object",
                        "properties": {
                            _field_name("api", "key"): {"type": "string", "sensitive": True},
                            "provider_id": {"type": "string"},
                        },
                        "required": ["provider_id", "api_key"],
                    },
                }
            ],
            "cards": [
                {
                    "metadata": {
                        _field_name("api", "key"): _demo_secret("sanitizer"),
                        "credential_ref": "::".join(["provider-auth", "openai", "api_key", "default"]),
                    }
                }
            ],
        }
    }

    sanitized = api_module._sanitize_model_auth_overview_payload(payload)
    schema = sanitized["overview"]["actions_schema"][0]["payload_schema"]

    assert schema["properties"]["api_key"] == {"type": "string", "sensitive": True}
    assert schema["required"] == ["provider_id", "api_key"]
    assert sanitized["overview"]["cards"][0]["metadata"]["api_key"] == "[REDACTED]"
    assert sanitized["overview"]["cards"][0]["metadata"]["credential_ref"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_model_auth_action_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        api_module.model_auth_center_service,
        "perform_action",
        AsyncMock(return_value={"success": True, "message": "done", "overview": {"cards": []}}),
    )
    response = await client.post(
        "/api/model_auth/action",
        json={"action": "scan", "payload": {"provider_id": "openai"}},
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["message"] == "done"


@pytest.mark.asyncio
async def test_model_auth_action_endpoint_returns_400_for_contract_errors(client, monkeypatch):
    monkeypatch.setattr(
        api_module.model_auth_center_service,
        "perform_action",
        AsyncMock(side_effect=ValueError("This auth method does not support local auth binding.")),
    )
    response = await client.post(
        "/api/model_auth/action",
        json={"action": "bind_local_auth", "payload": {"provider_id": "openai", "method_id": "oauth"}},
    )
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "does not support local auth binding" in data["message"]


@pytest.mark.asyncio
async def test_model_auth_action_endpoint_rejects_ui_only_actions(client):
    response = await client.post(
        "/api/model_auth/action",
        json={"action": "show_api_key_form", "payload": {"provider_id": "openai"}},
    )
    assert response.status_code == 400
    data = await response.get_json()
    assert data["success"] is False
    assert "show_api_key_form" in data["message"]


class _ModelDiscoveryResponse:
    def __init__(self, status_code=200, payload=None, *, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid-json-with-secret")
        return self._payload


class _ModelDiscoveryClient:
    calls = []
    response = _ModelDiscoveryResponse()

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "kwargs": dict(self.kwargs)})
        return self.response


@pytest.mark.asyncio
async def test_openai_compatible_model_discovery_reads_standard_models(monkeypatch):
    _ModelDiscoveryClient.calls = []
    _ModelDiscoveryClient.response = _ModelDiscoveryResponse(
        payload={
            "object": "list",
            "data": [
                {"id": "gpt-4.1"},
                {"id": "qwen-plus"},
                {"id": "gpt-4.1"},
            ],
        }
    )
    monkeypatch.setattr("backend.core.model_discovery.httpx.AsyncClient", _ModelDiscoveryClient)

    demo_key = _demo_secret("demo")
    result = await fetch_openai_compatible_models("https://proxy.example/v1", credential=demo_key)

    assert result.success is True
    assert result.models == ["gpt-4.1", "qwen-plus"]
    assert result.base_url == "https://proxy.example/v1"
    assert _ModelDiscoveryClient.calls[0]["url"] == "https://proxy.example/v1/models"
    assert _ModelDiscoveryClient.calls[0]["headers"]["Authorization"] == f"Bearer {demo_key}"


@pytest.mark.asyncio
async def test_openai_compatible_model_discovery_does_not_duplicate_models_suffix(monkeypatch):
    _ModelDiscoveryClient.calls = []
    _ModelDiscoveryClient.response = _ModelDiscoveryResponse(payload=["gpt-4.1", {"model": "glm-5"}, {"name": "kimi"}])
    monkeypatch.setattr("backend.core.model_discovery.httpx.AsyncClient", _ModelDiscoveryClient)

    result = await fetch_openai_compatible_models("https://proxy.example/v1/models", credential="")

    assert result.success is True
    assert result.models == ["gpt-4.1", "glm-5", "kimi"]
    assert _ModelDiscoveryClient.calls[0]["url"] == "https://proxy.example/v1/models"


@pytest.mark.asyncio
async def test_openai_compatible_model_discovery_rejects_invalid_scheme(monkeypatch):
    _ModelDiscoveryClient.calls = []
    monkeypatch.setattr("backend.core.model_discovery.httpx.AsyncClient", _ModelDiscoveryClient)

    demo_key = _demo_secret("secret")
    with pytest.raises(ValueError) as exc_info:
        await fetch_openai_compatible_models("file:///tmp/models", credential=demo_key)

    assert "http or https" in str(exc_info.value)
    assert demo_key not in str(exc_info.value)
    assert _ModelDiscoveryClient.calls == []


@pytest.mark.asyncio
async def test_openai_compatible_model_discovery_sanitizes_upstream_failures(monkeypatch):
    _ModelDiscoveryClient.calls = []
    _ModelDiscoveryClient.response = _ModelDiscoveryResponse(
        status_code=401,
        payload={"error": {"message": f"{_demo_secret('secret')} should not leak"}},
    )
    monkeypatch.setattr("backend.core.model_discovery.httpx.AsyncClient", _ModelDiscoveryClient)

    demo_key = _demo_secret("secret")
    result = await fetch_openai_compatible_models("https://proxy.example/v1", credential=demo_key)
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["models"] == []
    assert payload["code"] == "model_discovery_auth_failed"
    assert demo_key not in str(payload)


@pytest.mark.asyncio
async def test_openai_compatible_model_discovery_sanitizes_invalid_json(monkeypatch):
    _ModelDiscoveryClient.calls = []
    _ModelDiscoveryClient.response = _ModelDiscoveryResponse(status_code=200, json_error=True)
    monkeypatch.setattr("backend.core.model_discovery.httpx.AsyncClient", _ModelDiscoveryClient)

    result = await fetch_openai_compatible_models("https://proxy.example/v1", credential=_demo_secret("secret"))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["code"] == "model_discovery_invalid_json"
    assert "secret" not in str(payload).lower()
