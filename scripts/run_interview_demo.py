#!/usr/bin/env python3
"""Run a one-command interview demo without starting WeChat or the Web API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = PROJECT_ROOT / "data" / "runtime" / "demo" / "interview-rag-report.json"
DEFAULT_SUMMARY = PROJECT_ROOT / "data" / "runtime" / "demo" / "interview-demo-summary.md"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.readiness import (  # noqa: E402
    DEPLOYMENT_TARGET_ENV,
    DEPLOYMENT_TARGET_WEB_API,
    build_readiness_report,
)
from backend.wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION  # noqa: E402
from scripts.run_tool_workflow_demo import (  # noqa: E402
    build_demo_payload,
    load_eval_report,
    run_rag_eval,
)


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


@contextmanager
def _temporary_web_api_target() -> Iterator[None]:
    previous = os.environ.get(DEPLOYMENT_TARGET_ENV)
    os.environ[DEPLOYMENT_TARGET_ENV] = DEPLOYMENT_TARGET_WEB_API
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(DEPLOYMENT_TARGET_ENV, None)
        else:
            os.environ[DEPLOYMENT_TARGET_ENV] = previous


def _demo_config() -> Dict[str, Any]:
    return {
        "bot": {
            "required_wechat_version": OFFICIAL_SUPPORTED_WECHAT_VERSION,
            "silent_mode_required": True,
        },
        "api": {
            "presets": [
                {
                    "name": "Interview Demo",
                    "provider": "openai",
                    "api_key": "sk-demo-readiness-only",
                }
            ]
        },
    }


def build_demo_readiness_report() -> Dict[str, Any]:
    with _temporary_web_api_target():
        return build_readiness_report(config_loader=_demo_config)


def _summarize_readiness(report: Dict[str, Any]) -> Dict[str, Any]:
    checks = [
        {
            "key": str(check.get("key") or ""),
            "status": str(check.get("status") or ""),
            "blocking": bool(check.get("blocking")),
        }
        for check in list(report.get("checks") or [])
    ]
    return {
        "ready": bool(report.get("ready")),
        "blocking_count": int(report.get("blocking_count") or 0),
        "deployment_target": str(report.get("deployment_target") or ""),
        "summary": dict(report.get("summary") or {}),
        "checks": checks,
    }


def build_interview_payload(
    *,
    readiness: Dict[str, Any],
    report_path: Path,
    workflow_payload: Dict[str, Any],
    eval_exit_code: int = 0,
) -> Dict[str, Any]:
    rag = dict(workflow_payload.get("rag") or {})
    rag_summary = dict(rag.get("summary") or {})
    badcase_summary = dict(rag.get("badcase_summary") or {})
    workflow = dict(workflow_payload.get("workflow") or {})
    trace = list(workflow.get("trace") or [])
    repair = dict(workflow.get("repair") or {})

    readiness_summary = _summarize_readiness(readiness)
    rag_passed = bool(rag_summary.get("passed"))
    workflow_ok = bool(workflow_payload.get("success")) and bool(workflow.get("success"))
    success = bool(readiness_summary.get("ready")) and rag_passed and workflow_ok

    return {
        "success": success,
        "artifacts": {
            "rag_report": _relative_path(report_path),
        },
        "readiness": readiness_summary,
        "rag": {
            "eval_exit_code": int(eval_exit_code),
            "summary": rag_summary,
            "badcase_summary": badcase_summary,
        },
        "workflow": {
            "success": bool(workflow.get("success")),
            "trace_steps": len(trace),
            "tools": [str(step.get("tool") or "") for step in trace if isinstance(step, dict)],
            "repair_attempted": bool(repair.get("attempted")),
            "failed_steps": [
                {
                    "index": step.get("index"),
                    "tool": step.get("tool"),
                    "error_type": step.get("error_type"),
                }
                for step in trace
                if isinstance(step, dict) and step.get("status") != "ok"
            ],
        },
        "interview_talking_points": [
            "Web API readiness 证明后端治理切片可在不接入微信桌面的情况下自检。",
            "RAG eval 同时覆盖引用、召回、忠实度、引用绑定和拒答指标。",
            "badcase summary 把失败样例转成可复盘、可回归的工程动作。",
            "Tool Workflow trace 展示白名单工具、逐步可观测和 schema-safe repair 边界。",
        ],
    }


def render_interview_demo(payload: Dict[str, Any]) -> str:
    readiness = dict(payload.get("readiness") or {})
    rag = dict(payload.get("rag") or {})
    rag_summary = dict(rag.get("summary") or {})
    badcase_summary = dict(rag.get("badcase_summary") or {})
    workflow = dict(payload.get("workflow") or {})
    artifacts = dict(payload.get("artifacts") or {})

    lines = [
        "Interview demo",
        "-" * 50,
        f"status: {'ok' if payload.get('success') else 'failed'}",
        (
            "readiness: "
            f"{'ready' if readiness.get('ready') else 'blocked'} "
            f"(target={readiness.get('deployment_target')}, "
            f"blocking={readiness.get('blocking_count')})"
        ),
        f"rag_cases: {rag_summary.get('total_cases', 0)}",
        f"rag_eval_exit_code: {rag.get('eval_exit_code', 0)}",
        f"rag_passed: {bool(rag_summary.get('passed'))}",
        f"citation_accuracy: {rag_summary.get('citation_accuracy')}",
        f"context_recall: {rag_summary.get('context_recall')}",
        f"faithfulness: {rag_summary.get('faithfulness')}",
        f"answer_citation_binding: {rag_summary.get('answer_citation_binding')}",
        f"refusal_accuracy: {rag_summary.get('refusal_accuracy')}",
        f"badcases: {badcase_summary.get('badcase_count', 0)}",
        f"workflow: {'ok' if workflow.get('success') else 'failed'}",
        f"workflow_trace_steps: {workflow.get('trace_steps', 0)}",
        f"repair_attempted: {bool(workflow.get('repair_attempted'))}",
        f"rag_report: {artifacts.get('rag_report')}",
        "",
        "interview flow:",
        "1. 先说明 web-api readiness 是离线治理切片，不承诺微信桌面收发。",
        "2. 再讲 RAG eval 的引用、召回、忠实度、引用绑定和拒答指标。",
        "3. 接着用 badcase 数量说明当前评测是否需要复盘。",
        "4. 最后用 Tool Workflow trace 讲白名单、可观测和受控 repair。",
        "",
        "command:",
        "python scripts/run_interview_demo.py",
    ]
    return "\n".join(lines)


def render_markdown_summary(payload: Dict[str, Any]) -> str:
    readiness = dict(payload.get("readiness") or {})
    rag = dict(payload.get("rag") or {})
    rag_summary = dict(rag.get("summary") or {})
    badcase_summary = dict(rag.get("badcase_summary") or {})
    workflow = dict(payload.get("workflow") or {})
    artifacts = dict(payload.get("artifacts") or {})
    talking_points = list(payload.get("interview_talking_points") or [])

    status_text = "通过" if payload.get("success") else "未通过"
    lines = [
        "# 面试演示证据报告",
        "",
        f"- 总体状态：{status_text}",
        f"- RAG 报告：`{artifacts.get('rag_report')}`",
        "- 演示边界：仅验证 Web API/readiness、离线 RAG eval、badcase summary 与受控 Tool Workflow；不代表真实微信桌面收发已完成。",
        "",
        "## Readiness",
        "",
        f"- deployment_target：`{readiness.get('deployment_target')}`",
        f"- ready：`{bool(readiness.get('ready'))}`",
        f"- blocking_count：`{readiness.get('blocking_count')}`",
        "",
        "## RAG Eval",
        "",
        f"- cases：`{rag_summary.get('total_cases', 0)}`",
        f"- eval_exit_code：`{rag.get('eval_exit_code', 0)}`",
        f"- passed：`{bool(rag_summary.get('passed'))}`",
        f"- citation_accuracy：`{rag_summary.get('citation_accuracy')}`",
        f"- context_recall：`{rag_summary.get('context_recall')}`",
        f"- faithfulness：`{rag_summary.get('faithfulness')}`",
        f"- answer_citation_binding：`{rag_summary.get('answer_citation_binding')}`",
        f"- refusal_accuracy：`{rag_summary.get('refusal_accuracy')}`",
        f"- badcases：`{badcase_summary.get('badcase_count', 0)}`",
        "",
        "## Tool Workflow",
        "",
        f"- success：`{bool(workflow.get('success'))}`",
        f"- trace_steps：`{workflow.get('trace_steps', 0)}`",
        f"- tools：`{', '.join(workflow.get('tools') or [])}`",
        f"- repair_attempted：`{bool(workflow.get('repair_attempted'))}`",
        "",
        "## 面试讲法",
        "",
    ]
    for item in talking_points:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 可复现命令",
            "",
            "```powershell",
            ".\\.venv\\Scripts\\python.exe scripts\\run_interview_demo.py --summary data\\runtime\\demo\\interview-demo-summary.md",
            "```",
            "",
            "## 不夸大的边界",
            "",
            "- 不读取真实聊天内容。",
            "- 不访问真实微信进程。",
            "- 不执行任意 shell、任意 HTTP、文件写入或动态插件。",
            "- 不替代 Windows + 微信 PC `3.9.12.51` 的人工收发验证。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local interview demo.")
    parser.add_argument(
        "--report",
        default=str(DEFAULT_REPORT),
        help="Output path for the generated RAG eval report.",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Reuse --report if it already exists instead of running RAG eval first.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--summary",
        nargs="?",
        const=str(DEFAULT_SUMMARY),
        help="Write a Markdown evidence summary. Defaults to data/runtime/demo/interview-demo-summary.md when no path is provided.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_path = Path(args.report).expanduser().resolve()
    eval_exit_code = 0
    if not bool(args.skip_eval) or not report_path.exists():
        eval_exit_code = run_rag_eval(report_path)
        if eval_exit_code != 0 and not report_path.exists():
            return eval_exit_code
    if not report_path.exists():
        print(f"RAG eval report not found: {report_path}", file=sys.stderr)
        return 1

    readiness = build_demo_readiness_report()
    workflow_payload = asyncio.run(build_demo_payload(load_eval_report(report_path)))
    payload = build_interview_payload(
        readiness=readiness,
        report_path=report_path,
        workflow_payload=workflow_payload,
        eval_exit_code=eval_exit_code,
    )
    summary_path: Path | None = None
    if args.summary:
        summary_path = Path(str(args.summary)).expanduser().resolve()
        payload.setdefault("artifacts", {})["summary"] = _relative_path(summary_path)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_interview_demo(payload))
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(render_markdown_summary(payload), encoding="utf-8")
        if not args.json:
            print(f"summary: {_relative_path(summary_path)}")
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
