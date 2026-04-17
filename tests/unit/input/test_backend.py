"""Tests for MouseBackend Protocol and FakeMouseBackend.

T-020 RED phase — all tests must FAIL before T-021 GREEN.

REQ-MOUSE-TAKEBACK-003: injected events must be distinguishable from physical events.
"""
from __future__ import annotations


class TestMouseEventDataclass:
    """MouseEvent dataclass contract tests."""

    def test_mouse_event_fields(self) -> None:
        """MouseEvent has required fields: dx, dy, abs_x, abs_y, is_injected, ts."""
        from eou.input.backend import MouseEvent

        evt = MouseEvent(dx=1, dy=2, abs_x=100, abs_y=200, is_injected=False, ts=1.0)
        assert evt.dx == 1
        assert evt.dy == 2
        assert evt.abs_x == 100
        assert evt.abs_y == 200
        assert evt.is_injected is False
        assert evt.ts == 1.0

    def test_mouse_event_is_injected_true(self) -> None:
        """is_injected flag is preserved."""
        from eou.input.backend import MouseEvent

        evt = MouseEvent(dx=0, dy=0, abs_x=0, abs_y=0, is_injected=True, ts=0.0)
        assert evt.is_injected is True

    def test_mouse_event_is_dataclass(self) -> None:
        """MouseEvent is a dataclass (has __dataclass_fields__)."""
        from eou.input.backend import MouseEvent

        assert hasattr(MouseEvent, "__dataclass_fields__")


class TestMouseBackendProtocol:
    """MouseBackend Protocol structural contract."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """MouseBackend is a runtime-checkable Protocol."""
        from eou.input.backend import MouseBackend

        # runtime_checkable means isinstance() does not raise TypeError
        # (though it only checks for the existence of methods, not signatures)
        assert hasattr(MouseBackend, "__protocol_attrs__") or hasattr(
            MouseBackend, "_is_protocol"
        )

    def test_protocol_has_required_methods(self) -> None:
        """MouseBackend declares all required methods."""
        from eou.input.backend import MouseBackend

        required = {
            "start_capture",
            "stop_capture",
            "move",
            "move_abs",
            "get_position",
            "is_running",
        }
        # Protocol methods are accessible as regular class attributes
        for method_name in required:
            assert hasattr(MouseBackend, method_name), (
                f"MouseBackend missing method: {method_name}"
            )

    def test_fake_backend_satisfies_protocol(self) -> None:
        """FakeMouseBackend isinstance-checks as MouseBackend."""
        from eou.input.backend import MouseBackend
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        assert isinstance(fb, MouseBackend)


class TestFakeMouseBackend:
    """FakeMouseBackend deterministic behaviour — no threads, no OS."""

    def test_initial_state_not_running(self) -> None:
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        assert fb.is_running() is False

    def test_start_capture_sets_running(self) -> None:
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received: list[MouseEvent] = []
        fb.start_capture(received.append)
        assert fb.is_running() is True

    def test_stop_capture_clears_running(self) -> None:
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received: list[MouseEvent] = []
        fb.start_capture(received.append)
        fb.stop_capture()
        assert fb.is_running() is False

    def test_events_forwarded_to_callback(self) -> None:
        """feed_event() delivers events through the registered callback."""
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received: list[MouseEvent] = []
        fb.start_capture(received.append)

        evt = MouseEvent(dx=3, dy=-4, abs_x=50, abs_y=60, is_injected=False, ts=0.1)
        fb.feed_event(evt)

        assert len(received) == 1
        assert received[0] is evt

    def test_injected_flag_preserved_in_round_trip(self) -> None:
        """Events with is_injected=True are forwarded with is_injected=True intact."""
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received: list[MouseEvent] = []
        fb.start_capture(received.append)

        injected_evt = MouseEvent(dx=1, dy=0, abs_x=0, abs_y=0, is_injected=True, ts=0.5)
        fb.feed_event(injected_evt)

        assert received[0].is_injected is True

    def test_move_records_relative_delta(self) -> None:
        """move(dx, dy) records the delta in move_calls."""
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        fb.move(10, -5)
        assert (10, -5) in fb.move_calls

    def test_move_abs_records_absolute_position(self) -> None:
        """move_abs(x, y) records the position in move_abs_calls."""
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        fb.move_abs(200, 300)
        assert (200, 300) in fb.move_abs_calls

    def test_get_position_returns_current(self) -> None:
        """get_position() returns the last absolute position set via move_abs."""
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        fb.move_abs(400, 500)
        assert fb.get_position() == (400, 500)

    def test_get_position_default(self) -> None:
        """get_position() returns (0, 0) before any move_abs calls."""
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        assert fb.get_position() == (0, 0)

    def test_feed_event_without_callback_is_no_op(self) -> None:
        """Feeding events before start_capture does not raise."""
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        evt = MouseEvent(dx=0, dy=0, abs_x=0, abs_y=0, is_injected=False, ts=0.0)
        fb.feed_event(evt)  # Should not raise

    def test_multiple_events_all_forwarded(self) -> None:
        """Three events all reach the callback in order."""
        from eou.input.backend import MouseEvent
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        received: list[MouseEvent] = []
        fb.start_capture(received.append)

        events = [
            MouseEvent(dx=i, dy=i, abs_x=i * 10, abs_y=i * 10, is_injected=False, ts=float(i))
            for i in range(3)
        ]
        for evt in events:
            fb.feed_event(evt)

        assert len(received) == 3
        assert [e.dx for e in received] == [0, 1, 2]
