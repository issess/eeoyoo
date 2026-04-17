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
