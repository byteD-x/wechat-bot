import unittest
from unittest.mock import MagicMock, patch

from backend.handlers.converters import normalize_message_item
from backend.handlers.sender import send_quote_message, parse_send_result


class SenderHandlersTest(unittest.TestCase):
    def test_send_quote_message_exception_retry(self):
        quote_item = MagicMock()
        # First call raises exception, second succeeds
        quote_item.quote.side_effect = [Exception("First fail"), "Success"]

        with patch("time.sleep") as mock_sleep:
            success, _ = send_quote_message(quote_item, "text", 5.0)

        self.assertTrue(success)
        self.assertEqual(quote_item.quote.call_count, 2)
        mock_sleep.assert_called_once_with(0.3)

    def test_parse_send_result_uses_is_success_flag(self):
        class MockResult:
            def __init__(self, is_success):
                self.is_success = is_success
                self.message = "done"

            def __bool__(self):
                # 模拟底层对象总是 truthy，避免 bool(result) 误判
                return True

        self.assertEqual(parse_send_result(MockResult(True)), (True, "done"))
        self.assertEqual(parse_send_result(MockResult(False)), (False, "done"))

    def test_parse_send_result_accepts_zero_status_code(self):
        self.assertEqual(parse_send_result(0), (True, None))
        self.assertEqual(parse_send_result(1), (False, "1"))

    def test_parse_send_result_accepts_success_status_text(self):
        self.assertEqual(parse_send_result({"status": "成功", "message": "ok"}), (True, "ok"))
        self.assertEqual(parse_send_result({"status": "success", "message": "ok"}), (True, "ok"))
        self.assertEqual(parse_send_result({"status": "失败", "message": "bad"}), (False, "bad"))


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
