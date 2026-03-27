from __future__ import annotations

import os
from typing import Any

_UTF16_BOMS = (
    b"\xff\xfe",
    b"\xfe\xff",
)
_UTF32_BOMS = (
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
)


def looks_like_utf16_text(raw: bytes) -> bool:
    if not raw:
        return False
    if raw.startswith(_UTF16_BOMS) or raw.startswith(_UTF32_BOMS):
        return True
    sample = raw[: min(len(raw), 4096)]
    if len(sample) < 4:
        return False
    even_positions = sample[::2]
    odd_positions = sample[1::2]
    if not even_positions or not odd_positions:
        return False
    even_zero_ratio = even_positions.count(0) / len(even_positions)
    odd_zero_ratio = odd_positions.count(0) / len(odd_positions)
    return max(even_zero_ratio, odd_zero_ratio) >= 0.3 and min(even_zero_ratio, odd_zero_ratio) <= 0.05


def _candidate_encodings(raw: bytes) -> tuple[str, ...]:
    encodings = ["utf-8-sig", "utf-8"]
    if raw.startswith(_UTF32_BOMS):
        encodings.insert(0, "utf-32")
    elif raw.startswith(_UTF16_BOMS):
        encodings.insert(0, "utf-16")
    elif looks_like_utf16_text(raw):
        encodings.extend(["utf-16-le", "utf-16-be"])

    encodings.append("gb18030")
    if os.name == "nt":
        encodings.extend(["cp936", "mbcs"])
    return tuple(dict.fromkeys(encodings))


def decode_text_bytes(value: bytes | bytearray | memoryview | None) -> str:
    raw = bytes(value or b"")
    if not raw:
        return ""

    for encoding in _candidate_encodings(raw):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    best_text = ""
    best_score = (10**9, 10**9)
    for encoding in _candidate_encodings(raw):
        try:
            decoded = raw.decode(encoding, errors="replace")
        except LookupError:
            continue
        score = (
            decoded.count("\ufffd"),
            decoded.count("\x00"),
        )
        if score < best_score:
            best_text = decoded
            best_score = score
            if score == (0, 0):
                break
    return best_text


def coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return decode_text_bytes(value)
    return str(value or "")


__all__ = [
    "coerce_text",
    "decode_text_bytes",
    "looks_like_utf16_text",
]
