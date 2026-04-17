from __future__ import annotations

import asyncio


class FakeTransport:
    """In-memory duplex transport for testing.

    Provides a pair of connected FakeTransport instances that exchange
    bytes via asyncio.Queue, avoiding real network I/O.
    """

    def __init__(self) -> None:
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._peer: FakeTransport | None = None
        self._closed = False
        self._sent_frames: list[bytes] = []

    @classmethod
    def make_pair(cls) -> tuple[FakeTransport, FakeTransport]:
        """Create a connected pair (client, server)."""
        a, b = cls(), cls()
        a._peer = b
        b._peer = a
        return a, b

    async def connect(self, endpoint: str) -> None:
        self._closed = False

    async def send(self, frame: bytes) -> None:
        if self._closed:
            from eou.transport.base import ConnectionClosedError

            raise ConnectionClosedError("transport is closed")
        self._sent_frames.append(frame)
        if self._peer is not None:
            await self._peer._send_queue.put(frame)

    async def recv(self) -> bytes:
        if self._closed:
            from eou.transport.base import ConnectionClosedError

            raise ConnectionClosedError("transport is closed")
        return await self._send_queue.get()

    async def close(self) -> None:
        self._closed = True

    @property
    def sent_frames(self) -> list[bytes]:
        return list(self._sent_frames)
