import json
from pathlib import Path

from scripts.summarize_rag_badcases import build_badcase_summary, main, render_text


def test_badcase_summary_reports_clean_rag_eval_as_review_evidence():
    report = {
        "preset": "rag-smoke",
        "generated_at": "2026-06-18T00:00:00+00:00",
        "summary": {
            "total_cases": 1,
            "passed": True,
            "citation_accuracy": 1.0,
            "citation_eval_cases": 1,
            "context_recall": 1.0,
            "faithfulness": 1.0,
            "answer_citation_binding": 1.0,
            "refusal_accuracy": 1.0,
        },
        "cases": [
            {
                "id": "rag-cited-answer",
                "user_text": "release plan?",
                "flags": {"retrieval_hit": True},
                "rag_eval": {
                    "citation_accuracy": 1.0,
                    "context_recall": 1.0,
                    "faithfulness": True,
                    "answer_citation_bound": True,
                },
            }
        ],
        "regressions": [],
    }

    payload = build_badcase_summary(report)
    output = render_text(payload)

    assert payload["passed"] is True
    assert payload["badcase_count"] == 0
    assert payload["category_counts"] == {}
    assert "badcases: 0" in output
    assert "当前报告未发现 badcase" in output


def test_badcase_summary_classifies_rag_failures():
    report = {
        "preset": "rag-regression",
        "generated_at": "2026-06-18T00:00:00+00:00",
        "summary": {
            "total_cases": 3,
            "passed": False,
            "citation_accuracy": 0.0,
            "context_recall": 0.25,
            "faithfulness": 0.0,
            "answer_citation_binding": 0.0,
            "refusal_accuracy": 0.0,
            "runtime_exception_count": 1,
            "empty_reply_rate": 0.3333,
            "retrieval_hit_rate": 0.6667,
        },
        "cases": [
            {
                "id": "bad-citation",
                "user_text": "when is the release?",
                "flags": {"retrieval_hit": True},
                "rag_eval": {
                    "citation_accuracy": 0.0,
                    "context_recall": 0.5,
                    "faithfulness": False,
                    "answer_citation_bound": False,
                },
            },
            {
                "id": "bad-refusal",
                "user_text": "private salary?",
                "flags": {"retrieval_hit": True},
                "rag_eval": {
                    "refusal_match": False,
                    "faithfulness": False,
                },
            },
            {
                "id": "runtime-timeout",
                "user_text": "hello",
                "flags": {
                    "runtime_exception": True,
                    "empty_reply": True,
                    "retrieval_hit": False,
                },
                "runtime_exception": "timeout",
                "rag_eval": {},
            },
        ],
        "regressions": [
            {
                "metric": "citation_accuracy",
                "reason": "citation_accuracy below configured threshold",
            }
        ],
    }

    payload = build_badcase_summary(report)

    assert payload["passed"] is False
    assert payload["badcase_count"] == 3
    assert payload["regression_count"] == 1
    assert payload["category_counts"] == {
        "answer_citation_unbound": 1,
        "citation_mismatch": 1,
        "context_recall_gap": 1,
        "empty_reply": 1,
        "refusal_mismatch": 1,
        "retrieval_miss": 1,
        "runtime_exception": 1,
        "unfaithful_answer": 2,
    }
    assert payload["badcases"][0]["category_labels"] == [
        "引用不匹配",
        "上下文召回不足",
        "忠实度不足",
        "答案未绑定引用",
    ]
    assert any("citation 元数据" in action for action in payload["badcases"][0]["suggested_actions"])


def test_badcase_summary_cli_outputs_json(tmp_path: Path, capsys):
    report_path = tmp_path / "rag-report.json"
    report_path.write_text(
        json.dumps(
            {
                "preset": "rag-smoke",
                "summary": {"total_cases": 0, "passed": True},
                "cases": [],
                "regressions": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = main(["--report", str(report_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["preset"] == "rag-smoke"
    assert payload["badcase_count"] == 0
