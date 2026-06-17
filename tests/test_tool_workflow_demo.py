import json

import pytest

from scripts.run_tool_workflow_demo import build_demo_payload, render_demo


def _rag_report(passed=True):
    return {
        "preset": "tool-workflow-rag-demo",
        "generated_at": "2026-06-18T00:00:00+00:00",
        "summary": {
            "total_cases": 2,
            "passed": passed,
            "citation_accuracy": 1.0 if passed else 0.5,
            "context_recall": 1.0 if passed else 0.5,
            "faithfulness": 1.0 if passed else 0.5,
            "answer_citation_binding": 1.0 if passed else 0.0,
            "refusal_accuracy": 1.0,
            "runtime_exception_count": 0,
            "empty_reply_rate": 0.0,
            "retrieval_hit_rate": 1.0,
        },
        "cases": [
            {
                "id": "ok-rag",
                "user_text": "release plan?",
                "flags": {"retrieval_hit": True},
                "rag_eval": {
                    "citation_accuracy": 1.0,
                    "context_recall": 1.0,
                    "faithfulness": True,
                    "answer_citation_bound": True,
                },
            },
            {
                "id": "bad-citation",
                "user_text": "when is the release?",
                "flags": {"retrieval_hit": True},
                "rag_eval": {
                    "citation_accuracy": 1.0 if passed else 0.0,
                    "context_recall": 1.0 if passed else 0.5,
                    "faithfulness": True if passed else False,
                    "answer_citation_bound": True if passed else False,
                },
            },
        ],
        "regressions": []
        if passed
        else [
            {
                "metric": "citation_accuracy",
                "reason": "citation_accuracy below configured threshold",
            }
        ],
    }


@pytest.mark.asyncio
async def test_tool_workflow_demo_builds_repair_trace_for_clean_report():
    payload = await build_demo_payload(_rag_report(passed=True))

    assert payload["success"] is True
    workflow = payload["workflow"]
    assert workflow["success"] is True
    assert workflow["planning"]["workflow_mode"] == "plan_reflect_repair"
    assert workflow["repair"]["attempted"] is True
    assert workflow["repair"]["items"][0]["action"] == "use_default_scopes"
    assert [item["tool"] for item in workflow["trace"]] == [
        "readiness_check",
        "eval_latest",
        "cost_summary",
        "data_controls_dry_run",
        "data_controls_dry_run",
    ]
    assert workflow["trace"][3]["status"] == "error"
    assert workflow["trace"][3]["error_type"] == "schema_validation"
    assert workflow["trace"][4]["status"] == "ok"
    assert workflow["trace"][4]["repair_attempt"] == 1

    eval_output = workflow["trace"][1]["output"]
    assert eval_output["summary"]["total_cases"] == 2
    assert "cases" not in eval_output

    cost_output = workflow["trace"][2]["output"]
    assert cost_output["review_queue_count"] == 0
    assert "review_queue" not in cost_output
    assert payload["rag"]["badcase_summary"]["badcase_count"] == 0


@pytest.mark.asyncio
async def test_tool_workflow_demo_surfaces_badcase_count_without_raw_queue():
    payload = await build_demo_payload(_rag_report(passed=False))

    workflow = payload["workflow"]
    assert payload["success"] is True
    assert payload["rag"]["badcase_summary"]["badcase_count"] == 1
    assert workflow["trace"][2]["output"]["review_queue_count"] == 1
    serialized = json.dumps(workflow, ensure_ascii=False)
    assert '"review_queue":' not in serialized
    assert "bad-citation" not in serialized

    text = render_demo(payload)
    assert "workflow: ok" in text
    assert "badcases: 1" in text
    assert "白名单工具只返回摘要" in text
    assert "plan_reflect_repair" in text
