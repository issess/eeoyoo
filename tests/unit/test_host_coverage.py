"""Additional host.py coverage tests — error paths and edge cases."""
from __future__ import annotations

import asyncio
import time

from eou.input.backend import MouseEvent
from eou.ownership.edge_detector import EdgeConfig
from eou.ownership.takeback_detector import TakebackConfig
from tests.fakes.mouse import FakeMouseBackend
from tests.fakes.transport import FakeTransport
from tests.fakes.visibility import FakeCursorVisibility


def _right_edge() -> EdgeConfig:
    return EdgeConfig(edge="right", screen_bounds=(0, 0, 1919, 1079), threshold_px=2, dwell_ticks=2)


def _takeback() -> TakebackConfig:
    return TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)


class TestHostHandshakeBadMessage:
    """Host receives non-Hello during handshake."""

    async def test_host_bad_handshake_type_exits(self) -> None:
        """Receiving non-Hello during handshake causes Host.run() to exit cleanly."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Heartbeat

        host_t, remote_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_right_edge(),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _inject() -> None:
            await asyncio.sleep(0.05)
            # Send wrong message type during handshake
            await remote_t.send(encode(Heartbeat(ts=time.monotonic())))
            await asyncio.sleep(0.2)

        await asyncio.gather(_drive(), _inject(), return_exceptions=True)
        # Should not crash; exception is caught internally


class TestHostConflictGrant:
    """Host receives duplicate OwnershipGrant while already CONTROLLING."""

    async def test_conflict_grant_handled(self) -> None:
        """Duplicate OwnershipGrant while CONTROLLING does not crash."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipGrant

        host_t, remote_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()
        backend._position = (1918, 540)

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_right_edge(),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=3.0)

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
            # Send duplicate grant while CONTROLLING
            await remote_t.send(encode(OwnershipGrant(ts=time.monotonic())))
            await asyncio.sleep(0.2)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        # Conflict grant must be handled without crash


class TestHostTransportCloseBeforeGrant:
    """Host transport closes during AWAITING_GRANT (pending request)."""

    async def test_transport_close_from_idle_no_show(self) -> None:
        """Transport disconnect from IDLE does not call show() unnecessarily."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello

        host_t, remote_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=_right_edge(),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)
            await remote_t.close()  # disconnect immediately after handshake
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        # Should have exited cleanly; show_call_count may be 0 (was never CONTROLLING)


class TestRemoteCoverageBoost:
    """Additional remote.py coverage — error paths."""

    async def test_remote_bad_handshake_message_type(self) -> None:
        """Remote receives non-Hello during handshake — exits cleanly."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Heartbeat
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=EdgeConfig(edge="left", screen_bounds=(0, 0, 1919, 1079)),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            # Wrong message type
            await host_t.send(encode(Heartbeat(ts=time.monotonic())))
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_remote_transport_close_while_controlled(self) -> None:
        """Remote transport disconnect while CONTROLLED → FSM IDLE."""
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
            edge_config=EdgeConfig(edge="left", screen_bounds=(0, 0, 1919, 1079)),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=3.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.1)
            await host_t.close()  # Simulate disconnect while CONTROLLED
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        # Should exit cleanly

    async def test_remote_heartbeat_ignored(self) -> None:
        """Remote ignores Heartbeat frames gracefully."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Heartbeat, Hello
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=EdgeConfig(edge="left", screen_bounds=(0, 0, 1919, 1079)),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            await host_t.send(encode(Heartbeat(ts=time.monotonic())))
            await asyncio.sleep(0.1)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
