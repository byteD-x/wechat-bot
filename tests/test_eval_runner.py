import json
from pathlib import Path

from backend.core.eval_runner import evaluate_dataset, write_eval_report


def test_eval_runner_generates_report_and_passes_smoke_dataset(tmp_path: Path):
    dataset_path = Path("tests/fixtures/evals/smoke_cases.json")
    report = evaluate_dataset(dataset_path, preset="smoke")

    assert report["preset"] == "smoke"
    assert report["summary"]["total_cases"] == 27
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


def test_eval_runner_reports_rag_quality_metrics():
    dataset_path = Path("tests/fixtures/evals/rag_cases.json")
    report = evaluate_dataset(dataset_path, preset="rag-smoke")

    assert report["summary"]["passed"] is True
    assert report["summary"]["total_cases"] == 5
    assert report["summary"]["citation_accuracy"] == 1.0
    assert report["summary"]["citation_eval_cases"] == 3
    assert report["summary"]["context_recall"] == 1.0
    assert report["summary"]["faithfulness"] == 1.0
    assert report["summary"]["answer_citation_binding"] == 1.0
    assert report["summary"]["answer_citation_binding_eval_cases"] == 3
    assert report["summary"]["refusal_accuracy"] == 1.0
    assert report["summary"]["refusal_eval_cases"] == 2
    assert report["regressions"] == []
    assert report["cases"][0]["rag_eval"]["matched_evidence"]
    assert report["cases"][0]["rag_eval"]["answer_citation_bound"] is True


def test_eval_runner_fails_rag_metric_thresholds(tmp_path: Path):
    dataset = {
        "thresholds": {
            "citation_accuracy": 0.8,
            "context_recall": 0.8,
            "faithfulness": 0.8,
            "answer_citation_binding": 1.0,
            "refusal_accuracy": 1.0,
        },
        "cases": [
            {
                "id": "bad-citation",
                "chat_id": "friend:test",
                "user_text": "what is the answer?",
                "assistant_reply": "The answer is not grounded.",
                "retrieval": {
                    "augmented": True,
                    "citations": [
                        {
                            "citation_id": "wrong-citation",
                            "doc_id": "wrong-doc",
                            "chunk_id": "wrong-chunk",
                        }
                    ],
                },
                "expected_citation_ids": ["expected-citation"],
                "expected_doc_ids": ["expected-doc"],
            },
            {
                "id": "missing-answer-citation-binding",
                "chat_id": "friend:test",
                "user_text": "when is the release?",
                "assistant_reply": "The release happens after QA signoff.",
                "retrieval": {
                    "augmented": True,
                    "citations": [
                        {
                            "citation_id": "expected-citation",
                            "doc_id": "expected-doc",
                            "chunk_id": "expected-chunk",
                        }
                    ],
                },
                "expected_citation_ids": ["expected-citation"],
                "expected_doc_ids": ["expected-doc"],
                "expected_chunk_ids": ["expected-chunk"],
            },
            {
                "id": "bad-refusal",
                "chat_id": "friend:test",
                "user_text": "unsupported question",
                "assistant_reply": "Unsupported answer.",
                "retrieval": {"augmented": True, "citations": []},
                "safety": {"action": "allow"},
                "unsupported_answer": True,
            },
        ],
    }
    dataset_path = tmp_path / "bad-rag-eval.json"
    dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    report = evaluate_dataset(dataset_path, preset="rag-regression")

    assert report["summary"]["passed"] is False
    metrics = {item["metric"] for item in report["regressions"]}
    assert "citation_accuracy" in metrics
    assert "context_recall" in metrics
    assert "faithfulness" in metrics
    assert "answer_citation_binding" in metrics
    assert "refusal_accuracy" in metrics
