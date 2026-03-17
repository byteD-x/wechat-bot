"""wxauto-compatible silent backend powered by wcferry."""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from queue import Empty
from typing import Any, Dict, List, Optional

from .audio_transcription import transcribe_audio_file
from .base import BaseTransport
from ..utils.runtime_artifacts import (
    WCFERRY_DIR,
    chdir_temporarily,
    ensure_runtime_directories,
    relocate_known_root_artifacts,
)

logger = logging.getLogger(__name__)
_VERSION_PATTERN = re.compile(rb"3\.9\.\d{1,2}\.\d{1,2}")
_WCFERRY_MSG_DIAL_TIMEOUT_SEC = 12.0
_WCFERRY_MSG_DIAL_RETRY_INTERVAL_SEC = 0.6
_WCFERRY_ENABLE_RECV_TIMEOUT_SEC = 18.0
_WCFERRY_ENABLE_RECV_RETRY_INTERVAL_SEC = 1.0
_WCFERRY_DEFAULT_HOST = "127.0.0.1"
_WCFERRY_DEFAULT_PORT = 10086
_SPECIAL_CONTACT_DISPLAY_NAMES = {
    "filehelper": "文件传输助手",
}


class TransportUnavailableError(RuntimeError):
    """Raised when the requested transport cannot be initialized."""


@dataclass(slots=True)
class TransportStatus:
    backend: str
    silent_mode: bool
    wechat_version: str = ""
    required_version: str = ""
    supports_native_quote: bool = False
    supports_voice_transcription: bool = True
    status: str = "unknown"
    warning: str = ""


def _powershell(command: str) -> str:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    return (completed.stdout or "").strip()


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes  # type: ignore

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


@contextmanager
def _prevent_os_exit() -> Any:
    """
    wcferry uses os._exit() on some init/RPC failures, which would kill the entire backend process.
    Temporarily override it so we can surface a readable error and keep the API server alive.
    """

    original = getattr(os, "_exit", None)

    def _raise(code: int) -> None:
        raise RuntimeError(f"os._exit({code}) called by wcferry")

    try:
        if callable(original):
            os._exit = _raise  # type: ignore[assignment]
        yield
    finally:
        if callable(original):
            os._exit = original  # type: ignore[assignment]


def _best_effort_wcf_call(label: str, func, timeout_sec: float = 2.0) -> bool:
    if not callable(func):
        return False

    outcome: Dict[str, Optional[BaseException]] = {"error": None}

    def _runner() -> None:
        try:
            func()
        except BaseException as exc:  # pragma: no cover - defensive path
            outcome["error"] = exc

    thread = threading.Thread(
        target=_runner,
        name=f"WcferryCleanup:{label}",
        daemon=True,
    )
    thread.start()
    thread.join(max(float(timeout_sec or 0.0), 0.01))
    if thread.is_alive():
        logger.warning("wcferry cleanup step timed out: %s", label)
        return False
    if outcome["error"] is not None:
        logger.debug("wcferry cleanup step failed: %s | %s", label, outcome["error"])
        return False
    return True


def _is_tcp_port_open(host: str, port: int, timeout_sec: float = 0.25) -> bool:
    try:
        with socket.create_connection(
            (str(host or _WCFERRY_DEFAULT_HOST), int(port)),
            timeout=max(float(timeout_sec or 0.0), 0.05),
        ):
            return True
    except OSError:
        return False


def _get_wcf_sdk_path() -> Optional[Path]:
    try:
        import wcferry
    except ImportError:
        return None

    package_root = Path(getattr(wcferry, "__file__", "")).resolve().parent
    sdk_path = package_root / "sdk.dll"
    return sdk_path if sdk_path.exists() else None


def _destroy_stale_local_wcf_session() -> bool:
    sdk_path = _get_wcf_sdk_path()
    if sdk_path is None:
        return False

    try:
        import ctypes  # type: ignore

        sdk = ctypes.cdll.LoadLibrary(str(sdk_path))
        sdk.WxDestroySDK()
        try:
            ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.wintypes.HMODULE]
            ctypes.windll.kernel32.FreeLibrary(sdk._handle)
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.debug("best-effort stale wcferry cleanup failed: %s", exc)
        return False


