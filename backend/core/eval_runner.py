from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from backend.core.workspace_backup import get_app_version


SHORT_REPLY_MIN_CHARS = 6


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _normalize_case_identifier(index: int, item: Dict[str, Any]) -> str:
    raw = str(item.get("id") or item.get("case_id") or "").strip()
    return raw or f"case-{index + 1:02d}"


def _extract_case_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    metadata = item.get("metadata")
    return dict(metadata or {}) if isinstance(metadata, dict) else {}


def _extract_reply_text(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    for value in (
        item.get("assistant_reply"),
        item.get("reply_text"),
        item.get("draft_reply"),
        metadata.get("assistant_reply"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_feedback(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    reply_quality = dict(item.get("reply_quality") or {})
    if not reply_quality and isinstance(metadata.get("reply_quality"), dict):
        reply_quality = dict(metadata.get("reply_quality") or {})
    feedback = str(
        reply_quality.get("user_feedback")
        or reply_quality.get("feedback")
        or item.get("manual_feedback")
        or ""
    ).strip().lower()
    return feedback


def _extract_retrieval(item: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    retrieval = item.get("retrieval")
    if isinstance(retrieval, dict):
        return dict(retrieval)
    if isinstance(metadata.get("retrieval"), dict):
        return dict(metadata.get("retrieval") or {})
    return {}


def _extract_runtime_exception(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    for value in (
        item.get("runtime_exception"),
        metadata.get("runtime_exception"),
        metadata.get("response_error"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _load_dataset(dataset_path: str | Path) -> Dict[str, Any]:
    path = Path(dataset_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("eval dataset must be a JSON object")
    return payload


def evaluate_dataset(
    dataset_path: str | Path,
    *,
    preset: str,
) -> Dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    cases = list(dataset.get("cases") or [])
    baseline = dict(dataset.get("baseline") or {})

    evaluated_cases: List[Dict[str, Any]] = []
    empty_count = 0
    short_count = 0
    retrieval_hit_count = 0
    helpful_feedback_count = 0
    runtime_exception_count = 0

    for index, raw_case in enumerate(cases):
        item = dict(raw_case or {})
        metadata = _extract_case_metadata(item)
        reply_text = _extract_reply_text(item, metadata)
        feedback = _extract_feedback(item, metadata)
        retrieval = _extract_retrieval(item, metadata)
        runtime_exception = _extract_runtime_exception(item, metadata)

        is_empty = not bool(reply_text.strip())
        is_short = bool(reply_text) and len(reply_text.strip()) < SHORT_REPLY_MIN_CHARS
        retrieval_hit = bool(retrieval.get("augmented")) or int(retrieval.get("runtime_hit_count", 0) or 0) > 0
        helpful_feedback = feedback == "helpful"

        empty_count += 1 if is_empty else 0
        short_count += 1 if is_short else 0
        retrieval_hit_count += 1 if retrieval_hit else 0
        helpful_feedback_count += 1 if helpful_feedback else 0
        runtime_exception_count += 1 if runtime_exception else 0

        evaluated_cases.append({
            "id": _normalize_case_identifier(index, item),
            "chat_id": str(item.get("chat_id") or ""),
            "user_text": str(item.get("user_text") or item.get("content") or ""),
            "assistant_reply": reply_text,
            "flags": {
                "empty_reply": is_empty,
                "short_reply": is_short,
                "retrieval_hit": retrieval_hit,
                "helpful_feedback": helpful_feedback,
                "runtime_exception": bool(runtime_exception),
            },
            "retrieval": retrieval,
            "reply_quality": {
                "user_feedback": feedback,
            },
            "runtime_exception": runtime_exception,
        })

    total_cases = len(evaluated_cases)
    summary = {
        "total_cases": total_cases,
        "empty_reply_rate": _safe_rate(empty_count, total_cases),
        "short_reply_rate": _safe_rate(short_count, total_cases),
        "retrieval_hit_rate": _safe_rate(retrieval_hit_count, total_cases),
        "manual_feedback_hit_rate": _safe_rate(helpful_feedback_count, total_cases),
        "runtime_exception_count": runtime_exception_count,
        "passed": True,
    }

    regressions: List[Dict[str, Any]] = []
    if summary["runtime_exception_count"] > 0:
        regressions.append({
            "metric": "runtime_exception_count",
            "reason": "runtime_exception_count > 0",
            "actual": summary["runtime_exception_count"],
            "threshold": 0,
        })
    if summary["empty_reply_rate"] > 0:
        regressions.append({
            "metric": "empty_reply_rate",
            "reason": "empty_reply_rate > 0",
            "actual": summary["empty_reply_rate"],
            "threshold": 0,
        })

    baseline_short_reply_rate = float(baseline.get("short_reply_rate", 0.0) or 0.0)
    if summary["short_reply_rate"] > round(baseline_short_reply_rate + 0.15, 4):
        regressions.append({
            "metric": "short_reply_rate",
            "reason": "short_reply_rate exceeded baseline + 0.15",
            "actual": summary["short_reply_rate"],
            "threshold": round(baseline_short_reply_rate + 0.15, 4),
        })

    baseline_retrieval_hit_rate = float(baseline.get("retrieval_hit_rate", 0.0) or 0.0)
    if summary["retrieval_hit_rate"] < round(max(0.0, baseline_retrieval_hit_rate - 0.10), 4):
        regressions.append({
            "metric": "retrieval_hit_rate",
            "reason": "retrieval_hit_rate dropped below baseline - 0.10",
            "actual": summary["retrieval_hit_rate"],
            "threshold": round(max(0.0, baseline_retrieval_hit_rate - 0.10), 4),
        })

    summary["passed"] = len(regressions) == 0
    return {
        "summary": summary,
        "cases": evaluated_cases,
        "regressions": regressions,
        "generated_at": _utc_now_iso(),
        "preset": str(preset or "").strip(),
        "app_version": get_app_version(),
    }


def write_eval_report(report: Dict[str, Any], report_path: str | Path) -> None:
    destination = Path(report_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
