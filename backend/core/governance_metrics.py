"""In-memory governance API metrics."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any


class RuntimeGovernanceMetrics:
    """Aggregate safe runtime metrics for local governance APIs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._operations: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self._operations = {}

    def record_prompt_rollback(
        self,
        *,
        success: bool,
        duration_ms: float,
        failure_reason: str = "",
    ) -> None:
        self._record(
            "prompt_rollback",
            success=success,
            duration_ms=duration_ms,
            failure_reason=failure_reason,
        )

    def record_tool_workflow(
        self,
        *,
        success: bool,
        duration_ms: float,
        failure_reason: str = "",
    ) -> None:
        self._record(
            "tool_workflow",
            success=success,
            duration_ms=duration_ms,
            failure_reason=failure_reason,
        )

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            operations = {
                name: self._summarize_operation(payload)
                for name, payload in self._operations.items()
            }
        return {
            "operations": operations,
            "operation_count": len(operations),
        }

    def _record(
        self,
        operation: str,
        *,
        success: bool,
        duration_ms: float,
        failure_reason: str,
    ) -> None:
        operation_name = self._safe_label(operation, fallback="unknown")
        reason = self._safe_label(failure_reason, fallback="unknown")
        elapsed_ms = round(max(float(duration_ms or 0.0), 0.0), 1)
        with self._lock:
            payload = self._operations.setdefault(
                operation_name,
                {
                    "total": 0,
                    "success": 0,
                    "failure": 0,
                    "total_duration_ms": 0.0,
                    "last_duration_ms": 0.0,
                    "failure_reasons": {},
                },
            )
            payload["total"] += 1
            payload["total_duration_ms"] += elapsed_ms
            payload["last_duration_ms"] = elapsed_ms
            if success:
                payload["success"] += 1
            else:
                payload["failure"] += 1
                reasons = payload.setdefault("failure_reasons", {})
                reasons[reason] = int(reasons.get(reason, 0) or 0) + 1

    @staticmethod
    def _summarize_operation(payload: dict[str, Any]) -> dict[str, Any]:
        total = int(payload.get("total") or 0)
        success = int(payload.get("success") or 0)
        failure = int(payload.get("failure") or 0)
        total_duration_ms = float(payload.get("total_duration_ms") or 0.0)
        return {
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": round((success / total) * 100, 1) if total else 0.0,
            "last_duration_ms": round(float(payload.get("last_duration_ms") or 0.0), 1),
            "avg_duration_ms": round(total_duration_ms / total, 1) if total else 0.0,
            "failure_reasons": deepcopy(payload.get("failure_reasons") or {}),
        }

    @staticmethod
    def _safe_label(value: Any, *, fallback: str) -> str:
        label = str(value or "").strip().lower()
        label = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in label)
        label = "_".join(part for part in label.split("_") if part)
        return (label or fallback)[:80]


_GOVERNANCE_METRICS = RuntimeGovernanceMetrics()


def get_governance_metrics() -> RuntimeGovernanceMetrics:
    return _GOVERNANCE_METRICS
