"""Protocol package.

Public API: message types (Hello, MouseMove, …), AnyMessage union,
codec functions (encode, decode), and error types.
"""

from __future__ import annotations

from eou.protocol.codec import (
    MalformedMessageError,
    ProtocolError,
    UnknownMessageTypeError,
    decode,
    encode,
)
from eou.protocol.messages import (
    AnyMessage,
    Heartbeat,
    Hello,
    MouseMove,
    OwnershipGrant,
    OwnershipRequest,
    SessionEnd,
)

__all__ = [
    # Messages
    "AnyMessage",
    "Hello",
    "MouseMove",
    "OwnershipRequest",
    "OwnershipGrant",
    "SessionEnd",
    "Heartbeat",
    # Codec
    "encode",
    "decode",
    # Errors
    "ProtocolError",
    "UnknownMessageTypeError",
    "MalformedMessageError",
]
