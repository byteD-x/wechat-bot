"""Prompt revision ledger and rollback helpers."""

from __future__ import annotations

import difflib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.shared_config import atomic_write_json, ensure_data_root
from backend.utils.config import compose_system_prompt_template, extract_editable_system_prompt


MAX_REASON_CHARS = 500
MAX_OPERATOR_CHARS = 80
MAX_PROMPT_CHARS = 20000
DIFF_CONTEXT_LINES = 3


def _now_ts() -> int:
    return int(time.time())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


class PromptGovernanceService:
    """Small JSON-backed audit ledger for system Prompt revisions."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.ledger_path = (
            Path(ledger_path).expanduser().resolve()
            if ledger_path
            else ensure_data_root() / "prompt_revisions.json"
        )

    def load_ledger(self) -> dict[str, Any]:
        ledger, _issues = self._load_ledger_with_issues()
        return ledger

    def _load_ledger_with_issues(self) -> tuple[dict[str, Any], list[str]]:
        issues: list[str] = []
        if not self.ledger_path.exists():
            issues.append("ledger_missing")
            return {"schema_version": 1, "active_revision": 0, "revisions": []}, issues
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
            issues.append("ledger_parse_failed")
        if not isinstance(payload, dict):
            payload = {}
            issues.append("ledger_not_object")
        revisions = payload.get("revisions")
        if not isinstance(revisions, list):
            revisions = []
            issues.append("revisions_not_array")
        ledger = {
            "schema_version": _safe_int(payload.get("schema_version"), 1),
            "active_revision": _safe_int(payload.get("active_revision"), 0),
            "revisions": [dict(item) for item in revisions if isinstance(item, dict)],
        }
        issues.extend(self._audit_ledger_issues(ledger))
        return ledger, sorted(set(issues))

    def save_ledger(self, ledger: dict[str, Any]) -> None:
        atomic_write_json(self.ledger_path, ledger)

    def list_revisions(self) -> dict[str, Any]:
        ledger, issues = self._load_ledger_with_issues()
        active_revision = _safe_int(ledger.get("active_revision"), 0)
        revisions = [
            self._summarize_revision(item, active_revision=active_revision)
            for item in ledger.get("revisions", [])
        ]
        return {
            "success": True,
            "schema_version": _safe_int(ledger.get("schema_version"), 1),
            "active_revision": active_revision,
            "revision_count": len(revisions),
            "revisions": revisions,
            "issues": issues,
            "ledger_path": str(self.ledger_path),
        }

    def diff_revision(self, target_revision: int) -> dict[str, Any]:
        target_revision = _safe_int(target_revision, 0)
        if target_revision <= 0:
            raise ValueError("revision must be a positive integer")

        ledger, issues = self._load_ledger_with_issues()
        revisions = ledger.get("revisions", [])
        active_revision = _safe_int(ledger.get("active_revision"), 0)
        active = self._find_revision(revisions, active_revision)
        target = self._find_revision(revisions, target_revision)
        if target is None:
            raise LookupError("prompt revision not found")
        if active is None:
            raise LookupError("active prompt revision not found")

        active_prompt = self._revision_prompt(active)
        target_prompt = self._revision_prompt(target)
        diff_lines = list(
            difflib.unified_diff(
                active_prompt.splitlines(),
                target_prompt.splitlines(),
                fromfile=f"active:{active_revision}",
                tofile=f"target:{target_revision}",
                lineterm="",
                n=DIFF_CONTEXT_LINES,
            )
        )
        return {
            "success": True,
            "active_revision": active_revision,
            "target_revision": target_revision,
            "from_revision": self._summarize_revision(active, active_revision=active_revision),
            "to_revision": self._summarize_revision(target, active_revision=active_revision),
            "diff": diff_lines,
            "summary": {
                "changed": active_prompt != target_prompt,
                "line_count": len(diff_lines),
                "active_prompt_length": len(active_prompt),
                "target_prompt_length": len(target_prompt),
            },
            "issues": issues,
            "ledger_path": str(self.ledger_path),
        }

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
        target_revision = _safe_int(target_revision, 0)
        if target_revision <= 0:
            raise ValueError("revision must be a positive integer")

        ledger = self.seed_from_config(current_system_prompt)
        revisions = ledger["revisions"]
        target = next(
            (item for item in revisions if _safe_int(item.get("revision"), 0) == target_revision),
            None,
        )
        if target is None:
            raise LookupError("prompt revision not found")

        prompt = compose_system_prompt_template(target.get("prompt") or target.get("editable_prompt") or "")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError("prompt is too long")

        next_revision = max([_safe_int(item.get("revision"), 0) for item in revisions] + [0]) + 1
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

    @staticmethod
    def _find_revision(revisions: list[dict[str, Any]], revision: int) -> dict[str, Any] | None:
        for item in revisions:
            if _safe_int(item.get("revision"), 0) == revision:
                return item
        return None

    @staticmethod
    def _revision_prompt(revision: dict[str, Any]) -> str:
        return compose_system_prompt_template(
            revision.get("prompt") or revision.get("editable_prompt") or ""
        )

    @staticmethod
    def _summarize_revision(
        revision: dict[str, Any],
        *,
        active_revision: int,
    ) -> dict[str, Any]:
        revision_id = _safe_int(revision.get("revision"), 0)
        prompt = str(revision.get("prompt") or "")
        editable_prompt = str(revision.get("editable_prompt") or "")
        return {
            "revision": revision_id,
            "status": str(revision.get("status") or ""),
            "source": str(revision.get("source") or ""),
            "created_at": _safe_int(revision.get("created_at"), 0),
            "rollback_from": _safe_int(revision.get("rollback_from"), 0) or None,
            "reason": str(revision.get("reason") or ""),
            "operator": str(revision.get("operator") or ""),
            "active": revision_id == active_revision,
            "prompt_length": len(prompt),
            "editable_prompt_length": len(editable_prompt),
        }

    @staticmethod
    def _audit_ledger_issues(ledger: dict[str, Any]) -> list[str]:
        revisions = list(ledger.get("revisions") or [])
        if not revisions:
            return []
        active_revision = _safe_int(ledger.get("active_revision"), 0)
        active_status_count = len([
            item for item in revisions if str(item.get("status") or "") == "active"
        ])
        issues: list[str] = []
        if active_status_count != 1:
            issues.append("invalid_active_revision_count")
        if active_revision and PromptGovernanceService._find_revision(revisions, active_revision) is None:
            issues.append("active_revision_not_found")
        return issues


def get_prompt_governance_service() -> PromptGovernanceService:
    return PromptGovernanceService()
