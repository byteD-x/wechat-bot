import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.core.tool_workflow import (
    ControlledToolWorkflowService,
    ToolDefinition,
    ToolRegistry,
    model_tool_calls_to_steps,
)
from backend.core.provider_compat import NormalizedToolCall


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


async def _eval_report():
    return {
        "success": True,
        "name": "smoke-report.json",
        "report": {
            "preset": "smoke",
            "app_version": "1.6.2",
            "generated_at": "2026-06-07T00:00:00Z",
            "summary": {
                "total_cases": 27,
                "passed": True,
                "retrieval_hit_rate": 0.5,
            },
            "regressions": [],
            "cases": [{"id": "should-not-leak"}],
        },
    }


async def _cost_summary(payload):
    return {
        "success": True,
        "filters": {
            "period": payload["period"],
            "include_estimated": payload["include_estimated"],
        },
        "overview": {
            "reply_count": 3,
            "total_tokens": 420,
            "currency_groups": [{"currency": "USD", "total_cost": 0.18}],
        },
        "models": [{"model": "gpt-5-mini"}, {"model": "deepseek-chat"}],
        "review_queue": [{"reply_preview": "should-not-leak"}],
    }


async def _backup_cleanup_preview(payload):
    return {
        "success": True,
        "dry_run": True,
        "keep_policy": {
            "keep_quick": payload["keep_quick"],
            "keep_full": payload["keep_full"],
            "protect_restore_anchor": payload["protect_restore_anchor"],
            "path": "C:/secret/should-not-leak",
        },
        "candidate_count": 2,
        "delete_candidates": [
            {"id": "quick-1", "path": "C:/secret/delete-me"},
            {"id": "quick-2", "path": "E:\\private\\delete-me"},
        ],
        "preserved_backups": [{"id": "full-1", "path": "C:/secret/preserve-me"}],
        "protected_backup_ids": ["restore-anchor"],
        "backups": [{"id": "quick-3", "path": "E:\\private\\backup"}],
        "deleted_targets": [{"path": "C:/secret/deleted-target"}],
        "reclaimable_bytes": 8192,
        "summary": {
            "total_backups": 5,
            "quick_backup_count": 3,
            "full_backup_count": 2,
        },
    }


async def _data_controls_preview(payload):
    return {
        "success": True,
        "dry_run": True,
        "scopes": list(payload["scopes"]),
        "target_count": 3,
        "existing_target_count": 2,
        "unsupported_target_count": 1,
        "reclaimable_bytes": 4096,
        "targets": [
            {"path": "C:/secret/chat_memory.db", "relative_path": "chat_memory.db"},
            {"path": "E:\\private\\vector_db", "relative_path": "vector_db"},
        ],
        "unsupported_targets": [{"path": "C:/secret/unsupported"}],
        "deleted_targets": [{"path": "E:\\private\\deleted"}],
    }


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
async def test_tool_workflow_direct_mode_does_not_return_planning_metadata():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    result = await service.run([{"tool": "readiness_check"}])

    assert result["success"] is True
    assert "planning" not in result
    assert "reflection" not in result
    assert "repair" not in result


@pytest.mark.asyncio
async def test_tool_workflow_runs_readonly_observability_tools():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        eval_report_loader=_eval_report,
        cost_summary_loader=_cost_summary,
    )

    result = await service.run(
        [
            {"tool": "eval_latest"},
            {"tool": "cost_summary", "payload": {"period": "7d", "include_estimated": False}},
        ]
    )

    assert result["success"] is True
    assert [item["tool"] for item in result["trace"]] == ["eval_latest", "cost_summary"]
    eval_output = result["trace"][0]["output"]
    assert eval_output["has_report"] is True
    assert eval_output["name"] == "smoke-report.json"
    assert eval_output["summary"]["total_cases"] == 27
    assert eval_output["regression_count"] == 0
    assert "cases" not in eval_output

    cost_output = result["trace"][1]["output"]
    assert cost_output["filters"]["period"] == "7d"
    assert cost_output["filters"]["include_estimated"] is False
    assert cost_output["overview"]["total_tokens"] == 420
    assert cost_output["model_count"] == 2
    assert cost_output["review_queue_count"] == 1
    assert "review_queue" not in cost_output


def test_tool_workflow_model_tool_schemas_expose_safe_subset_only():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    tools = service.model_tool_schemas()
    names = [item["function"]["name"] for item in tools]

    assert names == [
        "backup_cleanup_dry_run",
        "cost_summary",
        "data_controls_dry_run",
        "eval_latest",
        "readiness_check",
    ]
    assert "prompt_preview" not in names
    assert "config_audit" not in names
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_tool_workflow_converts_model_tool_calls_to_steps():
    calls = [
        NormalizedToolCall(
            id="call_1",
            name="cost_summary",
            arguments='{"period":"7d","include_estimated":false}',
        )
    ]

    steps = model_tool_calls_to_steps(calls)

    assert steps == [
        {
            "tool": "cost_summary",
            "payload": {"period": "7d", "include_estimated": False},
            "tool_call_id": "call_1",
        }
    ]


