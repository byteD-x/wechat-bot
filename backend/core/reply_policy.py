from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from backend.config_schemas import ReplyPolicyConfig
from backend.core.bot_control import is_in_quiet_hours


AUTO_MODE = "auto"
MANUAL_MODE = "manual"
WHITELIST_ONLY_MODE = "whitelist_only"


def build_chat_id(event: Any) -> str:
    chat_name = str(getattr(event, "chat_name", "") or "").strip()
    return f"group:{chat_name}" if bool(getattr(event, "is_group", False)) else f"friend:{chat_name}"


def normalize_reply_policy(policy: Any = None) -> Dict[str, Any]:
    if isinstance(policy, ReplyPolicyConfig):
        return policy.model_dump(mode="json")
    return ReplyPolicyConfig(**deepcopy(policy or {})).model_dump(mode="json")


def update_per_chat_override(
    policy: Dict[str, Any],
    *,
    chat_id: str,
    mode: str,
) -> Dict[str, Any]:
    normalized = normalize_reply_policy(policy)
    target_chat_id = str(chat_id or "").strip()
    next_mode = str(mode or "").strip().lower()
    overrides = [
        item
        for item in list(normalized.get("per_chat_overrides") or [])
        if str((item or {}).get("chat_id") or "").strip() != target_chat_id
    ]
    if target_chat_id and next_mode in {AUTO_MODE, MANUAL_MODE}:
        overrides.append({"chat_id": target_chat_id, "mode": next_mode})
    normalized["per_chat_overrides"] = overrides
    return normalized


def _find_chat_override(policy: Dict[str, Any], chat_id: str) -> Optional[Dict[str, Any]]:
    target_chat_id = str(chat_id or "").strip()
    for item in list(policy.get("per_chat_overrides") or []):
        if str((item or {}).get("chat_id") or "").strip() == target_chat_id:
            return dict(item or {})
    return None


def _match_sensitive_keyword(policy: Dict[str, Any], user_text: str, draft_reply: str) -> str:
    haystacks = [str(user_text or "").lower(), str(draft_reply or "").lower()]
    for raw_keyword in list(policy.get("sensitive_keywords") or []):
        keyword = str(raw_keyword or "").strip().lower()
        if not keyword:
            continue
        if any(keyword in item for item in haystacks):
            return keyword
    return ""


def evaluate_reply_policy(
    event: Any,
    *,
    bot_cfg: Optional[Dict[str, Any]] = None,
    user_text: str = "",
    draft_reply: str = "",
    has_existing_history: bool = False,
) -> Dict[str, Any]:
    config = dict(bot_cfg or {})
    policy = normalize_reply_policy(config.get("reply_policy"))
    chat_id = build_chat_id(event)
    is_group = bool(getattr(event, "is_group", False))

    result: Dict[str, Any] = {
        "chat_id": chat_id,
        "mode": AUTO_MODE,
        "should_queue": False,
        "trigger_reason": "",
        "matched_keyword": "",
        "applied_rule": "default_mode",
        "policy": policy,
    }

    override = _find_chat_override(policy, chat_id)
    override_mode = str((override or {}).get("mode") or "").strip().lower()
    if override_mode in {AUTO_MODE, MANUAL_MODE}:
        result["mode"] = override_mode
        result["applied_rule"] = "per_chat_override"
        if override_mode == MANUAL_MODE:
            result["should_queue"] = True
            result["trigger_reason"] = "per_chat_override_manual"
        return result

    matched_keyword = _match_sensitive_keyword(policy, user_text, draft_reply)
    if matched_keyword:
        result["mode"] = MANUAL_MODE
        result["should_queue"] = True
        result["trigger_reason"] = "sensitive_keyword"
        result["matched_keyword"] = matched_keyword
        result["applied_rule"] = "sensitive_keyword"
        return result

    quiet_hours = dict(policy.get("quiet_hours") or {})
    quiet_hours_mode = str(quiet_hours.get("mode") or MANUAL_MODE).strip().lower()
    quiet_start = str(quiet_hours.get("start") or "00:00").strip() or "00:00"
    quiet_end = str(quiet_hours.get("end") or "07:30").strip() or "07:30"
    if quiet_hours_mode in {AUTO_MODE, MANUAL_MODE} and is_in_quiet_hours(quiet_start, quiet_end):
        result["mode"] = quiet_hours_mode
        result["applied_rule"] = "quiet_hours"
        if quiet_hours_mode == MANUAL_MODE:
            result["should_queue"] = True
            result["trigger_reason"] = "quiet_hours"
        return result

    if is_group:
        group_mode = str(policy.get("group_mode") or WHITELIST_ONLY_MODE).strip().lower()
        result["applied_rule"] = "group_mode"
        if group_mode == MANUAL_MODE:
            result["mode"] = MANUAL_MODE
            result["should_queue"] = True
            result["trigger_reason"] = "group_manual"
            return result
        if group_mode == WHITELIST_ONLY_MODE:
            whitelist = {
                str(item or "").strip()
                for item in list(config.get("whitelist") or [])
                if str(item or "").strip()
            }
            if str(getattr(event, "chat_name", "") or "").strip() not in whitelist:
                result["mode"] = MANUAL_MODE
                result["should_queue"] = True
                result["trigger_reason"] = "group_not_in_whitelist"
                return result
    elif not has_existing_history:
        new_contact_mode = str(policy.get("new_contact_mode") or MANUAL_MODE).strip().lower()
        result["mode"] = new_contact_mode
        result["applied_rule"] = "new_contact_mode"
        if new_contact_mode == MANUAL_MODE:
            result["should_queue"] = True
            result["trigger_reason"] = "new_contact_manual"
        return result

    default_mode = str(policy.get("default_mode") or AUTO_MODE).strip().lower()
    result["mode"] = default_mode
    result["applied_rule"] = "default_mode"
    if default_mode == MANUAL_MODE:
        result["should_queue"] = True
        result["trigger_reason"] = "default_manual"
    return result

