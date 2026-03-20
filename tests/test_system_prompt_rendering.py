from types import SimpleNamespace

from backend.utils.config import (
    compose_system_prompt_template,
    extract_editable_system_prompt,
    resolve_system_prompt,
)


def test_resolve_system_prompt_replaces_placeholders():
    bot_cfg = {
        "system_prompt": (
            "# 历史对话\n{history_context}\n\n"
            "# 用户画像\n{user_profile}\n\n"
            "# 当前情境\n{emotion_hint}{time_hint}{style_hint}\n"
        ),
        "system_prompt_overrides": {},
        "profile_inject_in_prompt": True,
        "emotion_inject_in_prompt": True,
    }
    event = SimpleNamespace(chat_name="Alice")
    user_profile = {"nickname": "Bob", "raw_item": "should_not_leak"}
    emotion = SimpleNamespace(
        emotion="happy", confidence=0.9, intensity=4, suggested_tone="light"
    )
    context = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "system", "content": "rag context"},
    ]

    rendered = resolve_system_prompt(event, bot_cfg, user_profile, emotion, context)
    assert "{history_context}" not in rendered
    assert "{user_profile}" not in rendered
    assert "{emotion_hint}" not in rendered
    assert "{time_hint}" not in rendered
    assert "{style_hint}" not in rendered

    assert "User: hello" in rendered
    assert "Assistant: hi" in rendered
    assert "- nickname: Bob" in rendered
    assert "raw_item" not in rendered
    assert "happy" in rendered
    assert "light" in rendered


def test_resolve_system_prompt_appends_required_injections_when_no_placeholders():
    bot_cfg = {
        "system_prompt": "base prompt",
        "system_prompt_overrides": {},
        "profile_inject_in_prompt": True,
        "emotion_inject_in_prompt": True,
    }
    event = SimpleNamespace(chat_name="Alice")
    user_profile = {"nickname": "Bob"}
    emotion = SimpleNamespace(emotion="neutral")

    rendered = resolve_system_prompt(event, bot_cfg, user_profile, emotion, [])
    assert "base prompt" in rendered
    assert "# 用户画像" in rendered
    assert "- nickname: Bob" in rendered
    assert "# 当前情境" in rendered
    assert "【当前情绪】neutral" in rendered


def test_resolve_system_prompt_prefers_contact_prompt_but_still_keeps_required_injections():
    bot_cfg = {
        "system_prompt": "base prompt",
        "system_prompt_overrides": {"Alice": "override prompt"},
        "profile_inject_in_prompt": True,
        "emotion_inject_in_prompt": False,
    }
    event = SimpleNamespace(chat_name="Alice")
    user_profile = {
        "nickname": "Bob",
        "profile_summary": "关系：老朋友",
        "contact_prompt": "contact prompt",
    }
    context = [{"role": "user", "content": "hello again"}]

    rendered = resolve_system_prompt(event, bot_cfg, user_profile, None, context)

    assert rendered.startswith("contact prompt")
    assert "override prompt" not in rendered
    assert "base prompt" not in rendered
    assert "User: hello again" in rendered


def test_system_prompt_helpers_strip_and_rebuild_fixed_injection_block():
    editable = "像本人一样回复，不要太官腔。"
    composed = compose_system_prompt_template(editable)

    assert editable in composed
    assert "{history_context}" in composed
    assert "{user_profile}" in composed
    assert "{emotion_hint}{time_hint}{style_hint}" in composed
    assert extract_editable_system_prompt(composed) == editable


def test_resolve_system_prompt_adds_time_and_style_injections_when_template_lacks_them(
    monkeypatch,
):
    bot_cfg = {
        "system_prompt": "只保留自定义规则",
        "system_prompt_overrides": {},
        "profile_inject_in_prompt": False,
        "emotion_inject_in_prompt": False,
    }
    event = SimpleNamespace(chat_name="Alice")
    context = [
        {"role": "user", "content": "你今天忙吗"},
        {"role": "assistant", "content": "还行，怎么了"},
    ]

    monkeypatch.setattr(
        "backend.core.emotion.get_time_aware_prompt_addition",
        lambda: "【时间感知】现在是晚上，回复可以更放松。",
    )
    monkeypatch.setattr(
        "backend.core.emotion.analyze_conversation_style",
        lambda items: {"style": "casual", "count": len(items)},
    )
    monkeypatch.setattr(
        "backend.core.emotion.get_style_adaptation_hint",
        lambda style_info: "延续对方的口语节奏，保持自然。",
    )

    rendered = resolve_system_prompt(event, bot_cfg, None, None, context)

    assert rendered.startswith("只保留自定义规则")
    assert "【时间感知】现在是晚上，回复可以更放松。" in rendered
    assert "【对话风格】延续对方的口语节奏，保持自然。" in rendered
