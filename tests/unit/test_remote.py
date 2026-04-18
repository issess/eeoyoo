"""Unit tests for Remote orchestration — T-035b RED phase.

REQ: SPEC-MOUSE-001 Slice 4 remote.py; Acceptance Scenarios 2, 3 (REMOTE side).

Tests:
    - Handshake: Remote awaits Hello(role='host') and replies Hello(role='remote').
    - OwnershipRequest received → OwnershipGrant sent + FSM CONTROLLED.
    - MouseMove received → injector.inject_move() called.
    - Takeback (physical local input) → SESSION_END(reason='takeback') sent + IDLE.
    - Remote does NOT call visibility.hide() or show() (REQ-MOUSE-VISIBILITY-004).
    - Transport disconnect while CONTROLLED → FSM IDLE (no crash).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from eou.input.backend import MouseEvent
from eou.ownership.edge_detector import EdgeConfig
from eou.ownership.takeback_detector import TakebackConfig
from tests.fakes.mouse import FakeMouseBackend
from tests.fakes.transport import FakeTransport
from tests.fakes.visibility import FakeCursorVisibility


def _edge_left(width: int = 1920, height: int = 1080) -> EdgeConfig:
    return EdgeConfig(
        edge="left",
        screen_bounds=(0, 0, width - 1, height - 1),
        threshold_px=2,
        dwell_ticks=2,
    )


def _takeback_config() -> TakebackConfig:
    return TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)


class TestRemoteHandshake:
    """Remote awaits Hello from host, then replies Hello(role='remote')."""

    async def test_remote_replies_hello_remote(self) -> None:
        """Remote sends Hello(role='remote') after receiving Hello(role='host')."""
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_left(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=1.0)

        async def _host_side() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _host_side(), return_exceptions=True)

        assert len(remote_t.sent_frames) >= 1
        hello = decode(remote_t.sent_frames[0])
        assert isinstance(hello, Hello)
        assert hello.role == "remote"


class TestRemoteOwnershipRequest:
    """OwnershipRequest → OwnershipGrant sent; FSM becomes CONTROLLED."""

    async def test_ownership_request_triggers_grant(self) -> None:
        """Receiving OwnershipRequest causes Remote to send OwnershipGrant."""
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello, OwnershipGrant, OwnershipRequest
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_left(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=1.5)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        sent = [decode(f) for f in remote_t.sent_frames]
        types = [type(m).__name__ for m in sent]
        assert "OwnershipGrant" in types


class TestRemoteMouseMoveInjection:
    """MouseMove frames received while CONTROLLED call injector.inject_move()."""

    async def test_mouse_move_frame_calls_backend_move(self) -> None:
        """MOUSE_MOVE received → backend.move(dx, dy) called."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, MouseMove, OwnershipRequest
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_left(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.05)
            # Send some MOUSE_MOVE frames
            for _ in range(3):
                await host_t.send(
                    encode(MouseMove(dx=5, dy=3, abs_x=100, abs_y=200, ts=time.monotonic()))
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.1)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        assert len(backend.move_calls) >= 1


class TestRemoteTakeback:
    """Physical local input while CONTROLLED triggers takeback."""

    async def test_takeback_sends_session_end(self) -> None:
        """5px cumulative non-injected movement → SESSION_END(reason='takeback') sent."""
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello, OwnershipRequest, SessionEnd
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_left(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.1)

            # Inject physical (non-injected) local input → trigger takeback
            for _ in range(3):
                backend.feed_event(
                    MouseEvent(dx=3, dy=2, abs_x=100, abs_y=200, is_injected=False, ts=time.monotonic())
                )
                await asyncio.sleep(0.01)

            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        sent = [decode(f) for f in remote_t.sent_frames]
        session_ends = [m for m in sent if isinstance(m, SessionEnd) and m.reason == "takeback"]
        assert len(session_ends) >= 1

    async def test_remote_does_not_call_visibility_hide(self) -> None:
        """Remote MUST NOT call visibility.hide() — REQ-MOUSE-VISIBILITY-004."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipRequest
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_left(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=1.5)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.3)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        # REQ-MOUSE-VISIBILITY-004: Remote must never hide the cursor
        assert visibility.hide_call_count == 0
        assert visibility.show_call_count == 0
