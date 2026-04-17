"""Tests for Transport ABC contract.

REQ-MOUSE-TRANSPORT-001: Transport ABC with async connect/send/recv/close.
REQ-MOUSE-TRANSPORT-002: All components depend only on Transport ABC.
"""

from __future__ import annotations

import asyncio

import pytest


class TestTransportExists:
    """Transport class and error types must exist in eou.transport.base."""

    def test_transport_class_exists(self) -> None:
        """Transport class must be importable from eou.transport.base."""
        from eou.transport.base import Transport  # noqa: F401

    def test_transport_error_exists(self) -> None:
        """TransportError must be an Exception subclass."""
        from eou.transport.base import TransportError

        assert issubclass(TransportError, Exception)

    def test_connection_closed_error_exists(self) -> None:
        """ConnectionClosedError must be a TransportError subclass."""
        from eou.transport.base import ConnectionClosedError, TransportError

        assert issubclass(ConnectionClosedError, TransportError)

    def test_frame_too_large_error_exists(self) -> None:
        """FrameTooLargeError must be a TransportError subclass."""
        from eou.transport.base import FrameTooLargeError, TransportError

        assert issubclass(FrameTooLargeError, TransportError)


class TestTransportInterface:
    """Transport Protocol must define the correct async interface."""

    def test_connect_is_coroutine(self) -> None:
        """connect(endpoint: str) -> None must be a coroutine function."""
        from eou.transport.base import Transport

        assert asyncio.iscoroutinefunction(Transport.connect)

    def test_send_is_coroutine(self) -> None:
        """send(frame: bytes) -> None must be a coroutine function."""
        from eou.transport.base import Transport

        assert asyncio.iscoroutinefunction(Transport.send)

    def test_recv_is_coroutine(self) -> None:
        """recv() -> bytes must be a coroutine function."""
        from eou.transport.base import Transport

        assert asyncio.iscoroutinefunction(Transport.recv)

    def test_close_is_coroutine(self) -> None:
        """close() -> None must be a coroutine function."""
        from eou.transport.base import Transport

        assert asyncio.iscoroutinefunction(Transport.close)


class TestConcreteTransportContract:
    """A minimal concrete Transport must satisfy the idempotency contract."""

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """Calling close() twice must not raise.

        REQ-MOUSE-TRANSPORT-001: close() is idempotent.
        """

        class _MinimalTransport:
            """Minimal concrete transport for contract verification."""

            _closed = False

            async def connect(self, endpoint: str) -> None:
                self._closed = False

            async def send(self, frame: bytes) -> None:
                pass

            async def recv(self) -> bytes:
                return b""

            async def close(self) -> None:
                self._closed = True

        t = _MinimalTransport()
        await t.close()
        await t.close()  # second call must not raise

    @pytest.mark.asyncio
    async def test_transport_error_is_raiseable(self) -> None:
        """TransportError can be raised and caught as Exception."""
        from eou.transport.base import TransportError

        with pytest.raises(Exception):
            raise TransportError("test error")

    @pytest.mark.asyncio
    async def test_connection_closed_error_is_transport_error(self) -> None:
        """ConnectionClosedError must be catchable as TransportError."""
        from eou.transport.base import ConnectionClosedError, TransportError

        with pytest.raises(TransportError):
            raise ConnectionClosedError("connection closed")
