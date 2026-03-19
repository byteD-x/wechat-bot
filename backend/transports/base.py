"""Common transport interface for WeChat backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseTransport(ABC):
    """Minimal transport contract consumed by the bot runtime."""

    backend_name = "transport"

    @abstractmethod
    def close(self) -> None:
        """Release transport resources."""

    @abstractmethod
    def get_transport_status(self) -> Dict[str, Any]:
        """Return runtime health and capability information."""

    @abstractmethod
    def poll_new_messages(self, filter_mute: bool = False) -> Any:
        """Poll transport messages using the shared runtime shape."""

    @abstractmethod
    def send_text(
        self,
        msg: str,
        who: Optional[str] = None,
        clear: bool = True,
        at: Optional[Any] = None,
        exact: bool = True,
    ) -> Dict[str, Any]:
        """Send a text message."""

    @abstractmethod
    def send_files(
        self,
        filepath: str,
        who: Optional[str] = None,
        exact: bool = True,
    ) -> Dict[str, Any]:
        """Send a file message."""
