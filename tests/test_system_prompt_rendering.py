from types import SimpleNamespace

from backend.utils.config import resolve_system_prompt


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
    assert "【当前情绪】happy" in rendered
    assert "【建议语气】light" in rendered


def test_resolve_system_prompt_appends_profile_and_emotion_when_no_placeholders():
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
    assert "[User Profile]" in rendered
    assert "[Current Emotion]" in rendered

