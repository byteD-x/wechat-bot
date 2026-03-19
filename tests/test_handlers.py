import asyncio
import unittest
from unittest.mock import MagicMock, patch

from backend.handlers.converters import normalize_message_item
from backend.handlers.sender import parse_send_result, send_reply_chunks


class SenderHandlersTest(unittest.TestCase):
    def test_parse_send_result_uses_is_success_flag(self):
        class MockResult:
            def __init__(self, is_success):
                self.is_success = is_success
                self.message = "done"

            def __bool__(self):
                return True

        self.assertEqual(parse_send_result(MockResult(True)), (True, "done"))
        self.assertEqual(parse_send_result(MockResult(False)), (False, "done"))

    def test_parse_send_result_accepts_zero_status_code(self):
        self.assertEqual(parse_send_result(0), (True, None))
        self.assertEqual(parse_send_result(1), (False, "1"))

    def test_parse_send_result_does_not_treat_false_as_success(self):
        self.assertEqual(
            parse_send_result(False),
            (False, "send_text returned False"),
        )

    def test_parse_send_result_accepts_success_status_text(self):
        self.assertEqual(parse_send_result({"status": "成功", "message": "ok"}), (True, "ok"))
        self.assertEqual(parse_send_result({"status": "success", "message": "ok"}), (True, "ok"))
        self.assertEqual(parse_send_result({"status": "失败", "message": "bad"}), (False, "bad"))


class SendReplyChunksTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_reply_chunks_sends_plain_text(self):
        wx = MagicMock()
        lock = asyncio.Lock()

        with patch(
            "backend.handlers.sender.send_message",
            return_value=(True, None),
        ) as mock_send:
            ok, err = await send_reply_chunks(
                wx=wx,
                chat_name="文件传输助手",
                text="hello",
                bot_cfg={},
                chunk_size=500,
                chunk_delay_sec=0.0,
                min_reply_interval=0.0,
                last_reply_ts={},
                wx_lock=lock,
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_send.assert_called_once_with(wx, "文件传输助手", "hello", {})


class ConvertersTest(unittest.TestCase):
    def test_normalize_msg_item_bad_timestamp(self):
        class MockItem:
            pass

        mock_item = MockItem()
        mock_item.type = "friend"
        mock_item.content = "hello"
        mock_item.sender = "user"
        mock_item.time = "invalid_timestamp"

        event = normalize_message_item("chat", mock_item, "me", "friend")
        self.assertIsNotNone(event)
        self.assertIsNone(event.timestamp)

    def test_normalize_msg_item_honors_explicit_at_me(self):
        class MockItem:
            pass

        mock_item = MockItem()
        mock_item.type = "text"
        mock_item.content = "hello"
        mock_item.sender = "user"
        mock_item.is_at_me = True

        event = normalize_message_item("group", mock_item, "me", "group")
        self.assertIsNotNone(event)
        self.assertTrue(event.is_at_me)


if __name__ == "__main__":
    unittest.main()
