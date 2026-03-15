"""wxauto-compatible silent backend powered by wcferry."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
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


class TransportUnavailableError(RuntimeError):
    """Raised when the requested transport cannot be initialized."""


@dataclass(slots=True)
class TransportStatus:
    backend: str
    silent_mode: bool
    wechat_version: str = ""
    required_version: str = ""
    compat_mode: bool = False
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
        self.configured_required_version = str(
            self.bot_cfg.get("required_wechat_version") or ""
        ).strip()
        self.supported_wechat_versions = detect_wcferry_supported_versions()
        self.required_version = self.configured_required_version or ",".join(
            self.supported_wechat_versions
        )
        self.wechat_path = detect_wechat_path()
        self.wechat_version = detect_wechat_version(self.wechat_path)
        self.compat_mode = False
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
            ensure_runtime_directories()
            with chdir_temporarily(WCFERRY_DIR):
                self._wcf = Wcf(debug=False)
            relocate_known_root_artifacts()
        except Exception as exc:
            raise TransportUnavailableError(str(exc)) from exc

        if not self._wcf.is_login():
            raise TransportUnavailableError("wechat not logged in")

        self.self_wxid = self._wcf.get_self_wxid()
        self.self_name = str(self.bot_cfg.get("self_name") or "").strip()
        self._contacts = self._wcf.get_contacts()
        self._refresh_contact_maps()
        if not self._wcf.enable_receiving_msg():
            raise TransportUnavailableError("failed to enable message receiving")

        self.transport_status.status = "connected"

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
            self._wcf.disable_recv_msg()
        except Exception:
            pass
        try:
            self._wcf.cleanup()
        except Exception:
            pass
        relocate_known_root_artifacts()

    def get_transport_status(self) -> Dict[str, Any]:
        return {
            "transport_backend": self.transport_status.backend,
            "silent_mode": self.transport_status.silent_mode,
            "wechat_version": self.transport_status.wechat_version,
            "required_wechat_version": self.transport_status.required_version,
            "compat_mode": self.transport_status.compat_mode,
            "supports_native_quote": self.transport_status.supports_native_quote,
            "supports_voice_transcription": self.transport_status.supports_voice_transcription,
            "transport_status": self.transport_status.status,
            "transport_warning": self.transport_status.warning,
        }

    def _resolve_name(self, wxid: str) -> str:
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
        if target in self._by_wxid:
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
                msg = self._wcf.get_msg(block=False)
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
        status = self._wcf.send_text(str(msg or ""), receiver, aters=aters)
        return {
            "success": status == 0,
            "code": status,
            "message": "" if status == 0 else f"send_text failed: {status}",
            "receiver": receiver,
        }

    def SendFiles(self, filepath: str, who: Optional[str] = None, exact: bool = True) -> Dict[str, Any]:
        receiver = self._resolve_receiver(who or "", exact=exact)
        status = self._wcf.send_file(filepath, receiver)
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
            downloaded = self._wcf.download_image(int(item.id), item.extra, str(target.parent))
        elif item.type == "voice":
            downloaded = self._wcf.get_audio_msg(int(item.id), str(target.parent), timeout=5)
        else:
            status = self._wcf.download_attach(int(item.id), item.thumb, item.extra)
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
        audio_path = self._wcf.get_audio_msg(int(item.id), str(audio_dir), timeout=5)
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
