from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from backend.shared_config import ensure_data_root


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    raw = bytes(value or b"")
    if not raw:
        raw = b"\0"
    buffer = ctypes.create_string_buffer(raw)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _dpapi_encrypt(value: bytes) -> str:
    if os.name != "nt":
        return base64.b64encode(value).decode("ascii")

    in_blob, in_buffer = _blob_from_bytes(value)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "wechat-chat-model-auth",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        del in_buffer


def _dpapi_decrypt(value: str) -> bytes:
    raw = base64.b64decode(str(value or "").encode("ascii"))
    if os.name != "nt":
        return raw

    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return decrypted
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        del in_buffer


@dataclass(frozen=True)
class CredentialRecord:
    ref: str
    provider_id: str
    method_type: str
    updated_at: int
    payload: Dict[str, Any]


@dataclass(frozen=True)
class CredentialLookupResult:
    ref: str
    exists: bool
    record: Optional[CredentialRecord] = None
    error: str = ""

    @property
    def readable(self) -> bool:
        return self.record is not None


class CredentialStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(path or (ensure_data_root() / "provider_credentials.json")).resolve()
        self._lock = threading.RLock()
        self._logged_lookup_failures: set[str] = set()

    def lookup(self, ref: str) -> CredentialLookupResult:
        wanted = str(ref or "").strip()
        if not wanted:
            return CredentialLookupResult(ref="", exists=False)
        with self._lock:
            data = self._read_store()
            item = data.get("credentials", {}).get(wanted)
            if not isinstance(item, dict):
                self._logged_lookup_failures.discard(wanted)
                return CredentialLookupResult(ref=wanted, exists=False)
            try:
                payload = self._decode_payload(item)
            except Exception as exc:
                self._log_lookup_failure(wanted, exc)
                return CredentialLookupResult(
                    ref=wanted,
                    exists=True,
                    record=None,
                    error=str(exc or "").strip() or exc.__class__.__name__,
                )
            self._logged_lookup_failures.discard(wanted)
            return CredentialLookupResult(
                ref=wanted,
                exists=True,
                record=CredentialRecord(
                    ref=wanted,
                    provider_id=str(item.get("provider_id") or "").strip(),
                    method_type=str(item.get("method_type") or "").strip(),
                    updated_at=int(item.get("updated_at") or 0),
                    payload=payload,
                ),
            )

    def get(self, ref: str) -> Optional[CredentialRecord]:
        return self.lookup(ref).record

    def set(self, ref: str, *, provider_id: str, method_type: str, payload: Dict[str, Any]) -> CredentialRecord:
        wanted = str(ref or "").strip()
        if not wanted:
            raise ValueError("credential ref is required")
        body = dict(payload or {})
        with self._lock:
            data = self._read_store()
            data.setdefault("credentials", {})
            data["credentials"][wanted] = {
                "provider_id": str(provider_id or "").strip(),
                "method_type": str(method_type or "").strip(),
                "updated_at": int(time.time()),
                "format": "dpapi" if os.name == "nt" else "base64",
                "payload": _dpapi_encrypt(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            }
            self._write_store(data)
        return self.get(wanted)  # type: ignore[return-value]

    def delete(self, ref: str) -> bool:
        wanted = str(ref or "").strip()
        if not wanted:
            return False
        with self._lock:
            data = self._read_store()
            removed = data.get("credentials", {}).pop(wanted, None)
            if removed is None:
                return False
            self._write_store(data)
            return True

    def has(self, ref: str) -> bool:
        return self.lookup(ref).record is not None

    def _decode_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        rendered = str(item.get("payload") or "").strip()
        if not rendered:
            return {}
        decrypted = _dpapi_decrypt(rendered)
        loaded = json.loads(decrypted.decode("utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def _read_store(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "credentials": {}}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "credentials": {}}
        if not isinstance(loaded, dict):
            return {"version": 1, "credentials": {}}
        loaded.setdefault("version", 1)
        loaded.setdefault("credentials", {})
        return loaded

    def _write_store(self, payload: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def _log_lookup_failure(self, ref: str, exc: Exception) -> None:
        if ref in self._logged_lookup_failures:
            return
        self._logged_lookup_failures.add(ref)
        logging.warning("读取认证凭据失败，已按缺失处理：%s（%s）", ref, exc)


_CREDENTIAL_STORE = CredentialStore()


def get_credential_store() -> CredentialStore:
    return _CREDENTIAL_STORE
