"""TCP transport implementation.

Implements the Transport Protocol over asyncio TCP streams with a 4-byte
big-endian unsigned length prefix framing protocol.

REQ-MOUSE-PROTOCOL-001: 4-byte BE length prefix + payload framing.
REQ-MOUSE-TRANSPORT-001: Transport ABC satisfied.
REQ-MOUSE-TRANSPORT-004: Unrecoverable I/O → surfaces ConnectionClosedError.
"""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

from eou.transport.base import (
    ConnectionClosedError,
    FrameTooLargeError,
    TransportTimeoutError,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum payload size accepted by this transport.
#: REQ-MOUSE-PROTOCOL-006: frames > 64 KiB must be rejected.
MAX_FRAME_SIZE: int = 64 * 1024  # 64 KiB

#: Number of bytes used for the length prefix (big-endian unsigned int).
# @MX:NOTE: [AUTO] 4-byte BE invariant — the length prefix is always exactly
#           4 bytes, encoding the payload byte count as a big-endian uint32.
#           Changing this constant is a breaking wire-protocol change.
LEN_PREFIX_BYTES: int = 4

#: Write timeout in seconds for send operations.
WRITE_TIMEOUT_SECS: float = 0.5  # 500 ms per REQ-MOUSE-TRANSPORT-004


# ---------------------------------------------------------------------------
# Private framing helpers (also tested directly for unit coverage)
# ---------------------------------------------------------------------------


def _encode_frame(payload: bytes) -> bytes:
    """Wrap *payload* in a 4-byte big-endian length prefix.

    Args:
        payload: Application-layer bytes to transmit. Must be 1..MAX_FRAME_SIZE bytes.

    Returns:
        ``len(payload).to_bytes(4, "big") + payload``

    Raises:
        ValueError: If *payload* is empty.
        FrameTooLargeError: If ``len(payload) > MAX_FRAME_SIZE``.

    # @MX:NOTE: [AUTO] 4-byte BE invariant — prefix encodes payload length only,
    #           exclusive of the 4-byte prefix itself (REQ-MOUSE-PROTOCOL-001).
    """
    if len(payload) == 0:
        raise ValueError("payload must not be empty (min 1 byte)")
    if len(payload) > MAX_FRAME_SIZE:
        raise FrameTooLargeError(
            f"frame size {len(payload)} exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE}"
        )
    return struct.pack(">I", len(payload)) + payload


async def _decode_frame(reader: asyncio.StreamReader) -> bytes:
    """Read exactly one frame from *reader*.

    Reads the 4-byte length prefix first, then reads exactly that many payload
    bytes.

    Args:
        reader: An asyncio.StreamReader positioned at the start of a frame.

    Returns:
        Payload bytes (framing stripped).

    Raises:
        ConnectionClosedError: On EOF before or during the frame (peer closed).
        FrameTooLargeError: If the declared length > MAX_FRAME_SIZE.

    # @MX:NOTE: [AUTO] 4-byte BE invariant — reads prefix first, validates
    #           against MAX_FRAME_SIZE before allocating payload buffer.
    """
    # Read 4-byte length prefix
    try:
        prefix = await reader.readexactly(LEN_PREFIX_BYTES)
    except asyncio.IncompleteReadError as exc:
        raise ConnectionClosedError(
            f"EOF while reading length prefix: got {len(exc.partial)} of {LEN_PREFIX_BYTES} bytes"
        ) from exc

    length: int = struct.unpack(">I", prefix)[0]

    # @MX:WARN: [AUTO] DoS prevention — validate declared length BEFORE allocating.
    # @MX:REASON: An attacker can declare length=MAX_INT to cause OOM. Reject here,
    #             before any read, to prevent allocation-based denial of service.
    if length > MAX_FRAME_SIZE:
        raise FrameTooLargeError(
            f"declared frame length {length} exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE}"
        )

    # Read payload
    try:
        payload = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ConnectionClosedError(
            f"EOF while reading payload: got {len(exc.partial)} of {length} bytes"
        ) from exc

    return payload


# ---------------------------------------------------------------------------
# TCPTransport
# ---------------------------------------------------------------------------


class TCPTransport:
    """Concrete TCP transport implementation.

    Wire format: 4-byte big-endian unsigned length prefix + raw payload.
    No encryption or authentication (MVP LAN-trust model).

    Usage::

        transport = TCPTransport()
        await transport.connect("127.0.0.1:9001")
        await transport.send(b"hello")
        data = await transport.recv()
        await transport.close()

    This class satisfies the Transport Protocol (checked at import time via
    isinstance checks in tests). It must NOT be imported by modules outside
    ``src/eou/transport/`` — upper layers receive it via DI only.
    """

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed: bool = True
        # Populated by listen() only. Python 3.12+ closes the StreamWriter
        # when asyncio.start_server's client callback returns, so the accept
        # handler must stay alive for the accepted connection's lifetime.
        # close() signals _server_release so the handler (and the server)
        # can be torn down cleanly.
        self._server: asyncio.Server | None = None
        self._server_release: asyncio.Event | None = None

    async def connect(self, endpoint: str) -> None:
        """Connect to *endpoint* (``"host:port"`` format).

        Used by the HOST role to dial the REMOTE peer.

        Args:
            endpoint: TCP address as ``"host:port"``, e.g. ``"127.0.0.1:9001"``.

        Raises:
            TransportError: On connection failure.
        """
        host, _, port_str = endpoint.rpartition(":")
        port = int(port_str)
        self._reader, self._writer = await asyncio.open_connection(host, port)
        self._closed = False

    async def listen(self, endpoint: str) -> None:
        """Bind to *endpoint* and accept exactly one incoming connection.

        Used by the REMOTE role to wait for the HOST's dial.  The listening
        socket is closed immediately after accepting the first peer
        (MVP: single-peer session).  Host portion ``0.0.0.0`` binds on all
        interfaces; a specific LAN IP restricts to that interface.

        Args:
            endpoint: TCP bind address as ``"host:port"``, e.g. ``"0.0.0.0:7001"``.

        Raises:
            TransportError: On bind failure.
        """
        host, _, port_str = endpoint.rpartition(":")
        port = int(port_str)

        loop = asyncio.get_running_loop()
        accepted: asyncio.Future[
            tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ] = loop.create_future()

        # Keep the accept-handler task alive until close() is called. Without
        # this, Python 3.12+ silently closes the StreamWriter as soon as the
        # handler returns, which tears down the freshly accepted connection
        # before the transport owner can use it (symptom: HOST's handshake
        # times out waiting for REMOTE's Hello reply).
        self._server_release = asyncio.Event()
        release = self._server_release

        async def _on_client(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            if not accepted.done():
                accepted.set_result((reader, writer))
                await release.wait()
            else:
                # Reject additional peers (MVP: single-peer)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass

        # host="" or "0.0.0.0" binds all interfaces on asyncio.start_server.
        bind_host: str | None = host if host not in ("", "0.0.0.0") else None
        server = await asyncio.start_server(_on_client, bind_host, port)
        self._server = server
        try:
            self._reader, self._writer = await accepted
        except BaseException:
            # Accept failed — release the handler and tear down the server.
            release.set()
            server.close()
            try:
                await server.wait_closed()
            except Exception:  # noqa: BLE001 — best-effort shutdown
                pass
            self._server = None
            self._server_release = None
            raise
        # Stop accepting new connections now that we have our peer. The
        # listening socket closes, but the already-accepted connection stays
        # open because _on_client is blocked on release.wait(). The full
        # server teardown (wait_closed) is deferred to close().
        server.close()
        self._closed = False

    async def send(self, frame: bytes) -> None:
        """Encode and transmit *frame* with a 4-byte length prefix.

        Args:
            frame: Application-layer payload bytes.

        Raises:
            ConnectionClosedError: If the transport is closed.
            FrameTooLargeError: If frame exceeds MAX_FRAME_SIZE.
            TransportTimeoutError: If write does not complete within 500 ms.
        """
        if self._closed or self._writer is None:
            raise ConnectionClosedError("transport is not connected")
        encoded = _encode_frame(frame)
        try:
            self._writer.write(encoded)
            await asyncio.wait_for(self._writer.drain(), timeout=WRITE_TIMEOUT_SECS)
        except asyncio.TimeoutError as exc:
            raise TransportTimeoutError("write timeout exceeded") from exc
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            await self.close()
            raise ConnectionClosedError(f"connection lost during send: {exc}") from exc

    async def recv(self) -> bytes:
        """Receive the next complete frame.

        Returns:
            Payload bytes with framing stripped.

        Raises:
            ConnectionClosedError: On EOF or disconnection.
            FrameTooLargeError: If declared frame length > MAX_FRAME_SIZE.
        """
        if self._closed or self._reader is None:
            raise ConnectionClosedError("transport is not connected")
        try:
            return await _decode_frame(self._reader)
        except (ConnectionResetError, OSError) as exc:
            await self.close()
            raise ConnectionClosedError(f"connection lost during recv: {exc}") from exc

    async def close(self) -> None:
        """Close the transport, releasing all resources.

        Idempotent: safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        # Release the accept-handler (listen-only) so it can exit and allow
        # the server to finish its shutdown below.
        if self._server_release is not None and not self._server_release.is_set():
            self._server_release.set()
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 — best-effort close
                pass
            self._writer = None
        self._reader = None
        if self._server is not None:
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001 — best-effort shutdown
                pass
            self._server = None
        self._server_release = None
