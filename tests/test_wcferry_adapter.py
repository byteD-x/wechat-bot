import sys
from queue import Queue
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

    assert wcferry_adapter_module._powershell(
        "Get-Process WeChat | Select-Object -First 1 -ExpandProperty Path"
    ) == r"E:\腾讯\WeChat.exe"


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


def test_enable_receiving_msg_robust_keeps_socket_on_idle_timeout(monkeypatch):
    adapter = _build_adapter()
    adapter._recv_ready = wcferry_adapter_module.threading.Event()
    adapter._recv_last_error = ""

    class _FakeTimeout(Exception):
        pass

    class _FakePair1:
        dial_count = 0

        def __init__(self):
            self.send_timeout = 0
            self.recv_timeout = 0

        def dial(self, _url, block=True):
            type(self).dial_count += 1

        def close(self):
            return None

        def recv_msg(self):
            adapter._wcf._is_receiving_msg = False
            raise _FakeTimeout("idle")

    class _FakeRequest:
        def __init__(self):
            self.func = 0
            self.flag = False

    class _FakeResponse:
        def __init__(self):
            self.status = 0
            self.wxmsg = object()

        def ParseFromString(self, _payload):
            return None

    fake_wcf_pb2 = SimpleNamespace(
        Request=_FakeRequest,
        Response=_FakeResponse,
        FUNC_ENABLE_RECV_TXT=1,
    )
    fake_wxmsg_module = SimpleNamespace(WxMsg=lambda payload: payload)
    fake_pynng_module = SimpleNamespace(Pair1=_FakePair1, Timeout=_FakeTimeout)
    fake_wcferry_module = SimpleNamespace(
        wcf_pb2=fake_wcf_pb2,
        wxmsg=fake_wxmsg_module,
    )

    monkeypatch.setitem(sys.modules, "wcferry", fake_wcferry_module)
    monkeypatch.setitem(sys.modules, "wcferry.wcf_pb2", fake_wcf_pb2)
    monkeypatch.setitem(sys.modules, "wcferry.wxmsg", fake_wxmsg_module)
    monkeypatch.setitem(sys.modules, "pynng", fake_pynng_module)
    monkeypatch.setattr(wcferry_adapter_module.time, "sleep", lambda _seconds: None)

    class _ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr(wcferry_adapter_module.threading, "Thread", _ImmediateThread)

    adapter._wcf = SimpleNamespace(
        _is_receiving_msg=False,
        _send_request=lambda req: SimpleNamespace(status=0),
        msg_url="tcp://127.0.0.1:10087",
        msg_socket=None,
        msgQ=Queue(),
        disable_recv_msg=lambda: None,
    )
    adapter._wcf_call = lambda _label, func, *args, **kwargs: func(*args, **kwargs)

    adapter._enable_receiving_msg_robust()

    assert adapter._recv_ready.is_set() is True
    assert _FakePair1.dial_count == 1
