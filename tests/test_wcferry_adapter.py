from types import SimpleNamespace

import backend.transports.wcferry_adapter as wcferry_adapter_module
from backend.transports.wcferry_adapter import WcferryTransport


def _build_adapter():
    adapter = object.__new__(WcferryTransport)
    adapter._by_wxid = {}
    adapter._name_map = {}
    return adapter


def test_powershell_decodes_gb18030_chinese_path(monkeypatch):
    monkeypatch.setattr(
        wcferry_adapter_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=r"E:\腾讯\WeChat.exe".encode("gb18030"),
        ),
    )

    assert wcferry_adapter_module._powershell("Get-Process WeChat | Select-Object -First 1 -ExpandProperty Path") == r"E:\腾讯\WeChat.exe"


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

    result = adapter.send_text("你好", "文件传输助手")

    assert result["success"] is True
    assert result["receiver"] == "filehelper"
    assert captured == {
        "label": "send_text",
        "func": adapter._wcf.send_text,
        "args": ("你好", "filehelper"),
        "kwargs": {"aters": ""},
    }
