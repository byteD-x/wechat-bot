from types import SimpleNamespace
from unittest.mock import patch

from backend.core.reply_policy import (
    build_chat_id,
    evaluate_reply_policy,
    update_per_chat_override,
)


def _event(*, chat_name="Alice", is_group=False):
    return SimpleNamespace(chat_name=chat_name, is_group=is_group)


def test_reply_policy_prefers_per_chat_override_over_other_rules():
    policy = update_per_chat_override(
        {
            "default_mode": "auto",
            "new_contact_mode": "manual",
            "group_mode": "whitelist_only",
            "sensitive_keywords": ["password"],
        },
        chat_id="friend:Alice",
        mode="auto",
    )

    with patch("backend.core.reply_policy.is_in_quiet_hours", return_value=True):
        result = evaluate_reply_policy(
            _event(chat_name="Alice"),
            bot_cfg={"reply_policy": policy},
            user_text="my password is 1234",
            draft_reply="I can help",
            has_existing_history=False,
        )

    assert result["applied_rule"] == "per_chat_override"
    assert result["mode"] == "auto"
    assert result["should_queue"] is False


def test_reply_policy_queues_sensitive_keywords():
    result = evaluate_reply_policy(
        _event(chat_name="Alice"),
        bot_cfg={
            "reply_policy": {
                "default_mode": "auto",
                "new_contact_mode": "auto",
                "group_mode": "whitelist_only",
                "sensitive_keywords": ["contract"],
            }
        },
        user_text="please send the contract draft",
        draft_reply="I will send the contract",
        has_existing_history=True,
    )

    assert result["applied_rule"] == "sensitive_keyword"
    assert result["matched_keyword"] == "contract"
    assert result["trigger_reason"] == "sensitive_keyword"
    assert result["should_queue"] is True


def test_reply_policy_queues_during_quiet_hours_when_enabled():
    with patch("backend.core.reply_policy.is_in_quiet_hours", return_value=True):
        result = evaluate_reply_policy(
            _event(chat_name="Alice"),
            bot_cfg={
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "auto",
                    "group_mode": "whitelist_only",
                    "quiet_hours": {"start": "00:00", "end": "07:30", "mode": "manual"},
                }
            },
            user_text="hello",
            draft_reply="good morning",
            has_existing_history=True,
        )

    assert result["applied_rule"] == "quiet_hours"
    assert result["trigger_reason"] == "quiet_hours"
    assert result["should_queue"] is True


def test_reply_policy_treats_new_contact_as_manual_by_default():
    with patch("backend.core.reply_policy.is_in_quiet_hours", return_value=False):
        result = evaluate_reply_policy(
            _event(chat_name="Alice"),
            bot_cfg={
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "manual",
                    "group_mode": "whitelist_only",
                }
            },
            user_text="hello",
            draft_reply="hi there",
            has_existing_history=False,
        )

    assert result["applied_rule"] == "new_contact_mode"
    assert result["trigger_reason"] == "new_contact_manual"
    assert result["should_queue"] is True


def test_reply_policy_respects_group_whitelist_mode():
    with patch("backend.core.reply_policy.is_in_quiet_hours", return_value=False):
        result = evaluate_reply_policy(
            _event(chat_name="Team Group", is_group=True),
            bot_cfg={
                "whitelist": [],
                "reply_policy": {
                    "default_mode": "auto",
                    "new_contact_mode": "manual",
                    "group_mode": "whitelist_only",
                },
            },
            user_text="@bot status",
            draft_reply="All green",
            has_existing_history=True,
        )

    assert result["applied_rule"] == "group_mode"
    assert result["trigger_reason"] == "group_not_in_whitelist"
    assert result["should_queue"] is True


def test_reply_policy_prefers_stable_raw_chat_id_but_keeps_legacy_override_match():
    raw_item = SimpleNamespace(chat_id="wxid_alice", sender_id="wxid_alice")
    event = _event(chat_name="Alice")
    event.raw_item = raw_item

    policy = update_per_chat_override(
        {
            "default_mode": "manual",
            "new_contact_mode": "manual",
            "group_mode": "whitelist_only",
        },
        chat_id="friend:Alice",
        mode="auto",
    )

    result = evaluate_reply_policy(
        event,
        bot_cfg={"reply_policy": policy},
        user_text="hello",
        draft_reply="hi there",
        has_existing_history=False,
    )

    assert build_chat_id(event) == "friend:wxid_alice"
    assert result["chat_id"] == "friend:wxid_alice"
    assert result["applied_rule"] == "per_chat_override"
    assert result["mode"] == "auto"
    assert result["should_queue"] is False
