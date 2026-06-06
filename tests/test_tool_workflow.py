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
    assert result["trace"][0]["attempts"] == 1
    assert result["trace"][0]["retry_count"] == 0
    assert "base prompt" in result["trace"][0]["output"]["prompt"]
    assert result["trace"][1]["retry_count"] == 1
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
    assert result["trace"][0]["attempts"] == 0
    assert result["trace"][0]["error_type"] == "schema_validation"
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
    assert result["trace"][0]["attempts"] == 0
    assert result["trace"][0]["error_type"] == "unsupported_tool"
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
    assert result["trace"][0]["attempts"] == 0
    assert result["trace"][0]["error_type"] == "permission_denied"
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
            retry_count=1,
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
    assert result["trace"][0]["attempts"] == 2
    assert result["trace"][0]["retry_count"] == 1
    assert result["trace"][0]["error_type"] == "timeout"
    assert "timed out" in result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_retries_flaky_registered_tool():
    attempts = {"count": 0}

    async def _flaky_handler(payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return {"ok": True, "attempt": attempts["count"]}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="flaky_tool",
            payload_schema={"type": "object", "properties": {}, "additionalProperties": False},
            permission="admin_read",
            timeout_sec=1.0,
            handler=_flaky_handler,
            retry_count=1,
        )
    )
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        registry=registry,
    )

    result = await service.run([{"tool": "flaky_tool"}])

    assert result["success"] is True
    assert attempts["count"] == 2
    assert result["trace"][0]["status"] == "ok"
    assert result["trace"][0]["attempts"] == 2
    assert result["trace"][0]["retry_count"] == 1
    assert result["trace"][0]["output"] == {"ok": True, "attempt": 2}


@pytest.mark.asyncio
async def test_tool_workflow_does_not_retry_schema_invalid_custom_tool():
    attempts = {"count": 0}

    async def _handler(payload):
        attempts["count"] += 1
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="schema_tool",
            payload_schema={
                "type": "object",
                "properties": {"required_value": {"type": "string"}},
                "required": ["required_value"],
                "additionalProperties": False,
            },
            permission="admin_read",
            timeout_sec=1.0,
            handler=_handler,
            retry_count=2,
        )
    )
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        registry=registry,
    )

    result = await service.run([{"tool": "schema_tool", "payload": {}}])

    assert result["success"] is False
    assert attempts["count"] == 0
    assert result["trace"][0]["attempts"] == 0
    assert result["trace"][0]["retry_count"] == 2
    assert result["trace"][0]["error_type"] == "schema_validation"
