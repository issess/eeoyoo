"""Tests for TCP framing: 4-byte big-endian length prefix protocol.

REQ-MOUSE-PROTOCOL-001: 4-byte BE unsigned length prefix + msgpack payload.
REQ-MOUSE-TRANSPORT-004: EOF/peer-close surfaces as ConnectionClosedError.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stream_reader(data: bytes) -> asyncio.StreamReader:
    """Return a StreamReader pre-loaded with *data*."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    return reader


def _eof_reader(partial: bytes = b"") -> asyncio.StreamReader:
    """Return a StreamReader with *partial* bytes then EOF."""
    reader = asyncio.StreamReader()
    if partial:
        reader.feed_data(partial)
    reader.feed_eof()
    return reader


# ---------------------------------------------------------------------------
# _encode_frame / _decode_frame unit tests (private helpers, tested directly)
# ---------------------------------------------------------------------------


class TestEncodeFrame:
    """_encode_frame wraps payload in 4-byte BE length prefix."""

    def test_length_prefix_is_4_bytes_big_endian(self) -> None:
        """The first 4 bytes of the encoded frame encode payload length as BE uint32."""
        from eou.transport.tcp import _encode_frame

        payload = b"hello"
        encoded = _encode_frame(payload)
        prefix = encoded[:4]
        length = struct.unpack(">I", prefix)[0]
        assert length == len(payload)

    def test_payload_follows_prefix(self) -> None:
        """Bytes after the 4-byte prefix are the original payload."""
        from eou.transport.tcp import _encode_frame

        payload = b"world"
        encoded = _encode_frame(payload)
        assert encoded[4:] == payload

    def test_encode_single_byte(self) -> None:
        """Single-byte payload is framed correctly."""
        from eou.transport.tcp import _encode_frame

        encoded = _encode_frame(b"x")
        assert struct.unpack(">I", encoded[:4])[0] == 1
        assert encoded[4:] == b"x"

    def test_encode_1024_bytes(self) -> None:
        """1 KiB payload round-trips through encode."""
        from eou.transport.tcp import _encode_frame

        payload = b"x" * 1024
        encoded = _encode_frame(payload)
        assert struct.unpack(">I", encoded[:4])[0] == 1024
        assert encoded[4:] == payload

    def test_encode_max_allowed_size(self) -> None:
        """A frame at exactly MAX_FRAME_SIZE must encode without error."""
        from eou.transport.tcp import MAX_FRAME_SIZE, _encode_frame

        payload = b"x" * MAX_FRAME_SIZE
        encoded = _encode_frame(payload)
        assert struct.unpack(">I", encoded[:4])[0] == MAX_FRAME_SIZE

    def test_encode_oversize_raises_frame_too_large(self) -> None:
        """Frames exceeding MAX_FRAME_SIZE must raise FrameTooLargeError."""
        from eou.transport.base import FrameTooLargeError
        from eou.transport.tcp import MAX_FRAME_SIZE, _encode_frame

        with pytest.raises(FrameTooLargeError):
            _encode_frame(b"x" * (MAX_FRAME_SIZE + 1))

    def test_encode_empty_bytes_raises(self) -> None:
        """Empty payload must be rejected (min frame length is 1 byte)."""
        from eou.transport.tcp import _encode_frame

        with pytest.raises(ValueError):
            _encode_frame(b"")


