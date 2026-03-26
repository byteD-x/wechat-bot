from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("quart")

from backend.api import app
import backend.api as api_module


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
