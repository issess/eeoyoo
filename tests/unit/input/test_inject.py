"""Tests for MouseInjector.

T-024 RED phase — tests must FAIL before T-025 GREEN.

REQ-MOUSE-TAKEBACK-003: injected events are tagged so TakebackDetector ignores them.
"""
from __future__ import annotations

import pytest


class TestMouseInjector:
    """MouseInjector delegates to backend.move/move_abs and enforces delta clamp."""

    def test_inject_move_calls_backend_move(self) -> None:
        """inject_move(dx, dy) calls backend.move(dx, dy)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_move(10, -5)
        assert (10, -5) in fb.move_calls

    def test_inject_move_abs_calls_backend_move_abs(self) -> None:
        """inject_move_abs(x, y) calls backend.move_abs(x, y)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_move_abs(200, 300)
        assert (200, 300) in fb.move_abs_calls

    def test_inject_move_dx_overflow_raises(self) -> None:
        """inject_move with |dx| > 10000 raises InjectionOutOfRangeError."""
        from eou.input.inject import InjectionOutOfRangeError, MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        with pytest.raises(InjectionOutOfRangeError):
            inj.inject_move(10001, 0)

    def test_inject_move_dy_overflow_raises(self) -> None:
        """inject_move with |dy| > 10000 raises InjectionOutOfRangeError."""
        from eou.input.inject import InjectionOutOfRangeError, MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        with pytest.raises(InjectionOutOfRangeError):
            inj.inject_move(0, -10001)

    def test_inject_move_negative_overflow_raises(self) -> None:
        """inject_move with dx = -10001 raises InjectionOutOfRangeError."""
        from eou.input.inject import InjectionOutOfRangeError, MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        with pytest.raises(InjectionOutOfRangeError):
            inj.inject_move(-10001, 0)

    def test_inject_move_boundary_exactly_10000_ok(self) -> None:
        """inject_move with |dx| == 10000 does not raise."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_move(10000, 10000)  # Should not raise
        assert (10000, 10000) in fb.move_calls

    def test_injection_out_of_range_is_value_error_subclass(self) -> None:
        """InjectionOutOfRangeError is a subclass of ValueError."""
        from eou.input.inject import InjectionOutOfRangeError

        assert issubclass(InjectionOutOfRangeError, ValueError)

    def test_inject_move_zero_delta_ok(self) -> None:
        """inject_move(0, 0) is valid and calls backend.move."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_move(0, 0)
        assert (0, 0) in fb.move_calls

    def test_inject_click_left_press(self) -> None:
        """inject_click('left', True) calls backend.click('left', True)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_click("left", True)
        assert ("left", True) in fb.click_calls

    def test_inject_click_right_release(self) -> None:
        """inject_click('right', False) calls backend.click('right', False)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_click("right", False)
        assert ("right", False) in fb.click_calls

    def test_inject_click_middle(self) -> None:
        """inject_click('middle', True) calls backend.click('middle', True)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_click("middle", True)
        assert ("middle", True) in fb.click_calls

    def test_inject_click_invalid_button_raises(self) -> None:
        """inject_click with unknown button raises ValueError."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        with pytest.raises(ValueError, match="Unknown button"):
            inj.inject_click("x2", True)

    def test_inject_scroll_vertical(self) -> None:
        """inject_scroll(0, -3) calls backend.scroll(0, -3)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_scroll(0, -3)
        assert (0, -3) in fb.scroll_calls

    def test_inject_scroll_horizontal(self) -> None:
        """inject_scroll(2, 0) calls backend.scroll(2, 0)."""
        from eou.input.inject import MouseInjector
        from tests.fakes.mouse import FakeMouseBackend

        fb = FakeMouseBackend()
        inj = MouseInjector(backend=fb)
        inj.inject_scroll(2, 0)
        assert (2, 0) in fb.scroll_calls
