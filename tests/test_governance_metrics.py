from backend.core.governance_metrics import RuntimeGovernanceMetrics


def test_governance_metrics_aggregates_counts_and_durations():
    metrics = RuntimeGovernanceMetrics()

    metrics.record_prompt_rollback(success=True, duration_ms=10.4)
    metrics.record_prompt_rollback(
        success=False,
        duration_ms=20.0,
        failure_reason="Prompt Revision Not Found",
    )
    metrics.record_tool_workflow(
        success=False,
        duration_ms=-5,
        failure_reason="unsupported tool!",
    )

    status = metrics.get_status()
    assert status["operation_count"] == 2

    rollback = status["operations"]["prompt_rollback"]
    assert rollback["total"] == 2
    assert rollback["success"] == 1
    assert rollback["failure"] == 1
    assert rollback["success_rate"] == 50.0
    assert rollback["last_duration_ms"] == 20.0
    assert rollback["avg_duration_ms"] == 15.2
    assert rollback["failure_reasons"] == {"prompt_revision_not_found": 1}

    workflow = status["operations"]["tool_workflow"]
    assert workflow["total"] == 1
    assert workflow["success"] == 0
    assert workflow["failure"] == 1
    assert workflow["last_duration_ms"] == 0.0
    assert workflow["failure_reasons"] == {"unsupported_tool": 1}


def test_governance_metrics_reset_clears_runtime_only_state():
    metrics = RuntimeGovernanceMetrics()
    metrics.record_tool_workflow(success=True, duration_ms=1.0)

    metrics.reset()

    assert metrics.get_status() == {"operations": {}, "operation_count": 0}
