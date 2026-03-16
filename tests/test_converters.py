import pytest

from backend.handlers.converters import normalize_new_messages


class _DummyMsg:
    def __init__(self, content: str, sender: str, msg_type: str = "text"):
        self.content = content
        self.sender = sender
        self.type = msg_type
        self.attr = None
        self.is_at_me = False


def test_normalize_new_messages_supports_list_of_chat_bundles():
    raw = [
        {
            "chat_name": "测试群",
            "chat_type": "group",
            "msg": [_DummyMsg("hello", "张三")],
        }
    ]

    events = normalize_new_messages(raw, self_name="机器人")
    assert len(events) == 1
    assert events[0].chat_name == "测试群"
    assert events[0].sender == "张三"
    assert events[0].is_group is True
    assert events[0].msg_type == "text"