@pytest.mark.parametrize(
    ("tool_call", "message"),
    [
        (
            NormalizedToolCall(id="call_1", name="shell_exec", arguments='{"cmd":"dir"}'),
            "unsupported model tool",
        ),
        (
            NormalizedToolCall(id="call_2", name="readiness_check", arguments="{broken"),
            "valid JSON",
        ),
        (
            NormalizedToolCall(id="call_3", name="readiness_check", arguments='["not-object"]'),
            "JSON object",
        ),
    ],
)
def test_tool_workflow_rejects_invalid_model_tool_calls(tool_call, message):
    with pytest.raises(ValueError, match=message):
        model_tool_calls_to_steps([tool_call])


@pytest.mark.asyncio
async def test_tool_workflow_runs_maintenance_dry_run_tools_without_leaking_raw_targets():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        backup_cleanup_loader=_backup_cleanup_preview,
        data_controls_loader=_data_controls_preview,
    )

    result = await service.run(
        [
            {
                "tool": "backup_cleanup_dry_run",
                "payload": {"keep_quick": 0, "keep_full": 2, "protect_restore_anchor": False},
            },
            {
                "tool": "data_controls_dry_run",
                "payload": {"scopes": ["memory", "export_rag"]},
            },
        ]
    )

    assert result["success"] is True
    backup_output = result["trace"][0]["output"]
    assert backup_output == {
        "success": True,
        "dry_run": True,
        "keep_policy": {"keep_quick": 0, "keep_full": 2, "protect_restore_anchor": False},
        "candidate_count": 2,
        "preserved_count": 1,
        "protected_count": 1,
        "reclaimable_bytes": 8192,
        "total_backups": 5,
        "quick_backup_count": 3,
        "full_backup_count": 2,
        "deleted_count": 0,
    }

    data_output = result["trace"][1]["output"]
    assert data_output == {
        "success": True,
        "dry_run": True,
        "scopes": ["memory", "export_rag"],
        "target_count": 3,
        "existing_target_count": 2,
        "unsupported_target_count": 1,
        "reclaimable_bytes": 4096,
        "deleted_count": 0,
    }

    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        '"delete_candidates"',
        '"preserved_backups"',
        '"backups"',
        '"targets"',
        '"unsupported_targets"',
        '"path"',
        '"relative_path"',
        "C:/secret",
        "E:\\private",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_tool_workflow_data_controls_dry_run_uses_default_scopes():
    observed = {}

    async def _loader(payload):
        observed["payload"] = payload
        return await _data_controls_preview(payload)

    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        data_controls_loader=_loader,
    )

    result = await service.run([{"tool": "data_controls_dry_run"}])

    assert result["success"] is True
    assert observed["payload"]["scopes"] == ["memory", "usage", "export_rag"]
    assert result["trace"][0]["output"]["scopes"] == ["memory", "usage", "export_rag"]


@pytest.mark.asyncio
async def test_tool_workflow_plan_reflect_repair_repairs_empty_data_control_scopes_once():
    observed = []

    async def _loader(payload):
        observed.append(payload)
        return await _data_controls_preview(payload)

    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        data_controls_loader=_loader,
    )

    result = await service.run(
        [{"tool": "data_controls_dry_run", "payload": {"scopes": []}}],
        workflow_mode="plan_reflect_repair",
    )

    assert result["success"] is True
    assert result["planning"] == {
        "workflow_mode": "plan_reflect_repair",
        "step_count": 1,
        "tools": ["data_controls_dry_run"],
        "max_repair_attempts": 1,
        "repair_policy": "schema_safe_defaults_only",
    }
    assert result["repair"]["attempted"] is True
    assert result["repair"]["count"] == 1
    assert result["repair"]["items"][0]["action"] == "use_default_scopes"
    assert result["reflection"]["status"] == "resolved"
    assert result["reflection"]["items"][0]["repairable"] is True
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][0]["error_type"] == "schema_validation"
    assert result["trace"][1]["status"] == "ok"
    assert result["trace"][1]["repair_attempt"] == 1
    assert result["trace"][1]["repair_of_index"] == 1
    assert result["trace"][1]["output"]["scopes"] == ["memory", "usage", "export_rag"]
    assert observed == [{"scopes": ["memory", "usage", "export_rag"]}]


