"""Audio transcription helpers for silent transport backends."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import httpx


def _normalize_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("missing base_url")
    return raw


def transcribe_audio_file(
    *,
    base_url: str,
    api_key: str,
    model: str,
    audio_path: str,
    timeout_sec: float = 30.0,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Call an OpenAI-compatible audio transcription endpoint."""
    if not os.path.exists(audio_path):
        return None, f"audio file not found: {audio_path}"

    endpoint = f"{_normalize_base_url(base_url)}/audio/transcriptions"
    headers: Dict[str, str] = {}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data: Dict[str, Any] = {"model": str(model or "").strip()}
    if not data["model"]:
        return None, "missing transcription model"
    if language:
        data["language"] = str(language).strip()
    if prompt:
        data["prompt"] = str(prompt)

    try:
        with open(audio_path, "rb") as fp:
            files = {
                "file": (
                    os.path.basename(audio_path),
                    fp,
                    "application/octet-stream",
                )
            }
            response = httpx.post(
                endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=max(float(timeout_sec or 30.0), 1.0),
            )
    except Exception as exc:
        return None, str(exc)

    if response.status_code >= 400:
        body = ""
        try:
            body = (response.text or "")[:300]
        except Exception:
            body = ""
        return None, body or f"http {response.status_code}"

    try:
        payload = response.json()
    except Exception:
        text = (response.text or "").strip()
        return (text or None), (None if text else "empty response")

    text = str(payload.get("text") or "").strip()
    if text:
        return text, None

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return None, message

    message = str(payload.get("message") or "").strip()
    return None, (message or "empty response")
