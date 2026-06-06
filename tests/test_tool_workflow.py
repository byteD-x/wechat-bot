import asyncio
from types import SimpleNamespace

import pytest

from backend.core.tool_workflow import (
    ControlledToolWorkflowService,
    ToolDefinition,
    ToolRegistry,
)


def _snapshot():
    return SimpleNamespace(
        config={
            "api": {"presets": []},
            "bot": {"system_prompt": "base prompt", "profile_inject_in_prompt": True},
            "logging": {},
            "agent": {},
            "services": {},
        },
        bot={"system_prompt": "base prompt", "profile_inject_in_prompt": True},
    )


async def _readiness():
    return {"success": True, "ready": True}


@pytest.mark.asyncio
async def test_tool_workflow_runs_registered_builtin_tools():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    result = await service.run(
        [
            {"tool": "prompt_preview", "payload": {"sample": {"sender": "Alice", "message": "hi"}}},
            {"tool": "readiness_check"},
        ]
    )

    assert result["success"] is True
    assert [item["tool"] for item in result["trace"]] == ["prompt_preview", "readiness_check"]
    assert result["trace"][0]["schema_valid"] is True
    assert result["trace"][0]["permission"] == "admin_read"
    assert result["trace"][0]["timeout_ms"] > 0
    assert "base prompt" in result["trace"][0]["output"]["prompt"]
    assert result["trace"][1]["output"]["ready"] is True


@pytest.mark.asyncio
async def test_tool_workflow_rejects_schema_invalid_payload():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    result = await service.run(
        [
            {
                "tool": "prompt_preview",
                "payload": {"sample": {"message_count": "not-an-integer"}},
            }
        ]
    )

    assert result["success"] is False
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][0]["schema_valid"] is False
    assert "payload.sample.message_count must be integer" in result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_rejects_unknown_tool_with_error_trace():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    result = await service.run([{"tool": "shell_exec", "payload": {"cmd": "dir"}}])

    assert result["success"] is False
    assert result["trace"][0]["status"] == "error"
    assert "unsupported tool" in result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_enforces_registered_permission():
    async def _handler(payload):
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dangerous_tool",
            payload_schema={"type": "object", "properties": {}, "additionalProperties": False},
            permission="admin_write",
            timeout_sec=1.0,
            handler=_handler,
        )
    )
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        registry=registry,
        allowed_permissions={"admin_read"},
    )

    result = await service.run([{"tool": "dangerous_tool"}])

    assert result["success"] is False
    assert result["trace"][0]["permission"] == "admin_write"
    assert "permission denied" in result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_records_timeout():
    async def _slow_handler(payload):
        await asyncio.sleep(0.05)
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow_tool",
            payload_schema={"type": "object", "properties": {}, "additionalProperties": False},
            permission="admin_read",
            timeout_sec=0.001,
            handler=_slow_handler,
        )
    )
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        registry=registry,
    )

    result = await service.run([{"tool": "slow_tool"}])

    assert result["success"] is False
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][0]["schema_valid"] is True
    assert "timed out" in result["trace"][0]["error"]
