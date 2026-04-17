"""Transport package.

Public API: Transport, TransportError, ConnectionClosedError,
FrameTooLargeError, TransportTimeoutError.

Concrete implementations (TCPTransport) are NOT re-exported here to
enforce the layer boundary: callers must depend only on the abstractions
defined in base.py and receive concrete instances via dependency injection.
"""

from __future__ import annotations

from eou.transport.base import (
    ConnectionClosedError,
    FrameTooLargeError,
    Transport,
    TransportError,
    TransportTimeoutError,
)

__all__ = [
    "Transport",
    "TransportError",
    "ConnectionClosedError",
    "FrameTooLargeError",
    "TransportTimeoutError",
]
