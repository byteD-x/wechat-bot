from types import SimpleNamespace

from backend.transports.wcferry_adapter import WcferryWeChatClient


def _build_adapter():
    adapter = object.__new__(WcferryWeChatClient)
    adapter._by_wxid = {}
    adapter._name_map = {}
    return adapter


def test_resolve_receiver_accepts_filehelper_display_name():
    adapter = _build_adapter()

    receiver = adapter._resolve_receiver("文件传输助手")

    assert receiver == "filehelper"


def test_resolve_name_exposes_filehelper_display_name():
    adapter = _build_adapter()

    display_name = adapter._resolve_name("filehelper")

    assert display_name == "文件传输助手"


def test_send_msg_normalizes_filehelper_display_name():
    adapter = _build_adapter()
    adapter._wcf = SimpleNamespace(send_text=object())
    captured = {}

    def _fake_wcf_call(label, func, *args, **kwargs):
        captured["label"] = label
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0

    adapter._wcf_call = _fake_wcf_call

    result = adapter.SendMsg("你好", "文件传输助手")

    assert result["success"] is True
    assert result["receiver"] == "filehelper"
    assert captured == {
        "label": "send_text",
        "func": adapter._wcf.send_text,
        "args": ("你好", "filehelper"),
        "kwargs": {"aters": ""},
    }
