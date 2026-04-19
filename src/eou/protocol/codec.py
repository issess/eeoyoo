"""Protocol codec: msgpack encode/decode for all message types.

The codec operates on complete message payloads. Framing (4-byte BE length
prefix) is the transport layer's responsibility (see transport/tcp.py).

Architecture decision: codec never imports from transport/ to maintain
clean layer separation. Upper layers (host.py, remote.py) call
  transport.send(codec.encode(msg))   and
  msg = codec.decode(await transport.recv())

REQ-MOUSE-PROTOCOL-002: all 6 message types supported.
REQ-MOUSE-PROTOCOL-006: unknown type / invalid msgpack / oversize → ProtocolError.

# @MX:ANCHOR: [AUTO] encode — single entry point for all outbound wire serialization.
# @MX:REASON: Every MOUSE_MOVE, HEARTBEAT, and control message passes through encode()
#             before hitting the wire. Changing the wire format here is a breaking
#             protocol change affecting both HOST and REMOTE simultaneously.
#
# @MX:ANCHOR: [AUTO] decode — single entry point for all inbound wire deserialization.
# @MX:REASON: All received frames from TCPTransport pass through decode(). Routing
#             logic in host.py/remote.py dispatches on the returned AnyMessage type.
"""

from __future__ import annotations

from typing import Any

import msgpack

from eou.protocol.messages import (
    AnyMessage,
    Heartbeat,
    Hello,
    MouseClick,
    MouseMove,
    MouseScroll,
    OwnershipGrant,
    OwnershipRequest,
    SessionEnd,
)

# ---------------------------------------------------------------------------
# Payload size gate (REQ-MOUSE-PROTOCOL-006)
# ---------------------------------------------------------------------------

#: Maximum accepted decoded payload size in bytes.
#: Matches transport-layer MAX_FRAME_SIZE (64 KiB).
MAX_PAYLOAD_BYTES: int = 64 * 1024


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ProtocolError(Exception):
    """Base class for codec-level errors.

    Raised when a message cannot be encoded or decoded without corrupting
    ownership state.
    """


class UnknownMessageTypeError(ProtocolError):
    """Raised when the 'type' field refers to an unknown message type.

    REQ-MOUSE-PROTOCOL-006: unknown types must be discarded without FSM mutation.
    """


class MalformedMessageError(ProtocolError):
    """Raised when the msgpack bytes are structurally invalid or missing required
    fields.

    REQ-MOUSE-PROTOCOL-006: invalid msgpack must be discarded.
    """


# ---------------------------------------------------------------------------
# Message type registry
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type] = {
    "HELLO": Hello,
    "MOUSE_MOVE": MouseMove,
    "MOUSE_CLICK": MouseClick,
    "MOUSE_SCROLL": MouseScroll,
    "OWNERSHIP_REQUEST": OwnershipRequest,
    "OWNERSHIP_GRANT": OwnershipGrant,
    "SESSION_END": SessionEnd,
    "HEARTBEAT": Heartbeat,
}

# Required fields per message type (used for validation in decode)
_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "HELLO": frozenset({"version", "role"}),
    "MOUSE_MOVE": frozenset({"dx", "dy", "ts"}),
    "MOUSE_CLICK": frozenset({"button", "pressed", "ts"}),
    "MOUSE_SCROLL": frozenset({"dx", "dy", "ts"}),
    "OWNERSHIP_REQUEST": frozenset({"ts"}),
    "OWNERSHIP_GRANT": frozenset({"ts"}),
    "SESSION_END": frozenset({"reason", "ts"}),
    "HEARTBEAT": frozenset({"ts"}),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode(msg: AnyMessage) -> bytes:
    """Serialize *msg* to msgpack bytes.

    Wire format: ``{"type": str, "payload": {...}}``

    Args:
        msg: Any concrete message instance.

    Returns:
        Raw msgpack bytes (no length prefix — transport adds that).

    Raises:
        ProtocolError: If serialization fails unexpectedly.

    # @MX:ANCHOR: [AUTO] encode — all outbound message serialization.
    # @MX:REASON: See module docstring.
    """
    payload = {k: v for k, v in vars(msg).items()}
    wire = {"type": msg.TYPE, "payload": payload}
    try:
        return msgpack.packb(wire, use_bin_type=True)
    except Exception as exc:
        raise ProtocolError(f"failed to encode {msg.TYPE}: {exc}") from exc


def decode(data: bytes) -> AnyMessage:
    """Deserialize msgpack bytes into the appropriate message dataclass.

    Args:
        data: Raw msgpack bytes as received from the transport layer.

    Returns:
        A concrete message instance (Hello, MouseMove, etc.).

    Raises:
        ProtocolError: If *data* exceeds MAX_PAYLOAD_BYTES.
        MalformedMessageError: If *data* is not valid msgpack, or is missing
            the required 'type' / 'payload' keys, or payload is missing
            required fields.
        UnknownMessageTypeError: If the 'type' value is not a registered type.

    # @MX:ANCHOR: [AUTO] decode — all inbound message deserialization.
    # @MX:REASON: See module docstring.
    """
    # Size gate (REQ-MOUSE-PROTOCOL-006)
    if len(data) > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            f"payload size {len(data)} exceeds MAX_PAYLOAD_BYTES {MAX_PAYLOAD_BYTES}"
        )

    # Deserialize
    try:
        wire: Any = msgpack.unpackb(data, raw=False, strict_map_key=False)
    except Exception as exc:
        raise MalformedMessageError(f"msgpack deserialization failed: {exc}") from exc

    # Structure validation
    if not isinstance(wire, dict):
        raise MalformedMessageError(f"expected msgpack map, got {type(wire).__name__}")
    if "type" not in wire:
        raise MalformedMessageError("missing required 'type' key")
    if "payload" not in wire:
        raise MalformedMessageError("missing required 'payload' key")

    msg_type: str = wire["type"]
    payload: Any = wire["payload"]

    # Type dispatch
    cls = _TYPE_MAP.get(msg_type)
    if cls is None:
        raise UnknownMessageTypeError(f"unknown message type: {msg_type!r}")

    if not isinstance(payload, dict):
        raise MalformedMessageError(
            f"payload for {msg_type} must be a dict, got {type(payload).__name__}"
        )

    # Required field check
    required = _REQUIRED_FIELDS.get(msg_type, frozenset())
    missing = required - payload.keys()
    if missing:
        raise MalformedMessageError(
            f"{msg_type} payload missing required fields: {sorted(missing)}"
        )

    # Construct dataclass (only pass known fields to avoid TypeError on extras)
    import dataclasses

    known = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in payload.items() if k in known}
    try:
        return cls(**filtered)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        raise MalformedMessageError(
            f"failed to construct {msg_type} from payload: {exc}"
        ) from exc
