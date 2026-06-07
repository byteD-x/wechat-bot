from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from typing import Any, Optional

from ..utils.common import as_int


DEFAULT_TRACE_LOGGER_MAX_ENTRIES = 32
_DIGEST_PREFIX_LEN = 16
_SAFE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_SAFE_METRIC_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _digest(value: Any) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST_PREFIX_LEN]


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return max(0, int(default))


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return round(parsed, 4)


class TraceLoggerLite:
    """In-memory trace summaries that deliberately exclude raw prompts and chat text."""

    def __init__(self, max_entries: int = DEFAULT_TRACE_LOGGER_MAX_ENTRIES) -> None:
        self.max_entries = as_int(max_entries, DEFAULT_TRACE_LOGGER_MAX_ENTRIES, min_value=1)
        self._entries: deque[dict[str, Any]] = deque(maxlen=self.max_entries)

    def record(
        self,
        *,
        event: str,
        status: str,
        chat_id: str,
        provider_id: str,
        model: str,
        priority: str,
        timings: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        error: Optional[BaseException] = None,
    ) -> dict[str, Any]:
        metadata = dict(metadata or {})
        entry: dict[str, Any] = {
            "recorded_at": round(time.time(), 4),
            "event": self._safe_label(event, fallback="invoke"),
            "status": self._safe_label(status, fallback="unknown"),
            "priority": self._safe_label(priority, fallback="foreground"),
            "provider_id": self._safe_label(provider_id, fallback="unknown"),
            "model_ref": _digest(model or "unknown"),
            "chat_ref": _digest(chat_id),
            "timings": self._summarize_timings(timings or {}),
            "finish_reason": self._safe_label(metadata.get("finish_reason"), fallback=""),
            "flags": self._summarize_flags(metadata),
            "retrieval": self._summarize_retrieval(metadata.get("retrieval")),
            "model_route": self._summarize_model_route(metadata.get("model_route")),
            "safety": self._summarize_safety(metadata.get("safety")),
            "model_tool": self._summarize_model_tool(metadata.get("model_tool_workflow")),
            "response_cache": self._summarize_response_cache(metadata.get("response_cache")),
        }
        if error is not None:
            entry["error_type"] = error.__class__.__name__
            entry["error_hash"] = _digest(str(error))
        self._entries.append(entry)
        return dict(entry)

    def get_status(self) -> dict[str, Any]:
        recent = [dict(item) for item in self._entries]
        return {
            "enabled": True,
            "max_entries": self.max_entries,
            "count": len(recent),
            "last": dict(recent[-1]) if recent else {},
            "recent": recent,
        }

    @staticmethod
    def _safe_label(value: Any, *, fallback: str) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        if _SAFE_LABEL_PATTERN.match(text) and "\\" not in text and "/" not in text:
            return text
        return f"sha256:{_digest(text)}"

    @staticmethod
    def _summarize_timings(timings: dict[str, Any]) -> dict[str, float]:
        safe: dict[str, float] = {}
        for key, value in timings.items():
            name = str(key or "").strip()
            if not name:
                continue
            if "token" in name.lower():
                continue
            if not _SAFE_METRIC_PATTERN.match(name) or "\\" in name or "/" in name:
                name = f"metric_{_digest(name)}"
            parsed = _safe_float(value)
            if parsed is not None:
                safe[name] = parsed
        return safe

    @staticmethod
    def _summarize_flags(metadata: dict[str, Any]) -> dict[str, bool]:
        names = (
            "compat_fallback_failed",
            "delayed_reply",
            "model_tool_call_loop_blocked",
            "model_tool_calls_enabled",
            "timeout_fallback_applied",
            "tool_call_only_response",
        )
        return {
            name: True
            for name in names
            if _safe_bool(metadata.get(name))
        }

    @staticmethod
    def _summarize_retrieval(value: Any) -> dict[str, Any]:
        retrieval = value if isinstance(value, dict) else {}
        return {
            "augmented": _safe_bool(retrieval.get("augmented")),
            "runtime_hit_count": _safe_int(retrieval.get("runtime_hit_count")),
            "export_hit_count": _safe_int(retrieval.get("export_hit_count")),
            "citation_count": _safe_int(retrieval.get("citation_count")),
        }

    @staticmethod
    def _summarize_model_route(value: Any) -> dict[str, Any]:
        route = value if isinstance(value, dict) else {}
        return {
            "strategy": TraceLoggerLite._safe_label(route.get("strategy"), fallback=""),
            "task_complexity": TraceLoggerLite._safe_label(route.get("task_complexity"), fallback=""),
            "rag_augmented": _safe_bool(route.get("rag_augmented")),
            "latency_priority": _safe_bool(route.get("latency_priority")),
            "cost_priority": _safe_bool(route.get("cost_priority")),
            "fallback_allowed": _safe_bool(route.get("fallback_allowed")),
        }

    @staticmethod
    def _summarize_safety(value: Any) -> dict[str, Any]:
        safety = value if isinstance(value, dict) else {}
        reasons = [
            str(item or "").strip()
            for item in safety.get("reasons") or []
            if str(item or "").strip()
        ]
        return {
            "action": TraceLoggerLite._safe_label(safety.get("action"), fallback=""),
            "reason_count": len(reasons),
            "reason_refs": [_digest(item) for item in reasons[:8]],
            "prompt_injection_detected": _safe_bool(safety.get("prompt_injection_detected")),
            "pii_detected": _safe_bool(safety.get("pii_detected")),
            "pii_blocked": _safe_bool(safety.get("pii_blocked")),
            "citation_required": _safe_bool(safety.get("citation_required")),
            "grounded": _safe_bool(safety.get("grounded")),
            "answer_citation_bound": _safe_bool(safety.get("answer_citation_bound")),
            "citation_count": _safe_int(safety.get("citation_count")),
        }

    @staticmethod
    def _summarize_model_tool(value: Any) -> dict[str, Any]:
        workflow = value if isinstance(value, dict) else {}
        trace_items = workflow.get("trace") if isinstance(workflow.get("trace"), list) else []
        trace: list[dict[str, Any]] = []
        for item in trace_items[:8]:
            if not isinstance(item, dict):
                continue
            trace.append(
                {
                    "index": _safe_int(item.get("index")),
                    "tool": TraceLoggerLite._safe_label(item.get("tool"), fallback=""),
                    "status": TraceLoggerLite._safe_label(item.get("status"), fallback=""),
                    "error_type": TraceLoggerLite._safe_label(
                        item.get("error_type"),
                        fallback="",
                    ),
                    "schema_valid": _safe_bool(item.get("schema_valid", True)),
                    "attempts": _safe_int(item.get("attempts")),
                }
            )
        return {
            "success": _safe_bool(workflow.get("success")),
            "step_count": _safe_int(workflow.get("step_count"), len(trace_items)),
            "error_type": TraceLoggerLite._safe_label(workflow.get("error_type"), fallback=""),
            "trace": trace,
        }

    @staticmethod
    def _summarize_response_cache(value: Any) -> dict[str, bool]:
        cache = value if isinstance(value, dict) else {}
        return {
            "hit": _safe_bool(cache.get("hit")),
            "stored": _safe_bool(cache.get("stored")),
        }
