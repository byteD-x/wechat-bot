from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..utils.common import as_float, as_int


@dataclass(slots=True)
class ModelRouteDecision:
    selected_provider: str
    selected_model: str
    task_complexity: str
    estimated_input_chars: int
    rag_augmented: bool
    latency_priority: bool
    cost_priority: bool
    fallback_allowed: bool
    reasons: List[str] = field(default_factory=list)
    strategy: str = "current_runtime"
    timeout_sec: float = 0.0
    deadline_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "task_complexity": self.task_complexity,
            "estimated_input_chars": self.estimated_input_chars,
            "rag_augmented": self.rag_augmented,
            "latency_priority": self.latency_priority,
            "cost_priority": self.cost_priority,
            "fallback_allowed": self.fallback_allowed,
            "timeout_sec": self.timeout_sec,
            "deadline_sec": self.deadline_sec,
            "reasons": list(self.reasons),
        }


class ModelRouter:
    """Explainable routing policy for the currently selected runtime model.

    This router intentionally does not switch providers or read credentials. It
    records a stable routing decision so production behavior can be audited
    before later introducing multi-profile execution.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(settings or {}) if isinstance(settings, dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.simple_max_chars = as_int(cfg.get("simple_max_chars", 240), 240, min_value=1)
        self.complex_min_chars = as_int(cfg.get("complex_min_chars", 1600), 1600, min_value=1)
        self.rag_complex_min_chars = as_int(
            cfg.get("rag_complex_min_chars", 900),
            900,
            min_value=1,
        )
        self.tight_deadline_sec = as_float(
            cfg.get("tight_deadline_sec", 2.0),
            2.0,
            min_value=0.0,
        )
        self.tight_timeout_sec = as_float(
            cfg.get("tight_timeout_sec", 5.0),
            5.0,
            min_value=0.0,
        )
        self.fallback_allowed = bool(cfg.get("fallback_allowed", True))

    def route(
        self,
        *,
        provider_id: str,
        model: str,
        user_text: str,
        rag_augmented: bool = False,
        timeout_sec: Optional[float] = None,
        deadline_sec: Optional[float] = None,
    ) -> ModelRouteDecision:
        selected_provider = str(provider_id or "unknown").strip().lower() or "unknown"
        selected_model = str(model or "unknown").strip() or "unknown"
        text = str(user_text or "")
        input_chars = len(text)
        timeout_value = as_float(timeout_sec, 0.0, min_value=0.0)
        deadline_value = as_float(deadline_sec, 0.0, min_value=0.0)

        reasons = ["current_runtime_locked"]
        if not self.enabled:
            reasons.append("routing_disabled")

        latency_priority = self._has_tight_latency_budget(timeout_value, deadline_value)
        if latency_priority:
            reasons.append("tight_latency_budget")

        if rag_augmented:
            reasons.append("rag_augmented")

        complexity = self._classify_complexity(input_chars, rag_augmented)
        if complexity == "simple":
            reasons.append("short_input")
        elif complexity == "complex":
            reasons.append("long_or_grounded_context")
        else:
            reasons.append("standard_input")

        cost_priority = complexity == "simple" and not rag_augmented
        if cost_priority:
            reasons.append("cost_sensitive")

        fallback_allowed = self.fallback_allowed and not latency_priority
        if not fallback_allowed:
            reasons.append("fallback_limited")

        return ModelRouteDecision(
            selected_provider=selected_provider,
            selected_model=selected_model,
            task_complexity=complexity,
            estimated_input_chars=input_chars,
            rag_augmented=bool(rag_augmented),
            latency_priority=latency_priority,
            cost_priority=cost_priority,
            fallback_allowed=fallback_allowed,
            reasons=reasons,
            timeout_sec=round(timeout_value, 4),
            deadline_sec=round(deadline_value, 4),
        )

    def _classify_complexity(self, input_chars: int, rag_augmented: bool) -> str:
        if input_chars >= self.complex_min_chars:
            return "complex"
        if rag_augmented and input_chars >= self.rag_complex_min_chars:
            return "complex"
        if rag_augmented:
            return "standard"
        if input_chars <= self.simple_max_chars:
            return "simple"
        return "standard"

    def _has_tight_latency_budget(self, timeout_sec: float, deadline_sec: float) -> bool:
        if deadline_sec > 0 and deadline_sec <= self.tight_deadline_sec:
            return True
        return timeout_sec > 0 and timeout_sec <= self.tight_timeout_sec