def _cleanup_stale_wcferry_ports(
    host: str = _WCFERRY_DEFAULT_HOST,
    base_port: int = _WCFERRY_DEFAULT_PORT,
    wait_timeout_sec: float = 3.0,
) -> bool:
    ports = (int(base_port), int(base_port) + 1)
    if not any(_is_tcp_port_open(host, port) for port in ports):
        return False

    logger.warning(
        "Detected stale local wcferry listeners on %s; destroying previous SDK session before reinjection",
        ",".join(str(port) for port in ports),
    )
    _destroy_stale_local_wcf_session()

    deadline = time.time() + max(float(wait_timeout_sec or 0.0), 0.2)
    while time.time() < deadline:
        if not any(_is_tcp_port_open(host, port) for port in ports):
            return True
        time.sleep(0.2)

    return not any(_is_tcp_port_open(host, port) for port in ports)


def _count_running_wechat_processes() -> int:
    raw = _powershell(
        "((Get-Process WeChat,Weixin -ErrorAction SilentlyContinue) | Measure-Object).Count"
    )
    try:
        return int(str(raw or "0").strip())
    except (TypeError, ValueError):
        return 0


def _build_local_wcferry_recovery_hint() -> str:
    details: List[str] = []
    ports = (_WCFERRY_DEFAULT_PORT, _WCFERRY_DEFAULT_PORT + 1)
    if any(_is_tcp_port_open(_WCFERRY_DEFAULT_HOST, port) for port in ports):
        details.append(
            f"本机 {_WCFERRY_DEFAULT_HOST}:{ports[0]}/{ports[1]} 仍有旧的 wcferry 监听"
        )

    process_count = _count_running_wechat_processes()
    if process_count > 1:
        details.append(f"检测到 {process_count} 个 WeChat.exe 进程")

    if not details:
        return ""

    return (
        "；".join(details)
        + "。请先完全退出所有微信进程，再重新打开并登录 1 个微信后重试。"
    )


def detect_wechat_path() -> str:
    candidates: List[str] = []
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat") as key:
            install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            if install_path:
                candidates.append(os.path.join(install_path, "WeChat.exe"))
    except Exception:
        pass

    candidates.extend(
        [
            r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            r"D:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
            r"D:\Program Files\Tencent\WeChat\WeChat.exe",
        ]
    )
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return os.path.abspath(candidate)

    # Fallback: detect from running process (helps when installed in a non-standard location).
    try:
        proc_path = _powershell(
            "(Get-Process WeChat,Weixin -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty Path)"
        )
        if proc_path and os.path.exists(proc_path):
            return os.path.abspath(proc_path)
    except Exception:
        pass
    return ""


