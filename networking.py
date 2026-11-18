"""Process-local networking safeguards for unreliable Windows IPv6 routes."""

from __future__ import annotations

import socket
import threading
from typing import Any


_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def ipv4_first_addresses(results: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Keep every DNS result but put IPv4 candidates before IPv6."""

    return sorted(
        results,
        key=lambda item: 0 if item and item[0] == socket.AF_INET else 1,
    )


def install_ipv4_first_dns() -> bool:
    """Install an idempotent process-local IPv4-first DNS preference."""

    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return False

        def getaddrinfo(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
            return ipv4_first_addresses(_ORIGINAL_GETADDRINFO(*args, **kwargs))

        socket.getaddrinfo = getaddrinfo
        _INSTALLED = True
        return True


__all__ = ["install_ipv4_first_dns", "ipv4_first_addresses"]
