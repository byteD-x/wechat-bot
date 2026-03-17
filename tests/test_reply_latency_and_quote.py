import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.modules.setdefault("aiosqlite", types.SimpleNamespace())

from backend.bot import WeChatBot


@pytest.mark.asyncio
async def test_send_smart_reply_fast_mode_forces_zero_send_delays():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_deadline_sec": 2.0,
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.8,
        "min_reply_interval_sec": 0.6,
        "emoji_policy": "keep",
        "reply_suffix": "",
    }
    bot.ai_client = SimpleNamespace(model="test-model")
    event = SimpleNamespace(chat_name="文件传输助手", content="你好", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks:
        sent = await bot._send_smart_reply(MagicMock(), event, "你好你好世界世界")

    mock_send_chunks.assert_awaited_once()
    assert mock_send_chunks.await_args.args[2] == "你好你好世界世界"
    assert mock_send_chunks.await_args.args[5] == 0.0
    assert mock_send_chunks.await_args.args[6] == 0.0
    assert sent == "你好你好世界世界"


@pytest.mark.asyncio
async def test_send_smart_reply_without_deadline_uses_configured_send_delays():
    bot = WeChatBot("config.yaml")
    bot.wx_lock = asyncio.Lock()
    bot.last_reply_ts = {"ts": 0.0}
    bot.bot_cfg = {
        "reply_chunk_size": 500,
        "reply_chunk_delay_sec": 0.8,
        "min_reply_interval_sec": 0.6,
        "emoji_policy": "keep",
        "reply_suffix": "",
    }
    bot.ai_client = SimpleNamespace(model="test-model")
    event = SimpleNamespace(chat_name="文件传输助手", content="你好", sender="user", raw_item=None)

    with patch("backend.bot.send_reply_chunks", new=AsyncMock(return_value=(True, None))) as mock_send_chunks:
        sent = await bot._send_smart_reply(MagicMock(), event, "你好你好世界世界")

    mock_send_chunks.assert_awaited_once()
    assert mock_send_chunks.await_args.args[2] == "你好你好世界世界"
    assert mock_send_chunks.await_args.args[5] == 0.8
    assert mock_send_chunks.await_args.args[6] == 0.6
    assert sent == "你好你好世界世界"