def detect_wechat_version(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    escaped = path.replace("\\", "\\\\").replace("'", "''")
    return _powershell(f"(Get-Item '{escaped}').VersionInfo.FileVersion")


def _matches_version_rule(version: str, rule: str) -> bool:
    current = str(version or "").strip()
    wanted = str(rule or "").strip()
    if not wanted or not current:
        return True
    for raw_part in wanted.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part.endswith("*"):
            if current.startswith(part[:-1]):
                return True
            continue
        if current == part:
            return True
    return False


def _version_sort_key(version: str) -> tuple[int, ...]:
    parts = []
    for part in str(version or "").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _extract_supported_wechat_versions(binary_path: Path) -> List[str]:
    if not binary_path.exists():
        return []

    raw = binary_path.read_bytes()
    matches = {
        match.group().decode("ascii", errors="ignore")
        for match in _VERSION_PATTERN.finditer(raw)
    }
    if not matches:
        decoded = raw.decode("utf-16le", errors="ignore")
        matches = set(re.findall(r"3\.9\.\d{1,2}\.\d{1,2}", decoded))
    return sorted(matches, key=_version_sort_key)


@lru_cache(maxsize=1)
def detect_wcferry_supported_versions() -> List[str]:
    try:
        import wcferry
    except ImportError:
        return []

    package_root = Path(getattr(wcferry, "__file__", "")).resolve().parent
    if not package_root.exists():
        return []
    return _extract_supported_wechat_versions(package_root / "spy.dll")


class WcfMessageItem:
    """Minimal message wrapper compatible with current bot helpers."""

    def __init__(
        self,
        adapter: "WcferryWeChatClient",
        raw: Any,
        *,
        chat_id: str,
        chat_name: str,
        sender_name: str,
        msg_type: str,
    ) -> None:
        self._adapter = adapter
        self._raw = raw
        self.chat_id = chat_id
        self.chat_name = chat_name
        self.sender = sender_name
        self.sender_id = raw.sender
        self.type = msg_type
        self.attr = "self" if raw.from_self() else None
        self.timestamp = float(getattr(raw, "ts", 0) or 0) or None
        self.time = self.timestamp
        self.id = getattr(raw, "id", None)
        self.xml = getattr(raw, "xml", "") or ""
        self.thumb = getattr(raw, "thumb", "") or ""
        self.extra = getattr(raw, "extra", "") or ""
        self.roomid = getattr(raw, "roomid", "") or ""
        self.is_at_me = bool(raw.is_at(adapter.self_wxid)) if raw.from_group() else False
        self.content = self._build_content(raw, msg_type)

    @staticmethod
    def _build_content(raw: Any, msg_type: str) -> str:
        content = str(getattr(raw, "content", "") or "").strip()
        if msg_type == "image":
            return "[图片]"
        if msg_type == "voice":
            return content or "[语音]"
        if msg_type == "file":
            return content or "[文件]"
        return content

    def SaveFile(self, path: str) -> str:
        return self._adapter.save_media(self, path)

    def to_text(self) -> Any:
        return self._adapter.transcribe_voice(self)

    def quote(self, msg: str, timeout: Optional[float] = None) -> bool:
        # wcferry does not expose a simple native reply API. The caller will
        # fallback to text quote when enabled.
        return False


class WcferryWeChatClient(BaseTransport):
    """Silent WeChat backend that mimics the wxauto methods used by the bot."""

    backend_name = "hook_wcferry"

    def __init__(self, bot_cfg: Dict[str, Any], ai_client: Optional[Any] = None) -> None:
        self.bot_cfg = dict(bot_cfg or {})
        self.ai_client = ai_client
        self._uses_local_wcf_sdk = False
        self.configured_required_version = str(
            self.bot_cfg.get("required_wechat_version") or ""
        ).strip()
        self.supported_wechat_versions = detect_wcferry_supported_versions()
        self.required_version = self.configured_required_version or ",".join(
            self.supported_wechat_versions
        )
        self.wechat_path = detect_wechat_path()
        self.wechat_version = detect_wechat_version(self.wechat_path)
        self.transport_status = TransportStatus(
            backend=self.backend_name,
            silent_mode=True,
            wechat_version=self.wechat_version,
            required_version=self.required_version,
            supports_native_quote=False,
            supports_voice_transcription=True,
        )
        self._validate_version_gate()

        try:
            from wcferry import Wcf
        except ImportError as exc:
            raise TransportUnavailableError("wcferry not installed") from exc

        try:
            if os.name == "nt" and not _is_windows_admin():
                raise TransportUnavailableError(
                    "wcferry 注入需要管理员权限：请用“以管理员身份运行”启动本项目（Electron/后端），并确保微信已启动且已登录。"
                )
            ensure_runtime_directories()
            with chdir_temporarily(WCFERRY_DIR):
                _cleanup_stale_wcferry_ports()
                # Use non-blocking mode and handle login wait ourselves so backend startup
                # won't hang indefinitely if WeChat isn't ready yet.
                with _prevent_os_exit():
                    self._wcf = Wcf(debug=False, block=False)
                    self._uses_local_wcf_sdk = True
            relocate_known_root_artifacts()
        except Exception as exc:
            message = str(exc)
            if "os._exit(-1)" in message or "注入失败" in message or "load_ctx" in message:
                hint = _build_local_wcferry_recovery_hint()
                if hint:
                    message = f"{message}；{hint}"
            raise TransportUnavailableError(message) from exc

        try:
            if not self._wait_for_login(timeout_sec=18.0):
                raise TransportUnavailableError("wechat not logged in")

            self._recv_ready = threading.Event()
            self._recv_last_error = ""

            self.self_wxid = self._wcf_call(
                "get_self_wxid",
                self._wcf.get_self_wxid,
            )
            self.self_name = str(self.bot_cfg.get("self_name") or "").strip()
            self._contacts = self._wcf_call("get_contacts", self._wcf.get_contacts)
            self._refresh_contact_maps()
            self._enable_receiving_msg_robust()

            self.transport_status.status = "connected"
        except Exception:
            # Best-effort cleanup; otherwise a failed init can leave stray RPC threads
            # and block subsequent restarts (appearing as a "hang").
            try:
                self._wcf._is_receiving_msg = False
            except Exception:
                pass
            _best_effort_wcf_call("disable_recv_msg", getattr(self._wcf, "disable_recv_msg", None))
            _best_effort_wcf_call("cleanup", getattr(self._wcf, "cleanup", None))
            if self._uses_local_wcf_sdk:
                _destroy_stale_local_wcf_session()
            relocate_known_root_artifacts()
            raise

    def _wait_for_login(self, timeout_sec: float = 15.0) -> bool:
        deadline = time.time() + float(timeout_sec or 0.0)
        while time.time() < deadline:
            if self._wcf_call("is_login", self._wcf.is_login):
                return True
            time.sleep(0.6)
        return False

    def _wcf_call(self, label: str, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SystemExit as exc:
            # wcferry internally uses sys.exit() on some RPC errors. Never let that kill our backend process.
            raise TransportUnavailableError(f"wcferry call exited during {label}") from exc

    def _enable_receiving_msg_robust(self) -> None:
        """
        Enable receiving messages with a retrying dial loop.

        wcferry's built-in enable_receiving_msg starts a daemon thread that dials msg_url once.
        If the server opens the msg port slightly later, that dial can fail with ConnectionRefused,
        killing the thread while _is_receiving_msg stays True. We implement a small, resilient
        receive loop to make startup reliable.
        """
        try:
            from wcferry import wcf_pb2
            from wcferry.wxmsg import WxMsg
            import pynng
        except Exception as exc:
            raise TransportUnavailableError("wcferry runtime unavailable") from exc

        if getattr(self._wcf, "_is_receiving_msg", False):
            # Another instance may have enabled it already; still require the msg channel to be ready.
            if self._recv_ready.is_set():
                return

        deadline = time.time() + _WCFERRY_ENABLE_RECV_TIMEOUT_SEC
        last_error = ""
        rsp = None
        while time.time() < deadline:
            req = wcf_pb2.Request()
            req.func = wcf_pb2.FUNC_ENABLE_RECV_TXT  # FUNC_ENABLE_RECV_TXT
            req.flag = False
            try:
                rsp = self._wcf_call("enable_recv_txt", self._wcf._send_request, req)
                if getattr(rsp, "status", 1) == 0:
                    break
                last_error = f"enable_recv_txt status={getattr(rsp, 'status', 'unknown')}"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(_WCFERRY_ENABLE_RECV_RETRY_INTERVAL_SEC)

        if rsp is None or getattr(rsp, "status", 1) != 0:
            raise TransportUnavailableError(
                f"failed to enable message receiving: {last_error or 'timeout'}"
            )

        # Match wcferry's state flag so other API calls behave consistently.
        self._wcf._is_receiving_msg = True

        def _connect_msg_socket(deadline_ts: float) -> bool:
            last_exc: Optional[BaseException] = None
            while self._wcf._is_receiving_msg and time.time() < deadline_ts:
                try:
                    old = getattr(self._wcf, "msg_socket", None)
                    if old is not None:
                        try:
                            old.close()
                        except Exception:
                            pass

                    sock = pynng.Pair1()
                    sock.send_timeout = 5000
                    sock.recv_timeout = 5000
                    sock.dial(self._wcf.msg_url, block=True)
                    self._wcf.msg_socket = sock
                    return True
                except BaseException as exc:
                    last_exc = exc
                    self._recv_last_error = str(exc)
                    time.sleep(_WCFERRY_MSG_DIAL_RETRY_INTERVAL_SEC)

            if last_exc is not None:
                self._recv_last_error = str(last_exc)
            return False

        def listening_msg():
            # First connect: bounded retries so init can fail fast and report a clear issue.
            deadline = time.time() + _WCFERRY_MSG_DIAL_TIMEOUT_SEC
            if not _connect_msg_socket(deadline):
                # Mark as not receiving so callers can retry via reconnect logic.
                self._wcf._is_receiving_msg = False
                return

            self._recv_ready.set()

            rsp_local = wcf_pb2.Response()
            while self._wcf._is_receiving_msg:
                try:
                    rsp_local.ParseFromString(self._wcf.msg_socket.recv_msg().bytes)
                    self._wcf.msgQ.put(WxMsg(rsp_local.wxmsg))
                except Exception as exc:
                    # On disconnects/transient errors, try reconnecting the message socket.
                    self._recv_last_error = str(exc)
                    time.sleep(0.15)
                    _connect_msg_socket(time.time() + 2.0)

        threading.Thread(target=listening_msg, name="GetMessageRobust", daemon=True).start()

        # Require msg channel ready; otherwise, receiving/replying will never work reliably.
        if not self._recv_ready.wait(timeout=_WCFERRY_MSG_DIAL_TIMEOUT_SEC):
            try:
                self._wcf.disable_recv_msg()
            except Exception:
                pass
            detail = self._recv_last_error or "dial timeout"
            raise TransportUnavailableError(
                f"wcferry message channel not ready (msg_url={getattr(self._wcf, 'msg_url', '')}): {detail}"
            )

    def _validate_version_gate(self) -> None:
        strict = bool(self.bot_cfg.get("silent_mode_required", True))
        if not self.wechat_version:
            return

        if self.configured_required_version and not _matches_version_rule(
            self.wechat_version,
            self.configured_required_version,
        ):
            self.transport_status.warning = (
                f"当前微信版本 {self.wechat_version} 不在配置要求范围 "
                f"{self.configured_required_version} 内"
            )
            if strict:
                raise TransportUnavailableError(self.transport_status.warning)

        detected_rule = ",".join(self.supported_wechat_versions)
        if detected_rule and not _matches_version_rule(self.wechat_version, detected_rule):
            self.transport_status.warning = (
                f"已安装 wcferry 仅支持微信 {detected_rule}，当前为 {self.wechat_version}"
            )
            raise TransportUnavailableError(self.transport_status.warning)

    def _refresh_contact_maps(self) -> None:
        self._by_wxid: Dict[str, Dict[str, Any]] = {}
        self._name_map: Dict[str, List[str]] = {}
        for contact in self._contacts:
            wxid = str(contact.get("wxid") or "").strip()
            if not wxid:
                continue
            self._by_wxid[wxid] = contact
            for field in ("remark", "name", "code", "wxid"):
                value = str(contact.get(field) or "").strip()
                if not value:
                    continue
                self._name_map.setdefault(value.lower(), []).append(wxid)

    def close(self) -> None:
        try:
            self._wcf._is_receiving_msg = False
        except Exception:
            pass
        _best_effort_wcf_call("disable_recv_msg", getattr(self._wcf, "disable_recv_msg", None))
        _best_effort_wcf_call("cleanup", getattr(self._wcf, "cleanup", None))
        if self._uses_local_wcf_sdk:
            _destroy_stale_local_wcf_session()
        relocate_known_root_artifacts()

    def get_transport_status(self) -> Dict[str, Any]:
        return {
            "transport_backend": self.transport_status.backend,
            "silent_mode": self.transport_status.silent_mode,
            "wechat_version": self.transport_status.wechat_version,
            "required_wechat_version": self.transport_status.required_version,
            "supports_native_quote": self.transport_status.supports_native_quote,
            "supports_voice_transcription": self.transport_status.supports_voice_transcription,
            "transport_status": self.transport_status.status,
            "transport_warning": self.transport_status.warning,
        }

    def _resolve_name(self, wxid: str) -> str:
        special_name = _SPECIAL_CONTACT_DISPLAY_NAMES.get(str(wxid or "").strip().lower())
        if special_name:
            return special_name
        contact = self._by_wxid.get(wxid) or {}
        return (
            str(contact.get("remark") or "").strip()
            or str(contact.get("name") or "").strip()
            or str(contact.get("code") or "").strip()
            or wxid
        )

    def _resolve_receiver(self, receiver: str, exact: bool = True) -> str:
        target = str(receiver or "").strip()
        if not target:
            raise ValueError("missing target")
        lowered = target.lower()
        for wxid, display_name in _SPECIAL_CONTACT_DISPLAY_NAMES.items():
            if lowered in {wxid, str(display_name).strip().lower()}:
                return wxid
        if target in self._by_wxid:
            return target

        # 允许直接传入 wxid / chatroom id（即使未出现在联系人列表中也尝试发送）。
        # 这能提高 hook_wcferry 在“群名未收录/联系人缓存未刷新”场景下的可用性。
        if lowered == "filehelper" or lowered.startswith("wxid_") or lowered.startswith("gh_") or lowered.endswith("@chatroom"):
            return target

        matched = self._name_map.get(target.lower(), [])
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1 and exact:
            raise ValueError(f"multiple contacts matched target: {target}")

        if not exact:
            lower = target.lower()
            fuzzy: List[str] = []
            for name, wxids in self._name_map.items():
                if lower in name:
                    fuzzy.extend(wxids)
            deduped = list(dict.fromkeys(fuzzy))
            if len(deduped) == 1:
                return deduped[0]
            if len(deduped) > 1:
                raise ValueError(f"multiple contacts matched target: {target}")

        raise ValueError(f"target not found: {target}")

    @staticmethod
    def _classify_message_type(msg: Any) -> str:
        mapping = {
            1: "text",
            3: "image",
            34: "voice",
            43: "video",
            47: "emoji",
            49: "file",
        }
        return mapping.get(int(getattr(msg, "type", 0) or 0), "text")

    def GetNextNewMessage(self, filter_mute: bool = False) -> Any:
        grouped: Dict[str, Dict[str, Any]] = {}
        while True:
            try:
                msg = self._wcf_call("get_msg", self._wcf.get_msg, block=False)
            except Empty:
                break
            except Exception as exc:
                logger.debug("wcferry get_msg failed: %s", exc)
                break

            chat_id = str(msg.roomid or msg.sender or "").strip()
            if not chat_id:
                continue
            chat_type = "group" if msg.from_group() else "friend"
            chat_name = self._resolve_name(chat_id)
            sender_name = self._resolve_name(str(msg.sender or "").strip())
            item = WcfMessageItem(
                self,
                msg,
                chat_id=chat_id,
                chat_name=chat_name,
                sender_name=sender_name,
                msg_type=self._classify_message_type(msg),
            )
            bucket = grouped.setdefault(
                chat_id,
                {"chat_name": chat_name, "chat_type": chat_type, "msg": []},
            )
            bucket["msg"].append(item)
        return list(grouped.values())

    def SendMsg(
        self,
        msg: str,
        who: Optional[str] = None,
        clear: bool = True,
        at: Optional[Any] = None,
        exact: bool = True,
    ) -> Dict[str, Any]:
        receiver = self._resolve_receiver(who or "", exact=exact)
        aters = ""
        if at:
            if isinstance(at, (list, tuple, set)):
                ids = [self._resolve_receiver(str(item), exact=True) for item in at]
                aters = ",".join(ids)
            else:
                aters = self._resolve_receiver(str(at), exact=True)
        status = self._wcf_call("send_text", self._wcf.send_text, str(msg or ""), receiver, aters=aters)
        return {
            "success": status == 0,
            "code": status,
            "message": "" if status == 0 else f"send_text failed: {status}",
            "receiver": receiver,
        }

    def SendFiles(self, filepath: str, who: Optional[str] = None, exact: bool = True) -> Dict[str, Any]:
        receiver = self._resolve_receiver(who or "", exact=exact)
        status = self._wcf_call("send_file", self._wcf.send_file, filepath, receiver)
        return {
            "success": status == 0,
            "code": status,
            "message": "" if status == 0 else f"send_file failed: {status}",
            "receiver": receiver,
        }

    def save_media(self, item: WcfMessageItem, target_path: str) -> str:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.type == "image":
            downloaded = self._wcf_call(
                "download_image",
                self._wcf.download_image,
                int(item.id),
                item.extra,
                str(target.parent),
            )
        elif item.type == "voice":
            downloaded = self._wcf_call(
                "get_audio_msg",
                self._wcf.get_audio_msg,
                int(item.id),
                str(target.parent),
                timeout=5,
            )
        else:
            status = self._wcf_call(
                "download_attach",
                self._wcf.download_attach,
                int(item.id),
                item.thumb,
                item.extra,
            )
            if status != 0:
                raise RuntimeError(f"download_attach failed: {status}")
            downloaded = item.extra

        if not downloaded or not os.path.exists(downloaded):
            raise RuntimeError("media download failed")
        downloaded_path = Path(downloaded)
        if downloaded_path.resolve() != target.resolve():
            if target.exists():
                target.unlink()
            shutil.move(str(downloaded_path), str(target))
        return str(target)

    def transcribe_voice(self, item: WcfMessageItem) -> Any:
        audio_dir = Path(os.getcwd()) / "temp_audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self._wcf_call(
            "get_audio_msg",
            self._wcf.get_audio_msg,
            int(item.id),
            str(audio_dir),
            timeout=5,
        )
        if not audio_path:
            return {"error": "voice download failed"}

        model = str(self.bot_cfg.get("voice_transcription_model") or "").strip()
        if not model:
            return {"error": "missing voice_transcription_model"}
        if not self.ai_client:
            return {"error": "ai runtime unavailable"}

        text, error = transcribe_audio_file(
            base_url=str(getattr(self.ai_client, "base_url", "") or ""),
            api_key=str(getattr(self.ai_client, "api_key", "") or ""),
            model=model,
            audio_path=audio_path,
            timeout_sec=float(self.bot_cfg.get("voice_transcription_timeout_sec", 30.0) or 30.0),
        )
        if error:
            return {"error": error}
        return text
