"""Transport abstraction layer.

Defines the Transport Protocol (seam for BLE swap) and transport-level
exception hierarchy. All components outside transport/ depend ONLY on
these public names — never on tcp.py or ble.py directly.

REQ-MOUSE-TRANSPORT-001: Transport ABC with async connect/send/recv/close.
REQ-MOUSE-TRANSPORT-002: Upper layers depend only on this ABC, via DI.
REQ-MOUSE-TRANSPORT-005: BLE swap requires only changes in transport/.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# @MX:ANCHOR: [AUTO] Transport Protocol — primary seam for BLE swap (REQ-MOUSE-TRANSPORT-005).
# @MX:REASON: All upper-layer components (protocol/, ownership/, host, remote) depend
#             exclusively on this interface. Changing the signature here is a breaking
#             contract change that will cascade through the entire codebase.


@runtime_checkable
class Transport(Protocol):
    """Async transport abstraction.

    Concrete implementations (TCPTransport, future BLETransport) are
    injected via dependency injection. No module outside transport/ may
    import a concrete implementation directly.

    All methods are coroutines to support asyncio event-loop integration.
    """

    async def connect(self, endpoint: str) -> None:
        """Establish a connection to *endpoint*.

        Args:
            endpoint: Implementation-defined address string.
                      TCP uses ``"host:port"``; BLE uses a device identifier.
        """
        ...

    async def send(self, frame: bytes) -> None:
        """Send a complete application-layer *frame*.

        The transport is responsible for any wire framing (e.g. length
        prefix). The caller passes raw payload bytes.

        Args:
            frame: Payload bytes to transmit.

        Raises:
            TransportError: On any unrecoverable send failure.
            ConnectionClosedError: If the connection has been closed.
            FrameTooLargeError: If *frame* exceeds MAX_FRAME_SIZE.
        """
        ...

    async def recv(self) -> bytes:
        """Receive the next complete application-layer frame.

        Blocks until a full frame is available.

        Returns:
            Payload bytes (framing stripped).

        Raises:
            TransportError: On any unrecoverable receive failure.
            ConnectionClosedError: If the peer closed the connection.
        """
        ...

    async def close(self) -> None:
        """Close the transport, releasing all resources.

        Idempotent: calling close() on an already-closed transport must
        not raise.
        """
        ...


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TransportError(Exception):
    """Base class for all transport-layer errors."""


class ConnectionClosedError(TransportError):
    """Raised when an operation is attempted on a closed connection,
    or when the remote peer closes the connection unexpectedly."""


class FrameTooLargeError(TransportError):
    """Raised when a frame exceeds the configured MAX_FRAME_SIZE.

    # @MX:WARN: [AUTO] DoS prevention gate — frames above MAX_FRAME_SIZE are
    #           rejected before any allocation. Never raise after allocating
    #           the buffer; check the declared length prefix first.
    # @MX:REASON: An attacker can send a 16 MiB length prefix with a tiny
    #             payload to cause OOM. Reject early, before read.
    """


class TransportTimeoutError(TransportError):
    """Raised when a send or connect operation exceeds its timeout."""
