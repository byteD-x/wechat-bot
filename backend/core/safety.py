from __future__ import annotations

import re
from typing import Any, Dict, List


PROMPT_INJECTION_PATTERNS = [
    r"(?i)\bignore (all )?(previous|prior|above) instructions\b",
    r"(?i)\bdisregard (all )?(previous|prior|above) instructions\b",
    r"(?i)\breveal (the )?(system|developer) prompt\b",
    r"(?i)\bprint (the )?(system|developer) prompt\b",
    r"\u5ffd\u7565(\u4ee5\u4e0a|\u4e4b\u524d|\u524d\u9762).{0,12}(\u6307\u4ee4|\u89c4\u5219|\u8981\u6c42)",
    r"(\u6cc4\u9732|\u8f93\u51fa|\u6253\u5370).{0,12}(\u7cfb\u7edf\u63d0\u793a|\u63d0\u793a\u8bcd|system prompt)",
]

PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    r"(?<!\d)1[3-9]\d{9}(?!\d)",
    r"(?<!\d)\d{17}[\dXx](?!\d)",
]

KNOWLEDGE_QUERY_PATTERN = re.compile(
    r"(\?|\uff1f|\u4e3a\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|\u8bf7\u95ee|"
    r"\u6839\u636e|\u4f9d\u636e|\u8bc1\u660e|\u6765\u6e90|\u8d44\u6599|"
    r"\u8c01|\u4ec0\u4e48|\u54ea\u91cc|\u4f55\u65f6|when|what|why|how)",
    re.IGNORECASE,
)


class SafetyGuard:
    def __init__(self, bot_cfg: Dict[str, Any] | None = None, agent_cfg: Dict[str, Any] | None = None) -> None:
        self.bot_cfg = dict(bot_cfg or {})
        self.agent_cfg = dict(agent_cfg or {})

    def assess(self, *, user_text: str, answer_text: str, retrieval: Dict[str, Any] | None = None) -> Dict[str, Any]:
        retrieval_payload = dict(retrieval or {})
        citations = list(retrieval_payload.get("citations") or [])
        reasons: List[str] = []

        prompt_injection_detected = self._matches_any(user_text, PROMPT_INJECTION_PATTERNS)
        pii_detected = self._matches_any(user_text, PII_PATTERNS) or self._matches_any(answer_text, PII_PATTERNS)
        citation_required = bool(
            self.bot_cfg.get("safety_require_citations_for_rag", False)
            or self.agent_cfg.get("safety_require_citations_for_rag", False)
        )
        block_prompt_injection = bool(
            self.bot_cfg.get("safety_block_prompt_injection", False)
            or self.agent_cfg.get("safety_block_prompt_injection", False)
        )
        knowledge_query = bool(KNOWLEDGE_QUERY_PATTERN.search(str(user_text or "")))
        rag_augmented = bool(retrieval_payload.get("augmented"))
        grounded = bool(citations)

        if prompt_injection_detected:
            reasons.append("prompt_injection_detected")
        if pii_detected:
            reasons.append("pii_detected")
        if citation_required and rag_augmented and knowledge_query and not grounded:
            reasons.append("missing_required_citation")

        action = "allow"
        refusal = ""
        if block_prompt_injection and prompt_injection_detected:
            action = "refuse"
            refusal = "\u8fd9\u4e2a\u8bf7\u6c42\u6d89\u53ca\u4fee\u6539\u6216\u6cc4\u9732\u7cfb\u7edf\u89c4\u5219\uff0c\u6211\u4e0d\u80fd\u6309\u8fd9\u4e2a\u65b9\u5411\u5904\u7406\u3002"
        elif citation_required and "missing_required_citation" in reasons:
            action = "refuse"
            refusal = "\u6211\u6ca1\u6709\u627e\u5230\u8db3\u591f\u53ef\u9760\u7684\u6765\u6e90\u4f9d\u636e\uff0c\u5148\u4e0d\u76f4\u63a5\u4e0b\u7ed3\u8bba\u3002"

        return {
            "action": action,
            "reasons": reasons,
            "prompt_injection_detected": prompt_injection_detected,
            "pii_detected": pii_detected,
            "citation_required": citation_required,
            "grounded": grounded,
            "citation_count": len(citations),
            "refusal": refusal,
        }

    @staticmethod
    def _matches_any(text: str, patterns: List[str]) -> bool:
        value = str(text or "")
        if not value:
            return False
        return any(re.search(pattern, value) for pattern in patterns)
