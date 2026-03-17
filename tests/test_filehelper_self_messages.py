import sys
import types

sys.modules.setdefault("aiosqlite", types.SimpleNamespace())

from backend.bot import WeChatBot
from backend.config import DEFAULT_CONFIG
from backend.types import MessageEvent


def test_default_config_does_not_ignore_filehelper():
    ignore_names = {
        str(name).strip()
        for name in DEFAULT_CONFIG.get("bot", {}).get("ignore_names", [])
        if str(name).strip()
    }

    assert "文件传输助手" not in ignore_names


def test_prepare_event_for_processing_allows_manual_filehelper_self_message():
    bot = WeChatBot("config.yaml")
    event = MessageEvent(
        chat_name="文件传输助手",
        sender="我自己",
        content="测试一下",
        is_group=False,
        is_at_me=False,
        msg_type="text",
        is_self=True,
        chat_type="friend",
    )

    result = bot._prepare_event_for_processing(event)

    assert result == "accepted_self_filehelper"
    assert event.is_self is False


def test_prepare_event_for_processing_skips_recent_filehelper_echo():
    bot = WeChatBot("config.yaml")
    bot._remember_recent_outgoing_message("文件传输助手", "这是机器人刚发的内容")
    event = MessageEvent(
        chat_name="文件传输助手",
        sender="我自己",
        content="这是机器人刚发的内容",
        is_group=False,
        is_at_me=False,
        msg_type="text",
        is_self=True,
        chat_type="friend",
    )

    result = bot._prepare_event_for_processing(event)

    assert result == "skip_recent_outgoing_echo"
    assert event.is_self is True


def test_prepare_event_for_processing_respects_disabled_filehelper_self_message_flag():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {"allow_filehelper_self_message": False}
    event = MessageEvent(
        chat_name="文件传输助手",
        sender="我自己",
        content="测试一下",
        is_group=False,
        is_at_me=False,
        msg_type="text",
        is_self=True,
        chat_type="friend",
    )

    result = bot._prepare_event_for_processing(event)

    assert result == "self_filtered"
    assert event.is_self is True
