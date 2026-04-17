"""Protocol message dataclasses.

Defines the six wire-protocol message types for SPEC-MOUSE-001.
All messages are frozen dataclasses with a TYPE ClassVar identifying
the wire type field.

REQ-MOUSE-PROTOCOL-002: HELLO, MOUSE_MOVE, OWNERSHIP_REQUEST, OWNERSHIP_GRANT,
    SESSION_END, HEARTBEAT.
REQ-MOUSE-PROTOCOL-003: MouseMove fields dx/dy/abs_x/abs_y/ts.
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar, Literal, Union


@dataclasses.dataclass(frozen=True)
class Hello:
    """Initial handshake message.

    Sent by both nodes immediately after TCP connection is established.
    """

    TYPE: ClassVar[str] = "HELLO"

    version: str
    role: Literal["host", "remote"]


@dataclasses.dataclass(frozen=True)
class MouseMove:
    """Relative mouse movement message.

    REQ-MOUSE-PROTOCOL-003: dx, dy, optional abs_x/abs_y, ts (monotonic seconds).
    """

    TYPE: ClassVar[str] = "MOUSE_MOVE"

    dx: int
    dy: int
    ts: float
    abs_x: int | None = None
    abs_y: int | None = None


@dataclasses.dataclass(frozen=True)
class OwnershipRequest:
    """Request to transfer mouse ownership to the peer."""

    TYPE: ClassVar[str] = "OWNERSHIP_REQUEST"

    ts: float


@dataclasses.dataclass(frozen=True)
class OwnershipGrant:
    """Acknowledgement that the ownership request has been granted."""

    TYPE: ClassVar[str] = "OWNERSHIP_GRANT"

    ts: float


@dataclasses.dataclass(frozen=True)
class SessionEnd:
    """Session termination notification.

    Sent by either node to signal session tear-down.
    """

    TYPE: ClassVar[str] = "SESSION_END"

    reason: Literal["edge_return", "takeback", "transport_disconnect", "shutdown"]
    ts: float


@dataclasses.dataclass(frozen=True)
class Heartbeat:
    """Keepalive ping.

    REQ-MOUSE-PROTOCOL-005: exchanged after 1 second of inactivity.
    """

    TYPE: ClassVar[str] = "HEARTBEAT"

    ts: float


#: Union of all concrete message types (used as the return type of decode).
AnyMessage = Union[
    Hello,
    MouseMove,
    OwnershipRequest,
    OwnershipGrant,
    SessionEnd,
    Heartbeat,
]
