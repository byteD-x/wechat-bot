from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict


class AuthSupportError(RuntimeError):
    """Raised when a requested auth-backed preset cannot be resolved."""


@dataclass(frozen=True)
class ResolvedAuthSettings:
    settings: Dict[str, Any]
    summary: Dict[str, Any]


ResolvedString = str | Callable[[], str]
ResolvedHeaders = Dict[str, str] | Callable[[], Dict[str, str]]
