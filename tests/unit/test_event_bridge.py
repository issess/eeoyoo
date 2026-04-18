"""Unit tests for MouseEventBridge — T-032 RED phase.

REQ: SPEC-MOUSE-001 strategy.md §2 asyncio ↔ thread bridge, plan.md R-09.

Tests:
    - submit() is callable from a non-asyncio thread and delivers to receive().
    - Events are delivered in FIFO order.
    - When queue is full, oldest event is dropped (R-09 drop policy).
    - Drop counter increments; WARNING logged once per 100 drops.
    - receive() yields events in loop thread only.
    - Burst of 1000 events does not deadlock.
"""
from __future__ import annotations

import asyncio
import threading

import pytest


class TestMouseEventBridgeBasic:
    """Basic single-event submit → receive round-trip."""

    def test_submit_then_receive_single_event(self) -> None:
        """submit() from the main thread delivers event via receive()."""
        from eou.bridge import MouseEventBridge

        async def _run() -> None:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=8)

            bridge.submit(42)
            result = await bridge.receive()
            assert result == 42

        asyncio.run(_run())

    def test_fifo_order_preserved(self) -> None:
        """Events arrive in the same order they were submitted."""
        from eou.bridge import MouseEventBridge

        async def _run() -> list[int]:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=16)
            for i in range(5):
                bridge.submit(i)
            return [await bridge.receive() for _ in range(5)]

        results = asyncio.run(_run())
        assert results == [0, 1, 2, 3, 4]


class TestMouseEventBridgeBackpressure:
    """Backpressure: when queue is full, oldest event is dropped."""

    def test_oldest_dropped_when_full(self) -> None:
        """When maxsize is reached, submit() drops the oldest item."""
        from eou.bridge import MouseEventBridge

        async def _run() -> list[int]:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=3)

            # Fill the queue
            bridge.submit(10)
            bridge.submit(20)
            bridge.submit(30)
            # This triggers a drop: oldest (10) is removed and 40 is added
            bridge.submit(40)

            return [await bridge.receive() for _ in range(3)]

        results = asyncio.run(_run())
        # 10 was dropped; 20, 30, 40 remain
        assert results == [20, 30, 40]

    def test_drop_counter_increments(self) -> None:
        """drop_count attribute increases for each dropped event."""
        from eou.bridge import MouseEventBridge

        async def _run() -> int:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=2)

            bridge.submit("a")
            bridge.submit("b")
            bridge.submit("c")  # drops "a"
            bridge.submit("d")  # drops "b"
            return bridge.drop_count

        drops = asyncio.run(_run())
        assert drops == 2

    def test_warning_logged_every_100_drops(self, caplog: pytest.LogCaptureFixture) -> None:
        """A WARNING is logged once per 100 drops."""
        import logging

        from eou.bridge import MouseEventBridge

        async def _run() -> None:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=1)
            with caplog.at_level(logging.WARNING):
                for i in range(105):
                    bridge.submit(i)

        asyncio.run(_run())
        warning_messages = [r for r in caplog.records if r.levelno == logging.WARNING]
        # At 100 drops and 200 drops; 105 drops → 1 warning at the 100th drop
        assert len(warning_messages) >= 1


class TestMouseEventBridgeThreadSafety:
    """Thread-safety: submit() can be called from a non-loop thread."""

    def test_submit_from_thread_no_deadlock(self) -> None:
        """Burst of 1000 events from a separate thread does not deadlock.

        plan.md R-09: burst 1000 events, observe drop count, assert no deadlock.
        """
        from eou.bridge import MouseEventBridge

        collected: list[int] = []
        done = threading.Event()

        async def _consumer(bridge: MouseEventBridge) -> None:
            while len(collected) < 256:  # collect up to maxsize events
                try:
                    event = await asyncio.wait_for(bridge.receive(), timeout=2.0)
                    collected.append(event)
                except asyncio.TimeoutError:
                    break
            done.set()

        async def _run() -> MouseEventBridge:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=256)

            asyncio.ensure_future(_consumer(bridge))

            def _producer() -> None:
                for i in range(1000):
                    bridge.submit(i)

            t = threading.Thread(target=_producer)
            t.start()
            # Wait for consumer to finish or timeout
            await asyncio.sleep(3.0)
            t.join(timeout=1.0)
            return bridge

        bridge = asyncio.run(_run())
        # Verify: some events were received, no deadlock occurred
        assert len(collected) > 0
        # Total events: 1000; queue capacity: 256; drops must account for the rest
        assert bridge.drop_count + len(collected) <= 1000

    def test_submit_called_from_loop_thread_directly(self) -> None:
        """submit() works even when called from within the event loop (same thread).

        This simulates test code calling submit() without a real OS thread.
        """
        from eou.bridge import MouseEventBridge

        async def _run() -> int:
            loop = asyncio.get_event_loop()
            bridge = MouseEventBridge(loop=loop, maxsize=4)
            bridge.submit(99)
            return await bridge.receive()

        result = asyncio.run(_run())
        assert result == 99
