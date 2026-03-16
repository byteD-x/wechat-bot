"""Transport backends for WeChat connectivity.

Keep this package import lightweight: the wcferry hook backend brings in extra
dependencies and Windows-specific logic. Import it lazily when requested so
API/UI startup stays responsive.
"""

from __future__ import annotations

from .base import BaseTransport

__all__ = ["BaseTransport", "TransportUnavailableError", "WcferryWeChatClient"]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in {"TransportUnavailableError", "WcferryWeChatClient"}:
        from .wcferry_adapter import TransportUnavailableError, WcferryWeChatClient

        return TransportUnavailableError if name == "TransportUnavailableError" else WcferryWeChatClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
