import json
from pathlib import Path

from backend.core.eval_runner import evaluate_dataset, write_eval_report


def test_eval_runner_generates_report_and_passes_smoke_dataset(tmp_path: Path):
    dataset_path = Path("tests/fixtures/evals/smoke_cases.json")
    report = evaluate_dataset(dataset_path, preset="smoke")

    assert report["preset"] == "smoke"
    assert report["summary"]["total_cases"] == 20
    assert report["summary"]["passed"] is True
    assert report["summary"]["empty_reply_rate"] == 0.0
    assert report["summary"]["runtime_exception_count"] == 0
    assert report["regressions"] == []

    report_path = tmp_path / "smoke-report.json"
    write_eval_report(report, report_path)
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["summary"]["passed"] is True
    assert persisted["cases"][0]["id"] == report["cases"][0]["id"]


def test_eval_runner_fails_on_empty_reply_and_runtime_exception(tmp_path: Path):
    dataset = {
        "baseline": {
            "short_reply_rate": 0.0,
            "retrieval_hit_rate": 1.0,
        },
        "cases": [
            {
                "id": "bad-case",
                "chat_id": "friend:test",
                "user_text": "hello",
                "assistant_reply": "",
                "retrieval": {"augmented": False},
                "reply_quality": {"user_feedback": "unhelpful"},
                "runtime_exception": "timeout",
            }
        ],
    }
    dataset_path = tmp_path / "bad-eval.json"
    dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    report = evaluate_dataset(dataset_path, preset="regression")

    assert report["summary"]["passed"] is False
    assert report["summary"]["empty_reply_rate"] == 1.0
    assert report["summary"]["runtime_exception_count"] == 1
    metrics = {item["metric"] for item in report["regressions"]}
    assert "empty_reply_rate" in metrics
    assert "runtime_exception_count" in metrics
    assert "retrieval_hit_rate" in metrics
