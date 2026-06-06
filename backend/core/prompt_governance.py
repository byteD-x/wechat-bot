"""Prompt revision ledger and rollback helpers."""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.shared_config import atomic_write_json, ensure_data_root
from backend.utils.config import compose_system_prompt_template, extract_editable_system_prompt


MAX_REASON_CHARS = 500
MAX_OPERATOR_CHARS = 80
MAX_PROMPT_CHARS = 20000


def _now_ts() -> int:
    return int(time.time())


class PromptGovernanceService:
    """Small JSON-backed audit ledger for system Prompt revisions."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.ledger_path = Path(ledger_path).expanduser().resolve() if ledger_path else ensure_data_root() / "prompt_revisions.json"

    def load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {"schema_version": 1, "active_revision": 0, "revisions": []}
        try:
            import json

            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        revisions = payload.get("revisions")
        if not isinstance(revisions, list):
            revisions = []
        return {
            "schema_version": int(payload.get("schema_version") or 1),
            "active_revision": int(payload.get("active_revision") or 0),
            "revisions": [dict(item) for item in revisions if isinstance(item, dict)],
        }

    def save_ledger(self, ledger: dict[str, Any]) -> None:
        atomic_write_json(self.ledger_path, ledger)

    def seed_from_config(self, system_prompt: Any, *, source: str = "config_seed") -> dict[str, Any]:
        ledger = self.load_ledger()
        if ledger["revisions"]:
            return ledger
        prompt = compose_system_prompt_template(system_prompt)
        revision = {
            "revision": 1,
            "status": "active",
            "source": source,
            "prompt": prompt,
            "editable_prompt": extract_editable_system_prompt(prompt),
            "created_at": _now_ts(),
        }
        ledger = {"schema_version": 1, "active_revision": 1, "revisions": [revision]}
        self.save_ledger(ledger)
        return ledger

    def rollback(
        self,
        target_revision: int,
        *,
        current_system_prompt: Any,
        reason: str = "",
        operator: str = "api",
    ) -> dict[str, Any]:
        target_revision = int(target_revision or 0)
        if target_revision <= 0:
            raise ValueError("revision must be a positive integer")

        ledger = self.seed_from_config(current_system_prompt)
        revisions = ledger["revisions"]
        target = next(
            (item for item in revisions if int(item.get("revision") or 0) == target_revision),
            None,
        )
        if target is None:
            raise LookupError("prompt revision not found")

        prompt = compose_system_prompt_template(target.get("prompt") or target.get("editable_prompt") or "")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError("prompt is too long")

        next_revision = max([int(item.get("revision") or 0) for item in revisions] + [0]) + 1
        for item in revisions:
            if str(item.get("status") or "") == "active":
                item["status"] = "superseded"

        new_revision = {
            "revision": next_revision,
            "status": "active",
            "source": "rollback",
            "prompt": prompt,
            "editable_prompt": extract_editable_system_prompt(prompt),
            "rollback_from": target_revision,
            "reason": str(reason or "").strip()[:MAX_REASON_CHARS],
            "operator": str(operator or "api").strip()[:MAX_OPERATOR_CHARS] or "api",
            "created_at": _now_ts(),
        }
        revisions.append(new_revision)
        ledger["active_revision"] = next_revision
        self.save_ledger(ledger)
        return {
            "success": True,
            "active_revision": next_revision,
            "rolled_back_from": target_revision,
            "revision": deepcopy(new_revision),
            "ledger_path": str(self.ledger_path),
        }


def get_prompt_governance_service() -> PromptGovernanceService:
    return PromptGovernanceService()
