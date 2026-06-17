#!/usr/bin/env python3
"""Summarize RAG eval reports into reviewable badcase categories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = PROJECT_ROOT / "data" / "evals" / "rag-smoke-report.json"

METRIC_KEYS = (
    "citation_accuracy",
    "context_recall",
    "faithfulness",
    "answer_citation_binding",
    "refusal_accuracy",
    "runtime_exception_count",
    "empty_reply_rate",
    "retrieval_hit_rate",
)

CATEGORY_LABELS = {
    "runtime_exception": "运行异常",
    "empty_reply": "空回复",
    "short_reply": "短回复",
    "retrieval_miss": "检索未命中",
    "citation_mismatch": "引用不匹配",
    "context_recall_gap": "上下文召回不足",
    "unfaithful_answer": "忠实度不足",
    "answer_citation_unbound": "答案未绑定引用",
    "refusal_mismatch": "拒答策略不匹配",
}

CATEGORY_ACTIONS = {
    "runtime_exception": "先查看 runtime_exception 与 trace 日志，补超时、重试或降级路径。",
    "empty_reply": "补充回复生成失败的兜底分支，并把空回复作为回归门禁。",
    "short_reply": "检查 prompt 和截断策略，确认不是异常兜底导致的信息不足。",
    "retrieval_miss": "回看 query rewrite、chunk 切分、向量索引和 top-k/rerank 配置。",
    "citation_mismatch": "核对 expected_* 与返回 citation 元数据，优先修复 doc_id/chunk_id/source_file 映射。",
    "context_recall_gap": "分析未召回的证据字段，必要时补充切分粒度、关键词召回或 RRF 融合。",
    "unfaithful_answer": "检查回答是否脱离证据，强化引用约束和无证据拒答策略。",
    "answer_citation_unbound": "要求答案显式包含返回的 citation_id，避免只召回不引用。",
    "refusal_mismatch": "核对 safety.action 与 unsupported_answer 标注，补敏感信息和无证据场景。",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _is_false(value: Any) -> bool:
    return value is False


def _is_below_one(value: Any) -> bool:
    return isinstance(value, (int, float)) and float(value) < 1.0


def _case_identifier(case: Dict[str, Any], index: int) -> str:
    raw = str(case.get("id") or "").strip()
    return raw or f"case-{index + 1:02d}"


def _classify_case(case: Dict[str, Any]) -> List[str]:
    flags = _as_dict(case.get("flags"))
    rag_eval = _as_dict(case.get("rag_eval"))
    categories: List[str] = []

    if flags.get("runtime_exception") or str(case.get("runtime_exception") or "").strip():
        categories.append("runtime_exception")
    if flags.get("empty_reply"):
        categories.append("empty_reply")
    if flags.get("short_reply"):
        categories.append("short_reply")
    if flags.get("retrieval_hit") is False:
        categories.append("retrieval_miss")
    if _is_below_one(rag_eval.get("citation_accuracy")):
        categories.append("citation_mismatch")
    if _is_below_one(rag_eval.get("context_recall")):
        categories.append("context_recall_gap")
    if _is_false(rag_eval.get("faithfulness")):
        categories.append("unfaithful_answer")
    if _is_false(rag_eval.get("answer_citation_bound")):
        categories.append("answer_citation_unbound")
    if _is_false(rag_eval.get("refusal_match")):
        categories.append("refusal_mismatch")

    return categories


def _collect_case_signals(case: Dict[str, Any]) -> Dict[str, Any]:
    rag_eval = _as_dict(case.get("rag_eval"))
    return {
        "citation_accuracy": rag_eval.get("citation_accuracy"),
        "context_recall": rag_eval.get("context_recall"),
        "faithfulness": rag_eval.get("faithfulness"),
        "answer_citation_bound": rag_eval.get("answer_citation_bound"),
        "refusal_match": rag_eval.get("refusal_match"),
        "runtime_exception": str(case.get("runtime_exception") or "").strip(),
    }


def _suggest_actions(categories: Iterable[str]) -> List[str]:
    actions: List[str] = []
    for category in categories:
        action = CATEGORY_ACTIONS.get(category)
        if action and action not in actions:
            actions.append(action)
    return actions


def load_report(report_path: str | Path) -> Dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RAG eval report must be a JSON object")
    return payload


def build_badcase_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = _as_dict(report.get("summary"))
    cases = list(report.get("cases") or [])
    regressions = [dict(item) for item in report.get("regressions") or [] if isinstance(item, dict)]
    category_counts: Dict[str, int] = {}
    badcases: List[Dict[str, Any]] = []

    for index, raw_case in enumerate(cases):
        case = _as_dict(raw_case)
        categories = _classify_case(case)
        if not categories:
            continue
        for category in categories:
            category_counts[category] = category_counts.get(category, 0) + 1
        badcases.append({
            "id": _case_identifier(case, index),
            "user_text": str(case.get("user_text") or ""),
            "categories": categories,
            "category_labels": [CATEGORY_LABELS.get(item, item) for item in categories],
            "signals": _collect_case_signals(case),
            "suggested_actions": _suggest_actions(categories),
        })

    metrics = {
        key: summary.get(key)
        for key in METRIC_KEYS
        if key in summary
    }
    return {
        "preset": str(report.get("preset") or ""),
        "generated_at": str(report.get("generated_at") or ""),
        "passed": bool(summary.get("passed")),
        "total_cases": int(summary.get("total_cases") or len(cases)),
        "badcase_count": len(badcases),
        "regression_count": len(regressions),
        "metrics": metrics,
        "category_counts": dict(sorted(category_counts.items())),
        "regressions": regressions,
        "badcases": badcases,
    }


def _format_metric_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_text(payload: Dict[str, Any], *, max_cases: int = 5) -> str:
    lines = [
        "RAG badcase summary",
        "-" * 50,
        f"preset: {payload.get('preset') or 'unknown'}",
        f"generated_at: {payload.get('generated_at') or 'unknown'}",
        f"passed: {str(bool(payload.get('passed'))).lower()}",
        f"cases: {payload.get('total_cases', 0)}",
        f"badcases: {payload.get('badcase_count', 0)}",
        f"regressions: {payload.get('regression_count', 0)}",
        "",
        "metrics:",
    ]
    metrics = _as_dict(payload.get("metrics"))
    for key in METRIC_KEYS:
        if key in metrics:
            lines.append(f"- {key}: {_format_metric_value(metrics.get(key))}")

    category_counts = _as_dict(payload.get("category_counts"))
    lines.append("")
    lines.append("categories:")
    if category_counts:
        for category, count in category_counts.items():
            label = CATEGORY_LABELS.get(category, category)
            lines.append(f"- {category} ({label}): {count}")
    else:
        lines.append("- none")

    regressions = list(payload.get("regressions") or [])
    lines.append("")
    lines.append("regressions:")
    if regressions:
        for item in regressions:
            metric = str(_as_dict(item).get("metric") or "unknown")
            reason = str(_as_dict(item).get("reason") or "")
            lines.append(f"- {metric}: {reason}".rstrip())
    else:
        lines.append("- none")

    badcases = list(payload.get("badcases") or [])
    lines.append("")
    lines.append("badcase details:")
    if badcases:
        for item in badcases[:max(0, max_cases)]:
            case = _as_dict(item)
            labels = ", ".join(str(label) for label in case.get("category_labels") or [])
            lines.append(f"- {case.get('id')}: {labels}")
            user_text = str(case.get("user_text") or "").strip()
            if user_text:
                lines.append(f"  query: {user_text[:120]}")
    else:
        lines.append("- none")

    actions = _suggest_actions(category_counts.keys())
    lines.append("")
    lines.append("suggested actions:")
    if actions:
        for action in actions:
            lines.append(f"- {action}")
    else:
        lines.append("- 当前报告未发现 badcase，可把该输出作为面试演示中的回归证据。")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a RAG eval report into badcase categories.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Path to a RAG eval report JSON file.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--max-cases", type=int, default=5, help="Maximum badcase details to print in text mode.")
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report_path = Path(args.report).expanduser()
    if not report_path.exists():
        print(f"RAG eval report not found: {report_path}", file=sys.stderr)
        return 1

    payload = build_badcase_summary(load_report(report_path))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload, max_cases=args.max_cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
