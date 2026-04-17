"""Tests for MouseCapture.

T-022 RED phase — tests must FAIL before T-023 GREEN.

REQ-MOUSE-TAKEBACK-003: injected events forwarded with is_injected flag intact.
"""
from __future__ import annotations


class TestMouseCapture:
    """MouseCapture forwards backend events to the provided queue callable."""

    def test_start_calls_backend_start_capture(self) -> None:
        """start() calls backend.start_capture() with an internal callback."""
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received = []
        mc = MouseCapture(backend=fb, queue=received.append)
        mc.start()
        assert fb.is_running() is True

    def test_stop_calls_backend_stop_capture(self) -> None:
        """stop() calls backend.stop_capture()."""
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received = []
        mc = MouseCapture(backend=fb, queue=received.append)
        mc.start()
        mc.stop()
        assert fb.is_running() is False

    def test_events_forwarded_to_queue(self) -> None:
        """Events received from backend are forwarded to queue unchanged."""
        from eou.input.backend import MouseEvent
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received = []
        mc = MouseCapture(backend=fb, queue=received.append)
        mc.start()

        events = [
            MouseEvent(dx=i, dy=-i, abs_x=i * 5, abs_y=i * 5, is_injected=False, ts=float(i))
            for i in range(3)
        ]
        for evt in events:
            fb.feed_event(evt)

        assert len(received) == 3
        assert all(r is e for r, e in zip(received, events))

    def test_is_injected_flag_preserved(self) -> None:
        """Events with is_injected=True pass through with the flag intact."""
        from eou.input.backend import MouseEvent
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received = []
        mc = MouseCapture(backend=fb, queue=received.append)
        mc.start()

        injected = MouseEvent(dx=1, dy=0, abs_x=0, abs_y=0, is_injected=True, ts=0.1)
        fb.feed_event(injected)

        assert received[0].is_injected is True

    def test_double_start_is_idempotent(self) -> None:
        """Calling start() twice does not raise and backend stays running."""
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        mc = MouseCapture(backend=fb, queue=lambda e: None)
        mc.start()
        mc.start()  # Second call must not raise
        assert fb.is_running() is True

    def test_stop_before_start_is_no_op(self) -> None:
        """Calling stop() before start() does not raise."""
        from eou.input.capture import MouseCapture
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        mc = MouseCapture(backend=fb, queue=lambda e: None)
        mc.stop()  # Must not raise
        assert fb.is_running() is False
