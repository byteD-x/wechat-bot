import json
from types import SimpleNamespace

import pytest

from backend.core.mcp_adapter import ReadOnlyMCPAdapter
from backend.core.tool_workflow import ControlledToolWorkflowService


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


async def _data_controls_preview(payload):
    return {
        "success": True,
        "dry_run": True,
        "scopes": list(payload["scopes"]),
        "target_count": 2,
        "existing_target_count": 1,
        "unsupported_target_count": 0,
        "reclaimable_bytes": 4096,
        "targets": [{"path": "C:/secret/chat_memory.db", "relative_path": "chat_memory.db"}],
    }


def _adapter():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        data_controls_loader=_data_controls_preview,
    )
    return ReadOnlyMCPAdapter(service)


@pytest.mark.asyncio
async def test_mcp_adapter_initialize_returns_readonly_tool_capability():
    result = await _adapter().handle(
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {},
        }
    )

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "init-1"
    assert result["result"]["protocolVersion"] == "2025-06-18"
    assert result["result"]["capabilities"] == {"tools": {}}
    assert result["result"]["serverInfo"]["name"] == "wechat-ai-assistant-readonly"


@pytest.mark.asyncio
async def test_mcp_adapter_tools_list_exposes_safe_subset_only():
    result = await _adapter().handle(
        {
            "jsonrpc": "2.0",
            "id": "tools-1",
            "method": "tools/list",
            "params": {},
        }
    )

    names = [item["name"] for item in result["result"]["tools"]]

    assert names == [
        "backup_cleanup_dry_run",
        "cost_summary",
        "data_controls_dry_run",
        "eval_latest",
        "readiness_check",
    ]
    assert "prompt_preview" not in names
    assert "config_audit" not in names
    assert result["result"]["tools"][0]["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_mcp_adapter_tools_call_returns_structured_summary_without_raw_targets():
    result = await _adapter().handle(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "data_controls_dry_run",
                "arguments": {"scopes": ["memory"]},
            },
        }
    )

    payload = result["result"]
    structured = payload["structuredContent"]
    serialized = json.dumps(result, ensure_ascii=False)

    assert payload["content"][0]["type"] == "text"
    assert payload.get("isError") is None
    assert structured["success"] is True
    assert structured["tool"] == "data_controls_dry_run"
    assert structured["output"] == {
        "success": True,
        "dry_run": True,
        "scopes": ["memory"],
        "target_count": 2,
        "existing_target_count": 1,
        "unsupported_target_count": 0,
        "reclaimable_bytes": 4096,
        "deleted_count": 0,
    }
    assert "targets" not in serialized
    assert "C:/secret" not in serialized
    assert "relative_path" not in serialized


@pytest.mark.asyncio
async def test_mcp_adapter_rejects_prompt_preview_and_unknown_tools():
    for name in ("prompt_preview", "config_audit", "shell_exec"):
        result = await _adapter().handle(
            {
                "jsonrpc": "2.0",
                "id": name,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
        )

        payload = result["result"]
        assert payload["isError"] is True
        assert payload["structuredContent"]["success"] is False
        assert payload["structuredContent"]["error"]["type"] == "unsupported_tool"
        assert "unsupported MCP tool" in payload["structuredContent"]["error"]["message"]


@pytest.mark.asyncio
async def test_mcp_adapter_rejects_invalid_arguments_and_method():
    invalid_arguments = await _adapter().handle(
        {
            "jsonrpc": "2.0",
            "id": "bad-args",
            "method": "tools/call",
            "params": {"name": "readiness_check", "arguments": ["not-object"]},
        }
    )
    unknown_method = await _adapter().handle(
        {
            "jsonrpc": "2.0",
            "id": "bad-method",
            "method": "resources/list",
            "params": {},
        }
    )

    assert invalid_arguments["error"]["code"] == -32602
    assert "arguments" in invalid_arguments["error"]["message"]
    assert unknown_method["error"]["code"] == -32601
    assert "unsupported MCP method" in unknown_method["error"]["message"]
