import json
import os
from pathlib import Path

from scripts import run_interview_demo as interview_demo


def _readiness(ready=True):
    return {
        "success": True,
        "ready": ready,
        "blocking_count": 0 if ready else 1,
        "deployment_target": "web-api",
        "summary": {
            "title": "Web API 部署准备已完成" if ready else "Web API 部署还差 1 项准备",
            "detail": "detail",
        },
        "checks": [
            {"key": "python_version", "status": "passed", "blocking": False},
            {"key": "wechat_process", "status": "skipped", "blocking": False},
        ],
    }


def _workflow_payload(passed=True):
    return {
        "success": True,
        "workflow": {
            "success": True,
            "trace": [
                {"index": 1, "tool": "readiness_check", "status": "ok"},
                {"index": 2, "tool": "eval_latest", "status": "ok"},
                {
                    "index": 3,
                    "tool": "data_controls_dry_run",
                    "status": "error",
                    "error_type": "schema_validation",
                },
                {
                    "index": 4,
                    "tool": "data_controls_dry_run",
                    "status": "ok",
                    "repair_attempt": 1,
                },
            ],
            "repair": {"attempted": True},
        },
        "rag": {
            "summary": {
                "total_cases": 5,
                "passed": passed,
                "citation_accuracy": 1.0 if passed else 0.6,
                "context_recall": 1.0,
                "faithfulness": 1.0,
                "answer_citation_binding": 1.0,
                "refusal_accuracy": 1.0,
            },
            "badcase_summary": {
                "badcase_count": 0 if passed else 1,
                "regression_count": 0 if passed else 1,
            },
        },
    }


def _report(passed=True):
    return {
        "summary": {
            "total_cases": 5,
            "passed": passed,
            "citation_accuracy": 1.0 if passed else 0.6,
            "context_recall": 1.0,
            "faithfulness": 1.0,
            "answer_citation_binding": 1.0,
            "refusal_accuracy": 1.0,
        },
        "cases": [],
        "regressions": [] if passed else [{"metric": "citation_accuracy"}],
    }


def test_interview_payload_summarizes_readiness_rag_and_workflow():
    payload = interview_demo.build_interview_payload(
        readiness=_readiness(),
        report_path=Path(interview_demo.PROJECT_ROOT) / "data" / "runtime" / "demo" / "report.json",
        workflow_payload=_workflow_payload(),
        eval_exit_code=0,
    )

    assert payload["success"] is True
    assert payload["artifacts"]["rag_report"].replace("\\", "/") == "data/runtime/demo/report.json"
    assert payload["readiness"]["ready"] is True
    assert payload["rag"]["eval_exit_code"] == 0
    assert payload["rag"]["summary"]["total_cases"] == 5
    assert payload["rag"]["badcase_summary"]["badcase_count"] == 0
    assert payload["workflow"]["trace_steps"] == 4
    assert payload["workflow"]["repair_attempted"] is True
    assert payload["workflow"]["failed_steps"][0]["error_type"] == "schema_validation"

    text = interview_demo.render_interview_demo(payload)
    assert "Interview demo" in text
    assert "readiness: ready" in text
    assert "rag_cases: 5" in text
    assert "rag_eval_exit_code: 0" in text
    assert "workflow_trace_steps: 4" in text
    assert "python scripts/run_interview_demo.py" in text


def test_demo_readiness_temporarily_uses_web_api_target(monkeypatch):
    monkeypatch.setenv(interview_demo.DEPLOYMENT_TARGET_ENV, "desktop")

    def fake_readiness_report(*, config_loader):
        assert os.environ[interview_demo.DEPLOYMENT_TARGET_ENV] == interview_demo.DEPLOYMENT_TARGET_WEB_API
        assert config_loader()["api"]["presets"][0]["api_key"] == "sk-demo-readiness-only"
        return _readiness()

    monkeypatch.setattr(interview_demo, "build_readiness_report", fake_readiness_report)

    report = interview_demo.build_demo_readiness_report()

    assert report["ready"] is True
    assert os.environ[interview_demo.DEPLOYMENT_TARGET_ENV] == "desktop"


