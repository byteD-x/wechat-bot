from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..utils.common import as_float, as_int


def _sha256_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_digest(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = str(value)
    return _sha256_text(payload)


def _message_to_safe_shape(message: Any) -> Dict[str, Any]:
    if isinstance(message, dict):
        role = str(
            message.get("role")
            or message.get("type")
            or message.get("message_type")
            or ""
        ).strip()
        content = message.get("content")
        extra = message.get("additional_kwargs") or message.get("kwargs") or {}
        return {
            "role": role,
            "content_hash": _json_digest(content),
            "extra_hash": _json_digest(extra),
        }
    role = str(
        getattr(message, "role", None)
        or getattr(message, "type", None)
        or getattr(message, "message_type", None)
        or message.__class__.__name__
    ).strip()
    return {
        "role": role,
        "content_hash": _json_digest(getattr(message, "content", "")),
        "extra_hash": _json_digest(getattr(message, "additional_kwargs", {}) or {}),
    }


def _extract_citation_ids(retrieval: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(retrieval, dict):
        return []
    ids: List[str] = []
    for item in retrieval.get("citations") or []:
        if not isinstance(item, dict):
            continue
        citation_id = str(item.get("citation_id") or "").strip()
        if citation_id:
            ids.append(citation_id)
    return sorted(set(ids))


@dataclass(slots=True)
class ResponseCacheKey:
    key: str
    provider_id: str
    model: str
    chat_hash: str
    user_text_hash: str
    system_prompt_hash: str
    prompt_messages_hash: str
    policy_hash: str
    citation_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "provider_id": self.provider_id,
            "model": self.model,
            "chat_hash": self.chat_hash,
            "user_text_hash": self.user_text_hash,
            "system_prompt_hash": self.system_prompt_hash,
            "prompt_messages_hash": self.prompt_messages_hash,
            "policy_hash": self.policy_hash,
            "citation_ids": list(self.citation_ids),
        }


@dataclass(slots=True)
class ResponseCacheEntry:
    key: ResponseCacheKey
    answer_text: str
    metadata: Dict[str, Any]
    created_at: float
    last_accessed_at: float


class ResponseCache:
    """In-memory response cache with exact, context-bound keys."""

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(settings or {}) if isinstance(settings, dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.ttl_sec = as_float(cfg.get("ttl_sec", 120.0), 120.0, min_value=0.0)
        self.max_entries = as_int(cfg.get("max_entries", 128), 128, min_value=1)
        self._store: Dict[str, ResponseCacheEntry] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "expired": 0,
            "evictions": 0,
            "skipped": 0,
        }

    def build_key(
        self,
        *,
        provider_id: str,
        model: str,
        chat_id: str,
        user_text: str,
        system_prompt: str,
        prompt_messages: List[Any],
        retrieval: Optional[Dict[str, Any]] = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> ResponseCacheKey:
        provider = str(provider_id or "unknown").strip().lower() or "unknown"
        model_name = str(model or "unknown").strip() or "unknown"
        citation_ids = _extract_citation_ids(retrieval)
        message_shapes = [_message_to_safe_shape(item) for item in prompt_messages or []]
        parts = {
            "provider_id": provider,
            "model": model_name,
            "chat_hash": _sha256_text(chat_id),
            "user_text_hash": _sha256_text(user_text),
            "system_prompt_hash": _sha256_text(system_prompt),
            "prompt_messages_hash": _json_digest(message_shapes),
            "policy_hash": _json_digest(policy_context or {}),
            "citation_ids": citation_ids,
        }
        return ResponseCacheKey(
            key=_json_digest(parts),
            provider_id=provider,
            model=model_name,
            chat_hash=str(parts["chat_hash"]),
            user_text_hash=str(parts["user_text_hash"]),
            system_prompt_hash=str(parts["system_prompt_hash"]),
            prompt_messages_hash=str(parts["prompt_messages_hash"]),
            policy_hash=str(parts["policy_hash"]),
            citation_ids=citation_ids,
        )

    def get(self, key: ResponseCacheKey) -> Optional[ResponseCacheEntry]:
        if not self.enabled:
            self._stats["skipped"] += 1
            return None
        entry = self._store.get(key.key)
        if entry is None:
            self._stats["misses"] += 1
            return None
        now = time.time()
        if self.ttl_sec > 0 and now - entry.created_at >= self.ttl_sec:
            self._store.pop(key.key, None)
            self._stats["expired"] += 1
            self._stats["misses"] += 1
            return None
        entry.last_accessed_at = now
        self._stats["hits"] += 1
        return ResponseCacheEntry(
            key=entry.key,
            answer_text=entry.answer_text,
            metadata=dict(entry.metadata),
            created_at=entry.created_at,
            last_accessed_at=entry.last_accessed_at,
        )

    def set(
        self,
        key: ResponseCacheKey,
        *,
        answer_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or not str(answer_text or "").strip():
            self._stats["skipped"] += 1
            return False
        now = time.time()
        self._store[key.key] = ResponseCacheEntry(
            key=key,
            answer_text=str(answer_text),
            metadata=dict(metadata or {}),
            created_at=now,
            last_accessed_at=now,
        )
        self._stats["stores"] += 1
        self._evict_if_needed()
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "size": len(self._store),
            "max_entries": self.max_entries,
            "ttl_sec": self.ttl_sec,
            **dict(self._stats),
        }

    def _evict_if_needed(self) -> None:
        while len(self._store) > self.max_entries:
            oldest_key = min(
                self._store,
                key=lambda item_key: self._store[item_key].last_accessed_at,
            )
            self._store.pop(oldest_key, None)
            self._stats["evictions"] += 1