class TestDecodeFrame:
    """_decode_frame reads exactly one frame from an asyncio.StreamReader."""

    @pytest.mark.asyncio
    async def test_round_trip_single_byte(self) -> None:
        """Encode then decode returns the original payload."""
        from eou.transport.tcp import _decode_frame, _encode_frame

        payload = b"x"
        reader = _make_stream_reader(_encode_frame(payload))
        assert await _decode_frame(reader) == payload

    @pytest.mark.asyncio
    async def test_round_trip_1024_bytes(self) -> None:
        """1 KiB payload survives encode → decode."""
        from eou.transport.tcp import _decode_frame, _encode_frame

        payload = b"x" * 1024
        reader = _make_stream_reader(_encode_frame(payload))
        assert await _decode_frame(reader) == payload

    @pytest.mark.asyncio
    async def test_round_trip_max_frame(self) -> None:
        """Payload at MAX_FRAME_SIZE survives encode → decode."""
        from eou.transport.tcp import MAX_FRAME_SIZE, _decode_frame, _encode_frame

        payload = b"y" * MAX_FRAME_SIZE
        reader = _make_stream_reader(_encode_frame(payload))
        assert await _decode_frame(reader) == payload

    @pytest.mark.asyncio
    async def test_split_delivery_two_halves_prefix(self) -> None:
        """Decoder handles the length prefix arriving in two separate chunks."""
        from eou.transport.tcp import _decode_frame, _encode_frame

        payload = b"split"
        encoded = _encode_frame(payload)

        # Feed 2 bytes of the 4-byte prefix, then the rest
        reader = asyncio.StreamReader()
        reader.feed_data(encoded[:2])
        reader.feed_data(encoded[2:])
        assert await _decode_frame(reader) == payload

    @pytest.mark.asyncio
    async def test_eof_during_length_prefix_raises_connection_closed(self) -> None:
        """EOF while reading the 4-byte prefix raises ConnectionClosedError.

        REQ-MOUSE-TRANSPORT-004: peer-close surfaces as ConnectionClosedError.
        """
        from eou.transport.base import ConnectionClosedError
        from eou.transport.tcp import _decode_frame

        reader = _eof_reader(partial=b"\x00\x00")  # only 2 of 4 prefix bytes
        with pytest.raises(ConnectionClosedError):
            await _decode_frame(reader)

    @pytest.mark.asyncio
    async def test_eof_during_payload_raises_connection_closed(self) -> None:
        """EOF while reading payload raises ConnectionClosedError.

        REQ-MOUSE-TRANSPORT-004: peer-close surfaces as ConnectionClosedError.
        """
        from eou.transport.base import ConnectionClosedError
        from eou.transport.tcp import _decode_frame

        # Declare length=10 but only provide 3 bytes of payload, then EOF
        prefix = struct.pack(">I", 10)
        reader = _eof_reader(partial=prefix + b"abc")
        with pytest.raises(ConnectionClosedError):
            await _decode_frame(reader)

    @pytest.mark.asyncio
    async def test_clean_eof_at_frame_boundary_raises_connection_closed(self) -> None:
        """EOF with zero buffered bytes raises ConnectionClosedError."""
        from eou.transport.base import ConnectionClosedError
        from eou.transport.tcp import _decode_frame

        reader = _eof_reader()
        with pytest.raises(ConnectionClosedError):
            await _decode_frame(reader)

    @pytest.mark.asyncio
    async def test_oversize_declared_length_raises_frame_too_large(self) -> None:
        """If the declared length exceeds MAX_FRAME_SIZE, raise FrameTooLargeError.

        REQ-MOUSE-PROTOCOL-006: frames > configured limit are discarded.
        """
        from eou.transport.base import FrameTooLargeError
        from eou.transport.tcp import MAX_FRAME_SIZE, _decode_frame

        oversized_prefix = struct.pack(">I", MAX_FRAME_SIZE + 1)
        reader = _make_stream_reader(oversized_prefix + b"x" * 10)
        with pytest.raises(FrameTooLargeError):
            await _decode_frame(reader)


class TestMaxFrameSize:
    """MAX_FRAME_SIZE constant semantics."""

    def test_max_frame_size_is_defined(self) -> None:
        """MAX_FRAME_SIZE must exist in tcp module."""
        from eou.transport.tcp import MAX_FRAME_SIZE  # noqa: F401

    def test_max_frame_size_value(self) -> None:
        """Default MAX_FRAME_SIZE must be 16 MiB per SPEC (64 KiB for PROTOCOL-006)."""
        from eou.transport.tcp import MAX_FRAME_SIZE

        # SPEC says 64 KiB per REQ-MOUSE-PROTOCOL-006; strategy says 16 MiB.
        # The implementation should use 64 KiB to satisfy the stricter PROTOCOL-006 gate.
        assert MAX_FRAME_SIZE == 64 * 1024

    def test_len_prefix_bytes_is_4(self) -> None:
        """LEN_PREFIX_BYTES constant must be 4."""
        from eou.transport.tcp import LEN_PREFIX_BYTES

        assert LEN_PREFIX_BYTES == 4
