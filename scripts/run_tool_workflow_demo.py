#!/usr/bin/env python3
"""Run a local Agent Tool Workflow demo for interviews and regression checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "tests" / "fixtures" / "evals" / "rag_cases.json"
DEFAULT_REPORT = PROJECT_ROOT / "data" / "runtime" / "demo" / "tool-workflow-rag-report.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.tool_workflow import ControlledToolWorkflowService
from scripts.summarize_rag_badcases import build_badcase_summary


def _snapshot() -> SimpleNamespace:
    config = {
        "api": {"presets": []},
        "bot": {
            "system_prompt": "你是本地微信 AI 助手，回答必须尊重证据和安全边界。",
            "profile_inject_in_prompt": True,
        },
        "logging": {},
        "agent": {
            "model_tool_calls_enabled": False,
            "retriever_hybrid_enabled": True,
        },
        "services": {},
    }
    return SimpleNamespace(
        config=config,
        api=config["api"],
        bot=config["bot"],
        logging=config["logging"],
        agent=config["agent"],
        services=config["services"],
    )


def run_rag_eval(report_path: Path) -> int:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(PROJECT_ROOT / "run.py"),
        "eval",
        "--dataset",
        str(DATASET),
        "--preset",
        "tool-workflow-rag-demo",
        "--report",
        str(report_path),
    ]
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return int(completed.returncode)


def load_eval_report(report_path: Path) -> Dict[str, Any]:
    return json.loads(report_path.read_text(encoding="utf-8"))


async def build_demo_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    badcase_summary = build_badcase_summary(report)

    async def _readiness() -> Dict[str, Any]:
        return {
            "success": True,
            "ready": True,
            "mode": "offline_demo",
            "checks": [
                {
                    "key": "rag_eval_report",
                    "status": "passed" if report.get("summary", {}).get("passed") else "failed",
                    "label": "RAG eval report",
                    "message": "RAG eval report is available for workflow demo.",
                    "blocking": False,
                }
            ],
        }

    async def _eval_report() -> Dict[str, Any]:
        return {
            "success": True,
            "name": "tool-workflow-rag-report.json",
            "report": report,
        }

    async def _cost_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "filters": {
                "period": str(payload.get("period") or "30d"),
                "include_estimated": bool(payload.get("include_estimated", True)),
            },
            "overview": {
                "reply_count": int(report.get("summary", {}).get("total_cases") or 0),
                "total_tokens": 0,
                "estimated": False,
                "note": "offline demo does not read real usage or cost records",
            },
            "models": [],
            "review_queue": [
                {"id": item.get("id"), "categories": item.get("categories")}
                for item in badcase_summary.get("badcases", [])
            ],
        }

    async def _data_controls_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else ["memory", "usage", "export_rag"]
        return {
            "success": True,
            "dry_run": True,
            "scopes": list(scopes),
            "target_count": len(list(scopes)),
            "existing_target_count": 0,
            "unsupported_target_count": 0,
            "reclaimable_bytes": 0,
        }

    service = ControlledToolWorkflowService(
        config_loader=_snapshot,
        readiness_loader=_readiness,
        eval_report_loader=_eval_report,
        cost_summary_loader=_cost_summary,
        data_controls_loader=_data_controls_preview,
    )
    result = await service.run(
        [
            {"tool": "readiness_check", "payload": {}},
            {"tool": "eval_latest", "payload": {}},
            {"tool": "cost_summary", "payload": {"period": "30d", "include_estimated": False}},
            {"tool": "data_controls_dry_run", "payload": {"scopes": []}},
        ],
        workflow_mode="plan_reflect_repair",
    )
    return {
        "success": bool(result.get("success")),
        "workflow": result,
        "rag": {
            "summary": dict(report.get("summary") or {}),
            "badcase_summary": badcase_summary,
        },
    }


def _format_status(value: Any) -> str:
    return "ok" if bool(value) else "failed"


def render_demo(payload: Dict[str, Any]) -> str:
    workflow = dict(payload.get("workflow") or {})
    rag = dict(payload.get("rag") or {})
    summary = dict(rag.get("summary") or {})
    badcase_summary = dict(rag.get("badcase_summary") or {})
    trace = list(workflow.get("trace") or [])

    lines = [
        "Agent Tool Workflow demo",
        "-" * 50,
        f"workflow: {_format_status(workflow.get('success'))}",
        f"trace_steps: {len(trace)}",
        f"repair_attempted: {bool(dict(workflow.get('repair') or {}).get('attempted'))}",
        f"rag_cases: {summary.get('total_cases', 0)}",
        f"rag_passed: {bool(summary.get('passed'))}",
        f"badcases: {badcase_summary.get('badcase_count', 0)}",
        "",
        "trace:",
    ]
    for item in trace:
        step = dict(item or {})
        line = (
            f"- #{step.get('index')} {step.get('tool')}: "
            f"{step.get('status')} "
            f"schema={step.get('schema_valid')} "
            f"attempts={step.get('attempts')}"
        )
        if step.get("error_type"):
            line += f" error={step.get('error_type')}"
        if step.get("repair_attempt"):
            line += f" repair_attempt={step.get('repair_attempt')}"
        lines.append(line)

    regression_count = badcase_summary.get("regression_count", 0)
    lines.extend(
        [
            "",
            "interview talking points:",
            "- 白名单工具只返回摘要，不展开完整 cases、review queue 或本机路径。",
            f"- RAG eval 与 Tool Workflow 串联后可同时展示评测状态和工具 trace；当前 regression_count={regression_count}。",
            "- plan_reflect_repair 只修复 schema-safe 默认值，不会把危险 payload 修成可执行动作。",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Agent Tool Workflow demo.")
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
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_path = Path(args.report).expanduser().resolve()
    if not bool(args.skip_eval) or not report_path.exists():
        result = run_rag_eval(report_path)
        if result != 0:
            return result
    if not report_path.exists():
        print(f"RAG eval report not found: {report_path}", file=sys.stderr)
        return 1

    payload = asyncio.run(build_demo_payload(load_eval_report(report_path)))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_demo(payload))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
