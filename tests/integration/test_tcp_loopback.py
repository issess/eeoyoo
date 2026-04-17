"""TCP loopback integration tests.

Tests TCPTransport and codec together over a real localhost TCP connection.
Each test spins up asyncio.start_server(port=0) and connects via
asyncio.open_connection to get an ephemeral port (avoids port conflicts).

REQ-MOUSE-TRANSPORT-001: Transport ABC satisfied.
REQ-MOUSE-TRANSPORT-002: Upper layers depend only on Transport ABC.
REQ-MOUSE-PROTOCOL-001..004: 6 message types round-trip via TCP.
"""

from __future__ import annotations

import asyncio

import pytest

from eou.protocol.codec import decode, encode
from eou.protocol.messages import (
    Heartbeat,
    Hello,
    MouseMove,
    OwnershipGrant,
    OwnershipRequest,
    SessionEnd,
)
from eou.transport.base import ConnectionClosedError
from eou.transport.tcp import TCPTransport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def loopback_pair() -> tuple[TCPTransport, TCPTransport]:
    """Yield a connected (server_transport, client_transport) pair.

    Server binds to 127.0.0.1:0 (ephemeral port). Both transports are
    closed in teardown regardless of test outcome.

    Strategy doc R-10: loop_scope="function" to avoid event-loop reuse issues.
    """
    server_transport: TCPTransport | None = None
    server: asyncio.Server | None = None
    client_transport = TCPTransport()

    connected_event = asyncio.Event()
    server_conn: list[TCPTransport] = []

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        t = TCPTransport()
        t._reader = reader
        t._writer = writer
        t._closed = False
        server_conn.append(t)
        connected_event.set()
        # Hold connection open until client disconnects
        try:
            while True:
                await asyncio.sleep(0.05)
        except Exception:
            pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    addr = server.sockets[0].getsockname()  # type: ignore[index]
    port: int = addr[1]

    await client_transport.connect(f"127.0.0.1:{port}")
    await asyncio.wait_for(connected_event.wait(), timeout=2.0)

    server_transport = server_conn[0]

    try:
        yield server_transport, client_transport
    finally:
        await client_transport.close()
        await server_transport.close()
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Helper: bidirectional round-trip
# ---------------------------------------------------------------------------


async def _round_trip(
    sender: TCPTransport,
    receiver: TCPTransport,
    msg: object,
) -> object:
    """Encode *msg*, send through *sender*, receive and decode from *receiver*."""
    await sender.send(encode(msg))  # type: ignore[arg-type]
    raw = await receiver.recv()
    return decode(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMessageRoundTrips:
    """Each of the 6 message types must survive a TCP send/receive cycle."""

    @pytest.mark.asyncio
    async def test_hello_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """Hello message round-trips client → server."""
        client, server = loopback_pair
        original = Hello(version="1.0", role="host")
        result = await _round_trip(client, server, original)
        assert result == original

    @pytest.mark.asyncio
    async def test_mouse_move_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """MouseMove round-trips with all fields."""
        client, server = loopback_pair
        original = MouseMove(dx=10, dy=-5, abs_x=800, abs_y=600, ts=1.5)
        result = await _round_trip(client, server, original)
        assert result == original

    @pytest.mark.asyncio
    async def test_mouse_move_without_abs(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """MouseMove round-trips with optional abs fields omitted."""
        client, server = loopback_pair
        original = MouseMove(dx=1, dy=2, ts=0.0)
        result = await _round_trip(client, server, original)
        assert result == original

    @pytest.mark.asyncio
    async def test_ownership_request_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """OwnershipRequest round-trips server → client (symmetric)."""
        client, server = loopback_pair
        original = OwnershipRequest(ts=0.1)
        result = await _round_trip(server, client, original)
        assert result == original

    @pytest.mark.asyncio
    async def test_ownership_grant_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """OwnershipGrant round-trips."""
        client, server = loopback_pair
        original = OwnershipGrant(ts=0.2)
        result = await _round_trip(server, client, original)
        assert result == original

    @pytest.mark.asyncio
    async def test_session_end_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """SessionEnd round-trips with all reason values."""
        client, server = loopback_pair
        for reason in ("edge_return", "takeback", "transport_disconnect", "shutdown"):
            original = SessionEnd(reason=reason, ts=0.0)  # type: ignore[arg-type]
            result = await _round_trip(client, server, original)
            assert result == original

    @pytest.mark.asyncio
    async def test_heartbeat_round_trip(
        self, loopback_pair: tuple[TCPTransport, TCPTransport]
    ) -> None:
        """Heartbeat round-trips."""
        client, server = loopback_pair
        original = Heartbeat(ts=3.14)
        result = await _round_trip(client, server, original)
        assert result == original


class TestDisconnectBehaviour:
    """Server close mid-session must surface as ConnectionClosedError on client."""

    @pytest.mark.asyncio
    async def test_server_close_raises_connection_closed_on_client_recv(self) -> None:
        """After server closes, client recv() raises ConnectionClosedError.

        REQ-MOUSE-TRANSPORT-004: unrecoverable I/O → ConnectionClosedError.
        """
        server_transport: TCPTransport | None = None
        server: asyncio.Server | None = None
        client_transport = TCPTransport()

        connected_event = asyncio.Event()
        server_conn: list[TCPTransport] = []

        async def handle_client(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            t = TCPTransport()
            t._reader = reader
            t._writer = writer
            t._closed = False
            server_conn.append(t)
            connected_event.set()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        addr = server.sockets[0].getsockname()  # type: ignore[index]

        try:
            await client_transport.connect(f"127.0.0.1:{addr[1]}")
            await asyncio.wait_for(connected_event.wait(), timeout=2.0)
            server_transport = server_conn[0]

            # Server closes first
            await server_transport.close()
            await asyncio.sleep(0.05)  # allow TCP teardown to propagate

            with pytest.raises(ConnectionClosedError):
                await client_transport.recv()
        finally:
            await client_transport.close()
            if server_transport:
                await server_transport.close()
            server.close()
            await server.wait_closed()
