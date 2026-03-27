from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import subprocess
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict

from backend.utils.text_codec import coerce_text, decode_text_bytes, looks_like_utf16_text

logger = logging.getLogger(__name__)
_MAX_TEXT_CANDIDATE_BYTES = 1024 * 1024
_BINARY_DETECTION_SAMPLE_BYTES = 65536


def normalize_text(value: Any) -> str:
    return coerce_text(value).strip()


def _looks_like_binary_bytes(raw: bytes) -> bool:
    if not raw:
        return False
    if raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return False
    if looks_like_utf16_text(raw):
        return False
    sample = raw[:_BINARY_DETECTION_SAMPLE_BYTES]
    if b"\x00" in sample:
        return True
    suspicious = 0
    for byte in sample:
        if byte in (9, 10, 13):
            continue
        if 32 <= byte <= 126:
            continue
        if byte >= 128:
            continue
        suspicious += 1
    return (suspicious / max(len(sample), 1)) > 0.18


def safe_read_text_candidate(path: Path, *, log_label: str = "auth state text file") -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_TEXT_CANDIDATE_BYTES + 1)
    except Exception as exc:
        logger.warning("Failed to read %s %s: %s", log_label, path, exc)
        return ""
    if not raw or len(raw) > _MAX_TEXT_CANDIDATE_BYTES or _looks_like_binary_bytes(raw):
        return ""
    text = decode_text_bytes(raw)
    if not text:
        return ""
    replacement_ratio = text.count("\ufffd") / max(len(text), 1)
    if replacement_ratio > 0.02:
        return ""
    return text


def safe_read_json(path: Path) -> Dict[str, Any]:
    text = safe_read_text_candidate(path, log_label="auth state file")
    if not text:
        return {}
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "{[":
        return {}
    try:
        payload = json.loads(text)
    except Exception as exc:
        if path.suffix.lower() == ".json" or stripped[0] in "{[":
            logger.warning("Failed to read auth state file %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def safe_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    raw = normalize_text(token)
    if not raw:
        return {}
    parts = raw.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1].replace("-", "+").replace("_", "/")
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        value = json.loads(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def mask_email(email: str) -> str:
    value = normalize_text(email)
    if "@" not in value:
        return value
    local, _, domain = value.partition("@")
    if len(local) <= 2:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:2]}***"
    return f"{masked_local}@{domain}"


def launch_detached(command: list[str]) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=True,
    )


def open_browser_url(url: str) -> bool:
    target = normalize_text(url)
    if not target:
        return False
    try:
        return bool(webbrowser.open(target))
    except Exception as exc:
        logger.warning("Failed to open browser url %s: %s", target, exc)
        return False


def generate_flow_id(prefix: str) -> str:
    raw_prefix = normalize_text(prefix).lower() or "flow"
    return f"{raw_prefix}_{uuid.uuid4().hex}"


def generate_pkce_pair() -> dict[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return {
        "code_verifier": verifier,
        "code_challenge": challenge,
    }
