"""Tests for protocol message dataclasses.

REQ-MOUSE-PROTOCOL-002: message types HELLO, MOUSE_MOVE, OWNERSHIP_REQUEST,
    OWNERSHIP_GRANT, SESSION_END, HEARTBEAT.
REQ-MOUSE-PROTOCOL-003: MOUSE_MOVE fields dx:int, dy:int, abs_x?:int, abs_y?:int, ts:float.
"""

from __future__ import annotations

import dataclasses

import pytest


class TestHello:
    """Hello message dataclass contract."""

    def test_hello_exists(self) -> None:
        from eou.protocol.messages import Hello  # noqa: F401

    def test_hello_type_constant(self) -> None:
        from eou.protocol.messages import Hello

        assert Hello.TYPE == "HELLO"

    def test_hello_fields(self) -> None:
        from eou.protocol.messages import Hello

        msg = Hello(version="1.0", role="host")
        assert msg.version == "1.0"
        assert msg.role == "host"

    def test_hello_role_literal_remote(self) -> None:
        from eou.protocol.messages import Hello

        msg = Hello(version="1.0", role="remote")
        assert msg.role == "remote"

    def test_hello_is_frozen(self) -> None:
        from eou.protocol.messages import Hello

        msg = Hello(version="1.0", role="host")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.version = "2.0"  # type: ignore[misc]


class TestMouseMove:
    """MouseMove message dataclass contract.

    REQ-MOUSE-PROTOCOL-003: dx:int, dy:int, abs_x?:int, abs_y?:int, ts:float.
    """

    def test_mouse_move_exists(self) -> None:
        from eou.protocol.messages import MouseMove  # noqa: F401

    def test_mouse_move_type_constant(self) -> None:
        from eou.protocol.messages import MouseMove

        assert MouseMove.TYPE == "MOUSE_MOVE"

    def test_mouse_move_required_fields(self) -> None:
        from eou.protocol.messages import MouseMove

        msg = MouseMove(dx=10, dy=-5, ts=1234.5)
        assert msg.dx == 10
        assert msg.dy == -5
        assert msg.ts == 1234.5

    def test_mouse_move_optional_abs_defaults_none(self) -> None:
        """abs_x and abs_y must default to None (optional).

        REQ-MOUSE-PROTOCOL-003: optional abs_x, abs_y.
        """
        from eou.protocol.messages import MouseMove

        msg = MouseMove(dx=0, dy=0, ts=0.0)
        assert msg.abs_x is None
        assert msg.abs_y is None

    def test_mouse_move_with_abs_coords(self) -> None:
        from eou.protocol.messages import MouseMove

        msg = MouseMove(dx=1, dy=2, abs_x=800, abs_y=600, ts=0.0)
        assert msg.abs_x == 800
        assert msg.abs_y == 600

    def test_mouse_move_is_frozen(self) -> None:
        from eou.protocol.messages import MouseMove

        msg = MouseMove(dx=0, dy=0, ts=0.0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.dx = 1  # type: ignore[misc]


class TestOwnershipRequest:
    """OwnershipRequest message dataclass contract."""

    def test_ownership_request_exists(self) -> None:
        from eou.protocol.messages import OwnershipRequest  # noqa: F401

    def test_ownership_request_type_constant(self) -> None:
        from eou.protocol.messages import OwnershipRequest

        assert OwnershipRequest.TYPE == "OWNERSHIP_REQUEST"

    def test_ownership_request_has_ts(self) -> None:
        from eou.protocol.messages import OwnershipRequest

        msg = OwnershipRequest(ts=99.9)
        assert msg.ts == 99.9

    def test_ownership_request_is_frozen(self) -> None:
        from eou.protocol.messages import OwnershipRequest

        msg = OwnershipRequest(ts=0.0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.ts = 1.0  # type: ignore[misc]


class TestOwnershipGrant:
    """OwnershipGrant message dataclass contract."""

    def test_ownership_grant_exists(self) -> None:
        from eou.protocol.messages import OwnershipGrant  # noqa: F401

    def test_ownership_grant_type_constant(self) -> None:
        from eou.protocol.messages import OwnershipGrant

        assert OwnershipGrant.TYPE == "OWNERSHIP_GRANT"

    def test_ownership_grant_has_ts(self) -> None:
        from eou.protocol.messages import OwnershipGrant

        msg = OwnershipGrant(ts=1.0)
        assert msg.ts == 1.0


class TestSessionEnd:
    """SessionEnd message dataclass contract."""

    def test_session_end_exists(self) -> None:
        from eou.protocol.messages import SessionEnd  # noqa: F401

    def test_session_end_type_constant(self) -> None:
        from eou.protocol.messages import SessionEnd

        assert SessionEnd.TYPE == "SESSION_END"

    def test_session_end_valid_reasons(self) -> None:
        """reason must accept valid Literal values."""
        from eou.protocol.messages import SessionEnd

        for reason in ("edge_return", "takeback", "transport_disconnect", "shutdown"):
            msg = SessionEnd(reason=reason, ts=0.0)  # type: ignore[arg-type]
            assert msg.reason == reason

    def test_session_end_has_ts(self) -> None:
        from eou.protocol.messages import SessionEnd

        msg = SessionEnd(reason="shutdown", ts=42.0)
        assert msg.ts == 42.0

    def test_session_end_is_frozen(self) -> None:
        from eou.protocol.messages import SessionEnd

        msg = SessionEnd(reason="shutdown", ts=0.0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.reason = "takeback"  # type: ignore[misc]


class TestHeartbeat:
    """Heartbeat message dataclass contract."""

    def test_heartbeat_exists(self) -> None:
        from eou.protocol.messages import Heartbeat  # noqa: F401

    def test_heartbeat_type_constant(self) -> None:
        from eou.protocol.messages import Heartbeat

        assert Heartbeat.TYPE == "HEARTBEAT"

    def test_heartbeat_has_ts(self) -> None:
        from eou.protocol.messages import Heartbeat

        msg = Heartbeat(ts=0.0)
        assert msg.ts == 0.0
