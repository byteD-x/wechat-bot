import json

from backend.core.trace_logger import TraceLoggerLite


def _record(logger, *, chat_id="friend:alice", model="test-model", **overrides):
    payload = {
        "event": "invoke",
        "status": "success",
        "chat_id": chat_id,
        "provider_id": "openai",
        "model": model,
        "priority": "foreground",
        "timings": {},
        "metadata": {},
    }
    payload.update(overrides)
    return logger.record(**payload)


def test_trace_logger_keeps_recent_entries_only():
    logger = TraceLoggerLite(max_entries=2)

    _record(logger, status="first", chat_id="friend:first")
    _record(logger, status="second", chat_id="friend:second")
    _record(logger, status="third", chat_id="friend:third")

    status = logger.get_status()

    assert status["count"] == 2
    assert [item["status"] for item in status["recent"]] == ["second", "third"]
    assert status["last"]["status"] == "third"


def test_trace_logger_uses_hash_refs_for_chat_and_model():
    logger = TraceLoggerLite(max_entries=4)
    chat_id = "friend:alice-secret"
    local_root = "\\".join(("C:", "Users", "Example"))
    model_path = "\\".join((local_root, "models", "secret-model.bin"))

    entry = _record(logger, chat_id=chat_id, model=model_path)

    assert entry["chat_ref"] != chat_id
    assert entry["model_ref"] != model_path
    assert len(entry["chat_ref"]) == 16
    assert len(entry["model_ref"]) == 16


def test_trace_logger_does_not_expose_sensitive_metadata_or_paths():
    logger = TraceLoggerLite(max_entries=4)
    local_root = "\\".join(("C:", "Users", "Example"))
    local_path = "\\".join((local_root, "secret.txt"))
    model_path = "\\".join((local_root, "models", "secret-model.bin"))
    route_path = "\\".join((local_root, "route.txt"))

    logger.record(
        event="invoke",
        status="success",
        chat_id="friend:alice-secret",
        provider_id="openai",
        model=model_path,
        priority="foreground",
        timings={
            "invoke_sec": 0.12345,
            "token_count": 999,
            local_path: 2.0,
        },
        metadata={
            "user_text": "my phone is 13800138000",
            "system_prompt": "secret system prompt",
            "prompt_messages": [{"role": "user", "content": "secret prompt message"}],
            "finish_reason": "stop",
            "retrieval": {
                "augmented": True,
                "runtime_hit_count": 2,
                "citations": [{"path": local_path}],
            },
            "model_route": {
                "strategy": route_path,
                "task_complexity": "complex",
                "rag_augmented": True,
            },
            "safety": {
                "action": "allow",
                "reasons": ["secret prompt injection text 13800138000"],
                "pii_detected": True,
            },
            "model_tool_workflow": {
                "success": True,
                "step_count": 1,
                "trace": [
                    {
                        "index": 1,
                        "tool": "cost_summary",
                        "status": "success",
                        "schema_valid": True,
                        "attempts": 1,
                        "output": {"raw": "secret tool output"},
                    }
                ],
            },
            "response_cache": {
                "hit": True,
                "stored": False,
                "user_text_hash": "not-sensitive",
            },
        },
        error=RuntimeError(f"secret error {local_path} credential sample"),
    )

    status = logger.get_status()
    serialized = json.dumps(status, ensure_ascii=False)

    timings = status["last"]["timings"]
    assert timings["invoke_sec"] == 0.1235
    assert len(timings) == 2
    assert next(key for key in timings if key.startswith("metric_")).startswith("metric_")
    assert status["last"]["safety"]["reason_count"] == 1
    assert status["last"]["model_tool"]["trace"] == [
        {
            "index": 1,
            "tool": "cost_summary",
            "status": "success",
            "error_type": "",
            "schema_valid": True,
            "attempts": 1,
        }
    ]
    assert status["last"]["response_cache"] == {"hit": True, "stored": False}
    assert status["last"]["error_type"] == "RuntimeError"
    assert "error_hash" in status["last"]

    for secret in (
        "friend:alice-secret",
        "secret-model.bin",
        "13800138000",
        "secret system prompt",
        "secret prompt message",
        "secret prompt injection text",
        "secret tool output",
        "secret error",
        "credential sample",
        local_root,
        "token_count",
    ):
        assert secret not in serialized


def test_trace_logger_model_tool_summary_omits_tool_output_and_error_text():
    logger = TraceLoggerLite(max_entries=4)

    entry = _record(
        logger,
        metadata={
            "model_tool_workflow": {
                "success": False,
                "error_type": "tool_call_rejected",
                "error": "raw invalid payload with secret text",
                "step_count": 1,
                "trace": [
                    {
                        "index": 1,
                        "tool": "readiness_check",
                        "status": "error",
                        "error_type": "tool_call_rejected",
                        "error": "raw trace error with secret text",
                        "schema_valid": False,
                        "attempts": 0,
                        "output": {"raw": "secret output"},
                    }
                ],
            },
        },
    )

    serialized = json.dumps(entry, ensure_ascii=False)

    assert entry["model_tool"]["success"] is False
    assert entry["model_tool"]["error_type"] == "tool_call_rejected"
    assert entry["model_tool"]["trace"][0]["tool"] == "readiness_check"
    assert entry["model_tool"]["trace"][0]["schema_valid"] is False
    assert "secret output" not in serialized
    assert "raw trace error" not in serialized
    assert "raw invalid payload" not in serialized