@pytest.mark.asyncio
async def test_tool_workflow_plan_reflect_repair_never_repairs_more_than_once():
    observed = []

    async def _loader(payload):
        observed.append(payload)
        return await _data_controls_preview(payload)

    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        data_controls_loader=_loader,
    )

    result = await service.run(
        [
            {
                "tool": "data_controls_dry_run",
                "payload": {"scopes": []},
                "continue_on_error": True,
            },
            {"tool": "data_controls_dry_run", "payload": {"scopes": []}},
        ],
        workflow_mode="plan_reflect_repair",
    )

    assert result["success"] is False
    assert result["repair"]["count"] == 1
    assert len([item for item in result["trace"] if item.get("repair_attempt")]) == 1
    assert result["reflection"]["status"] == "blocked"
    assert result["reflection"]["items"][0]["status"] == "resolved"
    assert result["reflection"]["items"][1]["status"] == "blocked"
    assert observed == [{"scopes": ["memory", "usage", "export_rag"]}]


@pytest.mark.asyncio
async def test_tool_workflow_rejects_maintenance_dry_run_unsafe_payloads():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        backup_cleanup_loader=_backup_cleanup_preview,
        data_controls_loader=_data_controls_preview,
    )

    backup_result = await service.run(
        [{"tool": "backup_cleanup_dry_run", "payload": {"apply": True, "backup_id": "b1"}}]
    )
    assert backup_result["success"] is False
    assert backup_result["trace"][0]["error_type"] == "schema_validation"
    assert "payload.apply is not allowed" in backup_result["trace"][0]["error"]
    assert "payload.backup_id is not allowed" in backup_result["trace"][0]["error"]

    empty_scopes_result = await service.run(
        [{"tool": "data_controls_dry_run", "payload": {"scopes": []}}]
    )
    assert empty_scopes_result["success"] is False
    assert empty_scopes_result["trace"][0]["error_type"] == "schema_validation"
    assert "payload.scopes must contain at least 1 item(s)" in empty_scopes_result["trace"][0]["error"]

    unknown_scope_result = await service.run(
        [{"tool": "data_controls_dry_run", "payload": {"scopes": ["memory", "unknown"]}}]
    )
    assert unknown_scope_result["success"] is False
    assert unknown_scope_result["trace"][0]["error_type"] == "schema_validation"
    assert "payload.scopes[1] must be one of: memory, usage, export_rag" in unknown_scope_result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_plan_reflect_repair_does_not_repair_unsafe_payloads():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        backup_cleanup_loader=_backup_cleanup_preview,
        data_controls_loader=_data_controls_preview,
    )

    result = await service.run(
        [
            {
                "tool": "backup_cleanup_dry_run",
                "payload": {"apply": True, "backup_id": "b1"},
            }
        ],
        workflow_mode="plan_reflect_repair",
    )

    assert result["success"] is False
    assert result["repair"]["attempted"] is False
    assert result["repair"]["count"] == 0
    assert result["reflection"]["status"] == "blocked"
    assert result["reflection"]["items"][0]["repairable"] is False
    assert result["trace"][0]["error_type"] == "schema_validation"
    assert "payload.apply is not allowed" in result["trace"][0]["error"]


@pytest.mark.asyncio
async def test_tool_workflow_rejects_cost_summary_extra_payload():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        cost_summary_loader=_cost_summary,
    )

    result = await service.run(
        [
            {
                "tool": "cost_summary",
                "payload": {"period": "30d", "chat_id": "friend:alice"},
            }
        ]
    )

    assert result["success"] is False
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][0]["attempts"] == 0
    assert result["trace"][0]["error_type"] == "schema_validation"
    assert "payload.chat_id is not allowed" in result["trace"][0]["error"]


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
async def test_tool_workflow_plan_reflect_repair_does_not_repair_unknown_tool():
    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
    )

    result = await service.run(
        [{"tool": "shell_exec", "payload": {"cmd": "dir"}}],
        workflow_mode="plan_reflect_repair",
    )

    assert result["success"] is False
    assert result["repair"]["attempted"] is False
    assert result["reflection"]["items"][0]["repairable"] is False
    assert result["trace"][0]["error_type"] == "unsupported_tool"


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
async def test_tool_workflow_plan_reflect_repair_does_not_repair_permission_denied():
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

    result = await service.run(
        [{"tool": "dangerous_tool"}],
        workflow_mode="plan_reflect_repair",
    )

    assert result["success"] is False
    assert result["repair"]["attempted"] is False
    assert result["reflection"]["items"][0]["repairable"] is False
    assert result["trace"][0]["error_type"] == "permission_denied"


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
