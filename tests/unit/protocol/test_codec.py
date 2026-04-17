"""Tests for protocol codec (msgpack encode/decode).

REQ-MOUSE-PROTOCOL-002: All 6 message types round-trip through codec.
REQ-MOUSE-PROTOCOL-006: Unknown type / invalid msgpack / oversize → ProtocolError.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


class TestCodecExists:
    """Codec functions and error types must exist."""

    def test_encode_exists(self) -> None:
        from eou.protocol.codec import encode  # noqa: F401

    def test_decode_exists(self) -> None:
        from eou.protocol.codec import decode  # noqa: F401

    def test_protocol_error_is_exception(self) -> None:
        from eou.protocol.codec import ProtocolError

        assert issubclass(ProtocolError, Exception)

    def test_unknown_message_type_error(self) -> None:
        from eou.protocol.codec import ProtocolError, UnknownMessageTypeError

        assert issubclass(UnknownMessageTypeError, ProtocolError)

    def test_malformed_message_error(self) -> None:
        from eou.protocol.codec import MalformedMessageError, ProtocolError

        assert issubclass(MalformedMessageError, ProtocolError)


class TestEncodeDecodeRoundTrip:
    """All 6 message types must survive encode → decode round-trip."""

    def test_hello_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello

        original = Hello(version="1.0", role="host")
        assert decode(encode(original)) == original

    def test_mouse_move_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import MouseMove

        original = MouseMove(dx=5, dy=-3, abs_x=100, abs_y=200, ts=1.5)
        assert decode(encode(original)) == original

    def test_mouse_move_without_abs_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import MouseMove

        original = MouseMove(dx=0, dy=0, ts=0.0)
        assert decode(encode(original)) == original

    def test_ownership_request_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import OwnershipRequest

        original = OwnershipRequest(ts=0.5)
        assert decode(encode(original)) == original

    def test_ownership_grant_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import OwnershipGrant

        original = OwnershipGrant(ts=1.0)
        assert decode(encode(original)) == original

    def test_session_end_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import SessionEnd

        original = SessionEnd(reason="takeback", ts=2.0)
        assert decode(encode(original)) == original

    def test_heartbeat_round_trip(self) -> None:
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Heartbeat

        original = Heartbeat(ts=3.14)
        assert decode(encode(original)) == original


class TestCodecStructure:
    """Codec wire format must use {type: str, payload: {...}} structure."""

    def test_encoded_has_type_and_payload(self) -> None:
        """encode() produces msgpack bytes containing type and payload keys."""
        import msgpack

        from eou.protocol.codec import encode
        from eou.protocol.messages import Heartbeat

        data = msgpack.unpackb(encode(Heartbeat(ts=1.0)), raw=False)
        assert "type" in data
        assert "payload" in data
        assert data["type"] == "HEARTBEAT"

    def test_type_field_matches_message_type(self) -> None:
        import msgpack

        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello

        data = msgpack.unpackb(encode(Hello(version="1", role="host")), raw=False)
        assert data["type"] == "HELLO"


class TestDecodeErrors:
    """decode() must raise appropriate errors for bad input.

    REQ-MOUSE-PROTOCOL-006: unknown type / invalid msgpack → discard + log.
    """

    def test_unknown_type_raises(self) -> None:
        """Decoding a message with an unknown 'type' raises UnknownMessageTypeError."""
        import msgpack

        from eou.protocol.codec import UnknownMessageTypeError, decode

        data = msgpack.packb({"type": "UNKNOWN_TYPE", "payload": {}}, use_bin_type=True)
        with pytest.raises(UnknownMessageTypeError):
            decode(data)

    def test_corrupted_bytes_raises_malformed(self) -> None:
        """Corrupted msgpack bytes raise MalformedMessageError."""
        from eou.protocol.codec import MalformedMessageError, decode

        with pytest.raises(MalformedMessageError):
            decode(b"\xff\xfe\xfd garbage bytes")

    def test_missing_type_key_raises_malformed(self) -> None:
        """msgpack map without 'type' key raises MalformedMessageError."""
        import msgpack

        from eou.protocol.codec import MalformedMessageError, decode

        data = msgpack.packb({"payload": {}}, use_bin_type=True)
        with pytest.raises(MalformedMessageError):
            decode(data)

    def test_missing_payload_key_raises_malformed(self) -> None:
        """msgpack map without 'payload' key raises MalformedMessageError."""
        import msgpack

        from eou.protocol.codec import MalformedMessageError, decode

        data = msgpack.packb({"type": "HEARTBEAT"}, use_bin_type=True)
        with pytest.raises(MalformedMessageError):
            decode(data)

    def test_missing_required_field_raises_malformed(self) -> None:
        """Missing required field in payload raises MalformedMessageError."""
        import msgpack

        from eou.protocol.codec import MalformedMessageError, decode

        # MouseMove requires dx, dy, ts
        data = msgpack.packb(
            {"type": "MOUSE_MOVE", "payload": {"dx": 1}}, use_bin_type=True
        )
        with pytest.raises(MalformedMessageError):
            decode(data)

    def test_oversize_payload_raises_protocol_error(self) -> None:
        """Payload exceeding 64 KiB raises ProtocolError.

        REQ-MOUSE-PROTOCOL-006: frame > 64 KiB discarded.
        """
        import msgpack

        from eou.protocol.codec import ProtocolError, decode

        # Craft a raw msgpack blob > 64 KiB
        big_blob = msgpack.packb(
            {"type": "MOUSE_MOVE", "payload": {"garbage": b"x" * 70_000}},
            use_bin_type=True,
        )
        with pytest.raises(ProtocolError):
            decode(big_blob)


class TestHypothesisRoundTrip:
    """Property tests: encode(decode(encode(x))) == encode(x).

    REQ-MOUSE-PROTOCOL-002/003: round-trip stability over arbitrary valid inputs.
    Risk mitigation per strategy.md R-11: strategies bounded to SPEC-allowed ranges.
    """

    @given(
        dx=st.integers(min_value=-(2**31), max_value=2**31 - 1),
        dy=st.integers(min_value=-(2**31), max_value=2**31 - 1),
        ts=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_mouse_move_round_trip_property(self, dx: int, dy: int, ts: float) -> None:
        """MouseMove encode → decode → encode is stable."""
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import MouseMove

        msg = MouseMove(dx=dx, dy=dy, ts=ts)
        encoded = encode(msg)
        assert encode(decode(encoded)) == encoded

    @given(ts=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_heartbeat_round_trip_property(self, ts: float) -> None:
        """Heartbeat encode → decode → encode is stable."""
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Heartbeat

        msg = Heartbeat(ts=ts)
        assert encode(decode(encode(msg))) == encode(msg)
