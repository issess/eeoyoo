"""Tests for TakebackDetector (REQ-MOUSE-TAKEBACK-001..004).

RED phase tests — T-016.

Coverage:
- REQ-MOUSE-TAKEBACK-001: cumulative ≥5px OR ≥2 non-injected events within 100ms
- REQ-MOUSE-TAKEBACK-002: after trigger, detector resets for reuse
- REQ-MOUSE-TAKEBACK-003: is_injected=True events are completely ignored
- REQ-MOUSE-TAKEBACK-004: state-guarded — only fires while CONTROLLED (caller resp.)

Clock injection: all tests use a fake monotonic clock for determinism.
"""

from __future__ import annotations

import pytest

from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_clock(start: float = 0.0) -> "FakeClock":
    return FakeClock(start)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self._t = t

    def __call__(self) -> float:
        return self._t

    def advance(self, ms: float) -> None:
        self._t += ms / 1000.0


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(0.0)


@pytest.fixture
def detector(clock: FakeClock) -> TakebackDetector:
    cfg = TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)
    return TakebackDetector(config=cfg, now=clock)


# ---------------------------------------------------------------------------
# REQ-MOUSE-TAKEBACK-001 a: cumulative pixel threshold
# ---------------------------------------------------------------------------


class TestPixelThreshold:
    def test_exactly_4px_cumulative_does_not_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Exactly 4px cumulative (< 5px threshold) must NOT trigger.

        REQ-MOUSE-TAKEBACK-001.
        """
        result = detector.observe(dx=2, dy=2, is_injected=False)
        assert result is False

    def test_exactly_5px_cumulative_triggers(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Exactly 5px cumulative (= threshold) must trigger.

        REQ-MOUSE-TAKEBACK-001 (|dx|+|dy| = 5).
        """
        result = detector.observe(dx=3, dy=2, is_injected=False)
        assert result is True

    def test_split_across_two_events_triggers(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """5px spread across two observations within window triggers.

        REQ-MOUSE-TAKEBACK-001.
        """
        clock.advance(0)
        detector.observe(dx=2, dy=1, is_injected=False)  # 3px cumulative
        clock.advance(10)
        result = detector.observe(dx=1, dy=1, is_injected=False)  # +2px = 5px
        assert result is True

    def test_negative_delta_still_counts_absolute(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Negative dx/dy use absolute value for pixel accumulation.

        REQ-MOUSE-TAKEBACK-001.
        """
        result = detector.observe(dx=-3, dy=-2, is_injected=False)
        assert result is True


# ---------------------------------------------------------------------------
# REQ-MOUSE-TAKEBACK-001 b: event count threshold within time window
# ---------------------------------------------------------------------------


class TestEventCountThreshold:
    def test_exactly_1_event_within_window_does_not_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """1 non-injected event (< 2 threshold) must NOT trigger.

        REQ-MOUSE-TAKEBACK-001.
        """
        result = detector.observe(dx=0, dy=0, is_injected=False)
        assert result is False

    def test_exactly_2_events_within_100ms_triggers(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """2 non-injected events within 100ms window triggers.

        REQ-MOUSE-TAKEBACK-001 b.
        """
        detector.observe(dx=0, dy=0, is_injected=False)
        clock.advance(50)  # 50ms later
        result = detector.observe(dx=0, dy=0, is_injected=False)
        assert result is True

    def test_2_events_spanning_101ms_does_not_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """2 non-injected events spanning 101ms (outside window) must NOT trigger.

        REQ-MOUSE-TAKEBACK-001 b: rolling window enforcement.
        """
        detector.observe(dx=0, dy=0, is_injected=False)
        clock.advance(101)  # first event is now outside the 100ms window
        result = detector.observe(dx=0, dy=0, is_injected=False)
        assert result is False


# ---------------------------------------------------------------------------
# REQ-MOUSE-TAKEBACK-003: injected events are ignored
# ---------------------------------------------------------------------------


class TestInjectedEventsIgnored:
    def test_injected_events_do_not_count_toward_pixel_threshold(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """is_injected=True events contribute 0px to accumulation.

        REQ-MOUSE-TAKEBACK-003.
        """
        # 10 injected events, each 5px — none should trigger
        for _ in range(10):
            result = detector.observe(dx=5, dy=0, is_injected=True)
        assert result is False

    def test_injected_events_do_not_count_toward_event_count(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """is_injected=True events do not increment the event counter.

        REQ-MOUSE-TAKEBACK-003.
        """
        detector.observe(dx=0, dy=0, is_injected=True)
        detector.observe(dx=0, dy=0, is_injected=True)
        # Even with 2 injected events, no trigger (they're ignored)
        result = detector.observe(dx=0, dy=0, is_injected=True)
        assert result is False

    def test_injected_followed_by_one_physical_does_not_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """1 physical event after many injected events must not trigger event-count path.

        REQ-MOUSE-TAKEBACK-003: only non-injected events counted.
        """
        for _ in range(5):
            detector.observe(dx=0, dy=0, is_injected=True)
        result = detector.observe(dx=0, dy=0, is_injected=False)
        assert result is False  # only 1 physical event, threshold is 2

    def test_mixed_injected_and_physical_only_counts_physical(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Mixed sequence: only physical events count toward event threshold.

        REQ-MOUSE-TAKEBACK-003.
        """
        detector.observe(dx=0, dy=0, is_injected=False)  # physical: count=1
        detector.observe(dx=0, dy=0, is_injected=True)  # injected: ignored
        clock.advance(50)
        result = detector.observe(dx=0, dy=0, is_injected=False)  # physical: count=2 → trigger
        assert result is True


# ---------------------------------------------------------------------------
# REQ-MOUSE-TAKEBACK-002: reset after trigger
# ---------------------------------------------------------------------------


class TestResetAfterTrigger:
    def test_detector_resets_after_pixel_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """After triggering via pixel threshold, counters reset for reuse.

        REQ-MOUSE-TAKEBACK-002.
        """
        result1 = detector.observe(dx=5, dy=0, is_injected=False)
        assert result1 is True
        # Should not immediately re-trigger on the next observation
        result2 = detector.observe(dx=0, dy=0, is_injected=False)
        assert result2 is False

    def test_detector_resets_after_count_trigger(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """After triggering via event count, counters reset for reuse.

        REQ-MOUSE-TAKEBACK-002.
        """
        detector.observe(dx=0, dy=0, is_injected=False)
        clock.advance(10)
        result1 = detector.observe(dx=0, dy=0, is_injected=False)
        assert result1 is True
        # After reset, need 2 new events to trigger again
        clock.advance(10)
        result2 = detector.observe(dx=0, dy=0, is_injected=False)
        assert result2 is False


# ---------------------------------------------------------------------------
# Rolling window boundary tests
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_old_events_expire_from_window(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Events older than time_window_ms are pruned and do not count.

        REQ-MOUSE-TAKEBACK-001: rolling window semantics.
        """
        detector.observe(dx=0, dy=0, is_injected=False)  # t=0ms
        clock.advance(110)  # now at 110ms
        detector.observe(dx=0, dy=0, is_injected=False)  # t=110ms — first event expired
        clock.advance(10)  # now at 120ms
        result = detector.observe(dx=0, dy=0, is_injected=False)  # t=120ms
        # Only events at 110ms and 120ms are in window → exactly 2 → trigger
        assert result is True

    def test_pixel_accumulation_uses_window(
        self, detector: TakebackDetector, clock: FakeClock
    ) -> None:
        """Pixel accumulation should only count events within the rolling window.

        REQ-MOUSE-TAKEBACK-001.
        """
        detector.observe(dx=3, dy=0, is_injected=False)  # 3px at t=0
        clock.advance(110)  # first event now outside window
        # Only this 2px contributes (3px event expired)
        result = detector.observe(dx=2, dy=0, is_injected=False)  # 2px → total 2px in window
        assert result is False  # 2px < 5px threshold