def test_interview_demo_main_outputs_json(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "rag-report.json"

    def fake_run_rag_eval(path):
        path.write_text(json.dumps(_report()), encoding="utf-8")
        return 0

    async def fake_build_demo_payload(report):
        assert report["summary"]["total_cases"] == 5
        return _workflow_payload()

    monkeypatch.setattr(interview_demo, "run_rag_eval", fake_run_rag_eval)
    monkeypatch.setattr(interview_demo, "build_demo_readiness_report", lambda: _readiness())
    monkeypatch.setattr(interview_demo, "build_demo_payload", fake_build_demo_payload)

    result = interview_demo.main(["--report", str(report_path), "--json"])

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["success"] is True
    assert output["artifacts"]["rag_report"] == str(report_path)
    assert output["workflow"]["tools"] == [
        "readiness_check",
        "eval_latest",
        "data_controls_dry_run",
        "data_controls_dry_run",
    ]


def test_interview_demo_main_writes_markdown_summary(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "rag-report.json"
    summary_path = tmp_path / "summary.md"

    def fake_run_rag_eval(path):
        path.write_text(json.dumps(_report()), encoding="utf-8")
        return 0

    async def fake_build_demo_payload(report):
        assert report["summary"]["total_cases"] == 5
        return _workflow_payload()

    monkeypatch.setattr(interview_demo, "run_rag_eval", fake_run_rag_eval)
    monkeypatch.setattr(interview_demo, "build_demo_readiness_report", lambda: _readiness())
    monkeypatch.setattr(interview_demo, "build_demo_payload", fake_build_demo_payload)

    result = interview_demo.main(
        [
            "--report",
            str(report_path),
            "--summary",
            str(summary_path),
        ]
    )

    output = capsys.readouterr().out
    summary_text = summary_path.read_text(encoding="utf-8")
    assert result == 0
    assert "summary:" in output
    assert "# 面试演示证据报告" in summary_text
    assert "- 总体状态：通过" in summary_text
    assert "readiness: ready" not in summary_text
    assert "Web API/readiness" in summary_text
    assert "RAG 报告" in summary_text
    assert "data_controls_dry_run" in summary_text


def test_interview_demo_json_includes_summary_artifact(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "rag-report.json"
    summary_path = tmp_path / "summary.md"

    def fake_run_rag_eval(path):
        path.write_text(json.dumps(_report()), encoding="utf-8")
        return 0

    async def fake_build_demo_payload(_report_payload):
        return _workflow_payload()

    monkeypatch.setattr(interview_demo, "run_rag_eval", fake_run_rag_eval)
    monkeypatch.setattr(interview_demo, "build_demo_readiness_report", lambda: _readiness())
    monkeypatch.setattr(interview_demo, "build_demo_payload", fake_build_demo_payload)

    result = interview_demo.main(
        [
            "--report",
            str(report_path),
            "--summary",
            str(summary_path),
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["artifacts"]["summary"] == str(summary_path)
    assert summary_path.exists()


def test_interview_demo_keeps_badcase_evidence_when_eval_fails_with_report(
    monkeypatch, tmp_path, capsys
):
    report_path = tmp_path / "rag-report.json"
    summary_path = tmp_path / "summary.md"

    def fake_run_rag_eval(path):
        path.write_text(json.dumps(_report(passed=False)), encoding="utf-8")
        return 7

    async def fake_build_demo_payload(_report_payload):
        return _workflow_payload(passed=False)

    monkeypatch.setattr(interview_demo, "run_rag_eval", fake_run_rag_eval)
    monkeypatch.setattr(interview_demo, "build_demo_readiness_report", lambda: _readiness())
    monkeypatch.setattr(interview_demo, "build_demo_payload", fake_build_demo_payload)

    result = interview_demo.main(
        [
            "--report",
            str(report_path),
            "--summary",
            str(summary_path),
        ]
    )

    output = capsys.readouterr().out
    summary_text = summary_path.read_text(encoding="utf-8")
    assert result == 1
    assert "rag_eval_exit_code: 7" in output
    assert "rag_passed: False" in output
    assert "badcases: 1" in output
    assert "- eval_exit_code：`7`" in summary_text
    assert "- passed：`False`" in summary_text
    assert "- badcases：`1`" in summary_text


def test_interview_demo_main_returns_eval_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(interview_demo, "run_rag_eval", lambda _path: 7)

    assert interview_demo.main(["--report", str(tmp_path / "missing.json")]) == 7
