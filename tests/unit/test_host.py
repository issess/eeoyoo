"""Unit tests for Host orchestration — T-034 RED phase.

REQ: SPEC-MOUSE-001 Slice 4 host.py; Acceptance Scenarios 1, 2 (HOST side), 7.

Tests use FakeTransport + FakeCursorVisibility + FakeMouseBackend.
No real network, no real OS cursor.

Scenarios covered:
    - Handshake: Host sends Hello(role="host") on run().
    - Edge dwell → OwnershipRequest sent.
    - OwnershipGrant received → FSM CONTROLLING + visibility.hide() called.
    - MOUSE_MOVE events forwarded while CONTROLLING.
    - SessionEnd(reason="edge_return") received → FSM IDLE + visibility.show().
    - SessionEnd(reason="takeback") received → FSM IDLE + visibility.show().
    - Transport disconnect → FSM IDLE + visibility.show().
"""
from __future__ import annotations

import asyncio
import time

from eou.input.backend import MouseEvent
from eou.ownership.edge_detector import EdgeConfig
from eou.ownership.takeback_detector import TakebackConfig
from tests.fakes.mouse import FakeMouseBackend
from tests.fakes.transport import FakeTransport
from tests.fakes.visibility import FakeCursorVisibility


def _make_fake_transport_pair() -> tuple[FakeTransport, FakeTransport]:
    return FakeTransport.make_pair()


def _edge_right(width: int = 1920, height: int = 1080) -> EdgeConfig:
    return EdgeConfig(
        edge="right",
        screen_bounds=(0, 0, width - 1, height - 1),
        threshold_px=2,
        dwell_ticks=2,
    )


def _takeback_config() -> TakebackConfig:
    return TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)


class TestHostHandshake:
    """Host sends HELLO on startup."""

    async def test_host_sends_hello_on_start(self) -> None:
        """Host sends Hello(role='host') during run() startup."""
        from eou.host import Host
        from eou.protocol.codec import decode
        from eou.protocol.messages import Hello

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        # Run briefly — host sends HELLO then waits for HELLO back.
        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=0.5)

        # Inject REMOTE HELLO so the handshake completes, then close.
        async def _inject() -> None:
            await asyncio.sleep(0.05)
            from eou.protocol.codec import encode

            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)
            await host_t.close()

        await asyncio.gather(_drive(), _inject(), return_exceptions=True)

        assert len(host_t.sent_frames) >= 1
        hello = decode(host_t.sent_frames[0])
        assert isinstance(hello, Hello)
        assert hello.role == "host"


class TestHostEdgeTransfer:
    """Edge dwell triggers OwnershipRequest → on Grant, hide() is called."""

    async def test_edge_dwell_sends_ownership_request(self) -> None:
        """Feeding 2 consecutive events at the right edge sends OwnershipRequest."""
        from eou.host import Host
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)  # near right edge

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=1.0)

        async def _scenario() -> None:
            # Complete handshake
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)

            # Feed edge events to trigger CROSS_OUT after dwell
            for _ in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=0, dy=0, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            # Wait for OwnershipRequest to be sent
            await asyncio.sleep(0.1)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        sent_messages = [decode(f) for f in host_t.sent_frames]
        msg_types = [type(m).__name__ for m in sent_messages]
        assert "OwnershipRequest" in msg_types

    async def test_ownership_grant_triggers_hide(self) -> None:
        """Receiving OwnershipGrant after REQUEST causes visibility.hide()."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipGrant

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=1.5)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)

            # Trigger edge dwell
            for _ in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=0, dy=0, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            # Send OwnershipGrant
            await asyncio.sleep(0.05)
            await remote_t.send(encode(OwnershipGrant(ts=time.monotonic())))
            await asyncio.sleep(0.1)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        assert visibility.hide_call_count >= 1

    async def test_mouse_move_sent_while_controlling(self) -> None:
        """While CONTROLLING, mouse movement events produce MOUSE_MOVE frames."""
        from eou.host import Host
        from eou.protocol.codec import decode, encode
        from eou.protocol.messages import Hello, MouseMove, OwnershipGrant

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)

            # Trigger edge dwell
            for _ in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=0, dy=0, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            await asyncio.sleep(0.05)
            await remote_t.send(encode(OwnershipGrant(ts=time.monotonic())))
            await asyncio.sleep(0.05)

            # Feed movement events while CONTROLLING
            for i in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=5, dy=3, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            await asyncio.sleep(0.1)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        sent_messages = [decode(f) for f in host_t.sent_frames]
        mouse_moves = [m for m in sent_messages if isinstance(m, MouseMove)]
        assert len(mouse_moves) >= 1


class TestHostSessionEnd:
    """SESSION_END received → FSM IDLE, visibility.show() called."""

    async def _run_until_session_end(
        self,
        reason: str,
    ) -> tuple[FakeCursorVisibility, int]:
        """Helper: drive Host through CONTROLLING then inject SESSION_END."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipGrant, SessionEnd

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)

            for _ in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=0, dy=0, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            await asyncio.sleep(0.05)
            await remote_t.send(encode(OwnershipGrant(ts=time.monotonic())))
            await asyncio.sleep(0.05)

            await remote_t.send(encode(SessionEnd(reason=reason, ts=time.monotonic())))  # type: ignore[arg-type]
            await asyncio.sleep(0.2)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        return visibility, visibility.show_call_count

    async def test_edge_return_session_end_calls_show(self) -> None:
        """SESSION_END(reason='edge_return') → visibility.show() called."""
        vis, show_count = await self._run_until_session_end("edge_return")
        assert show_count >= 1

    async def test_takeback_session_end_calls_show(self) -> None:
        """SESSION_END(reason='takeback') → visibility.show() called (Scenario 3)."""
        vis, show_count = await self._run_until_session_end("takeback")
        assert show_count >= 1


class TestHostTransportDisconnect:
    """Transport disconnect while CONTROLLING → FSM IDLE + show()."""

    async def test_transport_close_during_controlling_calls_show(self) -> None:
        """Transport disconnect → Host forces FSM to IDLE and calls show()."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipGrant

        host_t, remote_t = _make_fake_transport_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_edge_right(),
            takeback_config=_takeback_config(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)

            for _ in range(3):
                backend.feed_event(
                    MouseEvent(
                        dx=0, dy=0, abs_x=1918, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.02)

            await asyncio.sleep(0.05)
            await remote_t.send(encode(OwnershipGrant(ts=time.monotonic())))
            await asyncio.sleep(0.05)

            # Simulate transport disconnect
            await remote_t.close()
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

        assert visibility.show_call_count >= 1
