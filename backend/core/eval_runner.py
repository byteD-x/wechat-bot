from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend.core.workspace_backup import get_app_version


SHORT_REPLY_MIN_CHARS = 6


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _safe_average(total: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(total) / float(denominator), 4)


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


def _extract_safety(item: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    safety = item.get("safety")
    if isinstance(safety, dict):
        return dict(safety)
    if isinstance(metadata.get("safety"), dict):
        return dict(metadata.get("safety") or {})
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


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _extract_citations(retrieval: Dict[str, Any]) -> List[Dict[str, Any]]:
    citations = retrieval.get("citations")
    if not isinstance(citations, list):
        return []
    return [dict(item) for item in citations if isinstance(item, dict)]


def _add_expected_values(target: Set[str], prefix: str, values: Any) -> None:
    for value in _as_list(values):
        text = str(value or "").strip()
        if text:
            target.add(f"{prefix}:{text}")


def _collect_expected_evidence(item: Dict[str, Any], metadata: Dict[str, Any]) -> Set[str]:
    expected: Set[str] = set()
    for source in (item, metadata):
        _add_expected_values(expected, "citation_id", source.get("expected_citation_ids"))
        _add_expected_values(expected, "doc_id", source.get("expected_doc_ids"))
        _add_expected_values(expected, "chunk_id", source.get("expected_chunk_ids"))
        _add_expected_values(expected, "source_file", source.get("expected_source_files"))
        _add_expected_values(expected, "chunk_index", source.get("expected_chunk_indexes"))
        for citation in _as_list(source.get("expected_citations")):
            if not isinstance(citation, dict):
                continue
            for key in ("citation_id", "doc_id", "chunk_id", "source_file", "chunk_index"):
                text = str(citation.get(key) or "").strip()
                if text:
                    expected.add(f"{key}:{text}")
    return expected


def _citation_evidence_keys(citation: Dict[str, Any]) -> Set[str]:
    keys: Set[str] = set()
    for key in ("citation_id", "doc_id", "chunk_id", "source_file", "chunk_index"):
        text = str(citation.get(key) or "").strip()
        if text:
            keys.add(f"{key}:{text}")
    return keys


def _collect_returned_evidence(citations: List[Dict[str, Any]]) -> Set[str]:
    returned: Set[str] = set()
    for citation in citations:
        returned.update(_citation_evidence_keys(citation))
    return returned


def _collect_answer_citation_markers(citations: List[Dict[str, Any]]) -> Set[str]:
    markers: Set[str] = set()
    for citation in citations:
        for key in ("citation_id", "doc_id", "chunk_id", "source_file", "url"):
            text = str(citation.get(key) or "").strip()
            if text:
                markers.add(text)
    return markers


def _answer_references_returned_citation(reply_text: str, citations: List[Dict[str, Any]]) -> Optional[bool]:
    if not citations:
        return None
    reply = str(reply_text or "")
    if not reply.strip():
        return False
    markers = _collect_answer_citation_markers(citations)
    if not markers:
        return None
    return any(marker in reply for marker in markers)


def _extract_expected_action(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    for source in (item, metadata):
        action = str(
            source.get("expected_action")
            or source.get("expected_safety_action")
            or ""
        ).strip().lower()
        if action:
            return action
        if source.get("unsupported_answer") is True:
            return "refuse"
    return ""


def _extract_actual_action(item: Dict[str, Any], metadata: Dict[str, Any], safety: Dict[str, Any], reply_text: str) -> str:
    for value in (
        item.get("actual_action"),
        metadata.get("actual_action"),
        safety.get("action"),
    ):
        text = str(value or "").strip().lower()
        if text:
            return text
    return "allow" if str(reply_text or "").strip() else "refuse"


def _build_rag_case_metrics(
    item: Dict[str, Any],
    metadata: Dict[str, Any],
    retrieval: Dict[str, Any],
    safety: Dict[str, Any],
    reply_text: str,
) -> Dict[str, Any]:
    citations = _extract_citations(retrieval)
    expected_evidence = _collect_expected_evidence(item, metadata)
    returned_evidence = _collect_returned_evidence(citations)
    matched_evidence = expected_evidence & returned_evidence
    expected_action = _extract_expected_action(item, metadata)
    actual_action = _extract_actual_action(item, metadata, safety, reply_text)

    citation_accuracy: Optional[float] = None
    context_recall: Optional[float] = None
    faithfulness: Optional[bool] = None
    refusal_match: Optional[bool] = None
    answer_citation_bound = _answer_references_returned_citation(reply_text, citations)

    if expected_evidence:
        valid_citations = 0
        for citation in citations:
            if _citation_evidence_keys(citation) & expected_evidence:
                valid_citations += 1
        citation_accuracy = _safe_rate(valid_citations, len(citations))
        context_recall = _safe_rate(len(matched_evidence), len(expected_evidence))
        faithfulness = (
            bool(reply_text.strip())
            and context_recall > 0
            and citation_accuracy > 0
            and answer_citation_bound is not False
        )

    if expected_action:
        if expected_action == "manual":
            refusal_match = actual_action in {"manual", "refuse"}
        else:
            refusal_match = actual_action == expected_action
        if expected_action == "refuse":
            faithfulness = bool(refusal_match)

    return {
        "citations": citations,
        "expected_evidence": sorted(expected_evidence),
        "returned_evidence": sorted(returned_evidence),
        "matched_evidence": sorted(matched_evidence),
        "citation_accuracy": citation_accuracy,
        "context_recall": context_recall,
        "faithfulness": faithfulness,
        "answer_citation_bound": answer_citation_bound,
        "expected_action": expected_action,
        "actual_action": actual_action,
        "refusal_match": refusal_match,
    }


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
    thresholds = dict(dataset.get("thresholds") or {})

    evaluated_cases: List[Dict[str, Any]] = []
    empty_count = 0
    short_count = 0
    retrieval_hit_count = 0
    helpful_feedback_count = 0
    runtime_exception_count = 0
    citation_accuracy_total = 0.0
    citation_accuracy_cases = 0
    context_recall_total = 0.0
    context_recall_cases = 0
    faithfulness_count = 0
    faithfulness_cases = 0
    answer_citation_bound_count = 0
    answer_citation_binding_cases = 0
    refusal_correct_count = 0
    refusal_cases = 0

    for index, raw_case in enumerate(cases):
        item = dict(raw_case or {})
        metadata = _extract_case_metadata(item)
        reply_text = _extract_reply_text(item, metadata)
        feedback = _extract_feedback(item, metadata)
        retrieval = _extract_retrieval(item, metadata)
        safety = _extract_safety(item, metadata)
        runtime_exception = _extract_runtime_exception(item, metadata)
        rag_eval = _build_rag_case_metrics(item, metadata, retrieval, safety, reply_text)

        is_empty = not bool(reply_text.strip())
        is_short = bool(reply_text) and len(reply_text.strip()) < SHORT_REPLY_MIN_CHARS
        retrieval_hit = bool(retrieval.get("augmented")) or int(retrieval.get("runtime_hit_count", 0) or 0) > 0
        helpful_feedback = feedback == "helpful"

        empty_count += 1 if is_empty else 0
        short_count += 1 if is_short else 0
        retrieval_hit_count += 1 if retrieval_hit else 0
        helpful_feedback_count += 1 if helpful_feedback else 0
        runtime_exception_count += 1 if runtime_exception else 0
        if rag_eval["citation_accuracy"] is not None:
            citation_accuracy_total += float(rag_eval["citation_accuracy"])
            citation_accuracy_cases += 1
        if rag_eval["context_recall"] is not None:
            context_recall_total += float(rag_eval["context_recall"])
            context_recall_cases += 1
        if rag_eval["faithfulness"] is not None:
            faithfulness_count += 1 if rag_eval["faithfulness"] else 0
            faithfulness_cases += 1
        if rag_eval["answer_citation_bound"] is not None:
            answer_citation_bound_count += 1 if rag_eval["answer_citation_bound"] else 0
            answer_citation_binding_cases += 1
        if rag_eval["refusal_match"] is not None:
            refusal_correct_count += 1 if rag_eval["refusal_match"] else 0
            refusal_cases += 1

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
            "safety": safety,
            "rag_eval": {
                key: value
                for key, value in rag_eval.items()
                if key != "citations"
            },
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
        "citation_accuracy": _safe_average(citation_accuracy_total, citation_accuracy_cases),
        "citation_eval_cases": citation_accuracy_cases,
        "context_recall": _safe_average(context_recall_total, context_recall_cases),
        "context_recall_eval_cases": context_recall_cases,
        "faithfulness": _safe_rate(faithfulness_count, faithfulness_cases),
        "faithfulness_eval_cases": faithfulness_cases,
        "answer_citation_binding": _safe_rate(answer_citation_bound_count, answer_citation_binding_cases),
        "answer_citation_binding_eval_cases": answer_citation_binding_cases,
        "refusal_accuracy": _safe_rate(refusal_correct_count, refusal_cases),
        "refusal_eval_cases": refusal_cases,
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

    gated_metrics = {
        "citation_accuracy": citation_accuracy_cases,
        "context_recall": context_recall_cases,
        "faithfulness": faithfulness_cases,
        "answer_citation_binding": answer_citation_binding_cases,
        "refusal_accuracy": refusal_cases,
    }
    for metric, eligible_cases in gated_metrics.items():
        if eligible_cases <= 0:
            continue
        raw_threshold = thresholds.get(metric, baseline.get(metric))
        if raw_threshold is None:
            continue
        threshold = float(raw_threshold)
        if float(summary[metric]) < threshold:
            regressions.append({
                "metric": metric,
                "reason": f"{metric} below configured threshold",
                "actual": summary[metric],
                "threshold": threshold,
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
