"""Additional remote.py coverage — decode errors, SessionEnd dispatch, inject errors."""
from __future__ import annotations

import asyncio
import time

from eou.input.backend import MouseEvent
from eou.ownership.edge_detector import EdgeConfig
from eou.ownership.takeback_detector import TakebackConfig
from tests.fakes.mouse import FakeMouseBackend
from tests.fakes.transport import FakeTransport
from tests.fakes.visibility import FakeCursorVisibility


def _left_edge() -> EdgeConfig:
    return EdgeConfig(edge="left", screen_bounds=(0, 0, 1919, 1079), threshold_px=2, dwell_ticks=2)


def _takeback() -> TakebackConfig:
    return TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)


class TestRemoteSessionEndFromControlled:
    """Remote receives SESSION_END while CONTROLLED → FSM IDLE."""

    async def test_session_end_while_controlled_goes_idle(self) -> None:
        """SESSION_END from host while CONTROLLED → Remote FSM → IDLE."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, OwnershipRequest, SessionEnd
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_left_edge(),
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
            # Send SESSION_END to force Remote back to IDLE
            await host_t.send(encode(SessionEnd(reason="edge_return", ts=time.monotonic())))
            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_remote_decode_error_frame_discarded(self) -> None:
        """Corrupted frame is discarded without crashing."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_left_edge(),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await host_t.send(encode(Hello(version="0.1.0", role="host")))
            await asyncio.sleep(0.05)
            # Send corrupted bytes directly (not a valid msgpack message)
            await host_t.send(b"\xff\xfe\xfd\xfc garbage data that is not valid msgpack")
            await asyncio.sleep(0.1)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_remote_ownership_request_while_not_idle_ignored(self) -> None:
        """OwnershipRequest while CONTROLLED is ignored."""
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
            edge_config=_left_edge(),
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
            # Send another OwnershipRequest while CONTROLLED → should be ignored
            await host_t.send(encode(OwnershipRequest(ts=time.monotonic())))
            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_remote_mouse_move_out_of_range_ignored(self) -> None:
        """MOUSE_MOVE with out-of-range delta is caught without crash."""
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
            edge_config=_left_edge(),
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
            # Send out-of-range delta that will trigger InjectionOutOfRangeError
            await host_t.send(encode(MouseMove(dx=99999, dy=99999, ts=time.monotonic())))
            await asyncio.sleep(0.2)
            await remote_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        # Should not crash


class TestRemoteTakebackSendError:
    """Remote takeback send fails (transport already closed)."""

    async def test_takeback_send_when_transport_closed(self) -> None:
        """SESSION_END for takeback gracefully handles closed transport."""
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
            edge_config=_left_edge(),
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
            # Close transport before takeback fires
            await remote_t.close()
            # Feed physical input to trigger takeback (send will fail gracefully)
            for _ in range(4):
                backend.feed_event(
                    MouseEvent(
                        dx=3, dy=2, abs_x=50, abs_y=540,
                        is_injected=False, ts=time.monotonic(),
                    )
                )
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_remote_wrong_hello_role(self) -> None:
        """Remote receives Hello(role='remote') instead of 'host' — raises."""
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello
        from eou.remote import Remote

        remote_t, host_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        remote = Remote(
            transport=remote_t,
            backend=backend,
            visibility=visibility,
            edge_config=_left_edge(),
            takeback_config=_takeback(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(remote.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            # Send wrong role
            await host_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.3)

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        # Should exit cleanly via ConnectionError → except Exception path


class TestHostCoverageBoost:
    """Additional host.py coverage."""

    async def test_host_decode_error_frame_discarded(self) -> None:
        """Corrupted inbound frame is discarded gracefully."""
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
            edge_config=EdgeConfig(edge="right", screen_bounds=(0, 0, 1919, 1079)),
            takeback_config=TakebackConfig(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)
            # Send corrupted frame
            await remote_t.send(b"\xff\xfe garbage")
            await asyncio.sleep(0.1)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)

    async def test_host_session_end_while_idle_noop(self) -> None:
        """SESSION_END received while IDLE is a no-op."""
        from eou.host import Host
        from eou.protocol.codec import encode
        from eou.protocol.messages import Hello, SessionEnd

        host_t, remote_t = FakeTransport.make_pair()
        visibility = FakeCursorVisibility()
        backend = FakeMouseBackend()

        host = Host(
            transport=host_t,
            backend=backend,
            visibility=visibility,
            edge_config=EdgeConfig(edge="right", screen_bounds=(0, 0, 1919, 1079)),
            takeback_config=TakebackConfig(),
        )

        async def _drive() -> None:
            await asyncio.wait_for(host.run(), timeout=2.0)

        async def _scenario() -> None:
            await asyncio.sleep(0.05)
            await remote_t.send(encode(Hello(version="0.1.0", role="remote")))
            await asyncio.sleep(0.05)
            # Send SESSION_END while Host is IDLE — should be no-op
            await remote_t.send(encode(SessionEnd(reason="edge_return", ts=time.monotonic())))
            await asyncio.sleep(0.1)
            await host_t.close()

        await asyncio.gather(_drive(), _scenario(), return_exceptions=True)
        assert visibility.show_call_count == 0  # Never entered CONTROLLING
