from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List


_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "is",
    "it",
    "of",
    "on",
    "please",
    "should",
    "the",
    "to",
    "what",
    "when",
    "where",
    "who",
    "why",
}


@dataclass(frozen=True)
class QueryRewriteResult:
    original_query: str
    keyword_query: str
    terms: List[str]
    changed: bool

    def to_trace(self, *, enabled: bool) -> Dict[str, Any]:
        return {
            "enabled": bool(enabled),
            "changed": bool(self.changed),
            "term_count": len(self.terms),
        }


class QueryRewriteService:
    """Build a conservative keyword query for hybrid retrieval."""

    def rewrite(self, query_text: Any) -> QueryRewriteResult:
        original = self._normalize(query_text)
        terms = self._extract_terms(original)
        keyword_query = " ".join(terms) if terms else original
        return QueryRewriteResult(
            original_query=original,
            keyword_query=keyword_query,
            terms=terms,
            changed=bool(keyword_query and keyword_query != original),
        )

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _extract_terms(text: str) -> List[str]:
        terms: List[str] = []
        seen = set()
        for raw in _TOKEN_RE.findall(text.lower()):
            term = raw.strip()
            if not term or term in _STOPWORDS:
                continue
            if term.isdigit() and len(term) < 3:
                continue
            if term not in seen:
                seen.add(term)
                terms.append(term)
        return terms[:12]


__all__ = [
    "QueryRewriteResult",
    "QueryRewriteService",
]
