import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.modules.setdefault("aiosqlite", types.SimpleNamespace())

from backend.bot import WeChatBot


def _build_mock_bot_manager():
    manager = MagicMock()
    manager.update_startup_state = AsyncMock()
    manager.notify_status_change = AsyncMock()
    manager.broadcast_event = AsyncMock()
    manager.apply_pause_state = AsyncMock()
    manager.set_issue = MagicMock()
    manager.clear_issue = MagicMock()
    manager._invalidate_status_cache = MagicMock()
    return manager


@pytest.mark.asyncio
async def test_send_smart_reply_skips_suffix_only_payload():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "emoji_policy": "strip",
        "reply_suffix": " [bot]",
    }
    event = SimpleNamespace(chat_name="chat", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks:
        sent = await bot._send_smart_reply(MagicMock(), event, "😀")

    assert sent == ""
    mock_send_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_and_reply_empty_reply_does_not_send_suffix_only_fallback():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {
        "reply_deadline_sec": 2.0,
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.0,
        "min_reply_interval_sec": 0.0,
        "emoji_policy": "strip",
        "reply_suffix": " [bot]",
    }
    bot.agent_cfg = {"enabled": True}
    bot.sem = asyncio.Semaphore(1)
    bot.wx_lock = asyncio.Lock()
    bot.memory = None
    bot.vector_memory = None
    bot.export_rag = None
    bot.runtime_preset_name = "Ollama"
    bot._record_reply_stats = MagicMock()
    bot._set_ai_health = MagicMock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.ipc = MagicMock()
    bot.bot_manager = _build_mock_bot_manager()

    prepared = SimpleNamespace(
        timings={},
        trace={},
        response_metadata={},
    )

    bot.ai_client = SimpleNamespace(
        prepare_request=AsyncMock(return_value=prepared),
        invoke=AsyncMock(return_value=""),
        finalize_request=AsyncMock(),
        get_status=MagicMock(return_value={"engine": "langgraph"}),
        model="test-model",
    )

    event = SimpleNamespace(
        chat_name="filehelper",
        sender="wxid_xxx",
        content="hello",
        is_group=False,
        msg_type="text",
        raw_item=None,
        timestamp=None,
    )

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks:
        await bot._process_and_reply(MagicMock(), event, "hello", "hello")

    bot.ai_client.invoke.assert_awaited_once_with(prepared)
    mock_send_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_smart_reply_fast_mode_skips_natural_split():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_deadline_sec": 2.0,
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.5,
        "min_reply_interval_sec": 0.2,
        "natural_split_enabled": True,
        "natural_split_min_chars": 1,
        "natural_split_max_chars": 2,
        "natural_split_max_segments": 3,
        "natural_split_delay_sec": [1.0, 1.0],
        "emoji_policy": "keep",
        "reply_suffix": " [bot]",
    }

    bot.ai_client = SimpleNamespace(model="test-model")
    event = SimpleNamespace(chat_name="filehelper", content="hello", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks:
        sent = await bot._send_smart_reply(MagicMock(), event, "done")

    assert mock_send_chunks.await_count == 1
    sent_text = mock_send_chunks.await_args.args[2]
    assert sent_text == "done[bot]"
    assert sent == "done[bot]"


def test_build_final_reply_text_uses_suffix_after_sanitizing():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {
        "emoji_policy": "strip",
        "reply_suffix": " [bot]",
    }
    bot.ai_client = SimpleNamespace(model="test-model")

    assert bot._build_final_reply_text("hi😀") == "hi[bot]"


def test_get_natural_split_config_normalizes_reversed_delay_range():
    bot = WeChatBot("config.yaml")
    bot.bot_cfg = {
        "natural_split_min_chars": 20,
        "natural_split_max_chars": 50,
        "natural_split_max_segments": 4,
        "natural_split_delay_sec": [0.9, 0.2],
    }

    config = bot._get_natural_split_config()

    assert config["min_chars"] == 20
    assert config["max_chars"] == 50
    assert config["max_segments"] == 4
    assert config["delay_min"] == 0.2
    assert config["delay_max"] == 0.9
