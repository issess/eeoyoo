"""Tests for EdgeDetector (REQ-MOUSE-EDGE-001..005).

RED phase tests — T-014.

Coverage:
- REQ-MOUSE-EDGE-001: sampling is O(1) per call (pure logic, no async)
- REQ-MOUSE-EDGE-002: CROSS_OUT emitted only after dwell_ticks consecutive within threshold
- REQ-MOUSE-EDGE-003: symmetric return edge monitoring (state=CONTROLLED)
- REQ-MOUSE-EDGE-004: EdgeConfig.from_dict with unknown keys raises ValueError
- REQ-MOUSE-EDGE-005: single brief touch must NOT emit CROSS_OUT
"""

from __future__ import annotations

import pytest

from eou.ownership.edge_detector import EdgeConfig, EdgeDetector, EdgeEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def right_edge_config() -> EdgeConfig:
    """Standard right-edge config: threshold=2px, dwell=2 ticks, 1920x1080."""
    return EdgeConfig(
        edge="right",
        threshold_px=2,
        dwell_ticks=2,
        screen_bounds=(0, 0, 1919, 1079),
    )


@pytest.fixture
def right_detector(right_edge_config: EdgeConfig) -> EdgeDetector:
    return EdgeDetector(right_edge_config)


# ---------------------------------------------------------------------------
# REQ-MOUSE-EDGE-001: O(1) per call — structural test
# ---------------------------------------------------------------------------


class TestEdgeDetectorBasics:
    def test_edge_detector_is_constructible(self, right_edge_config: EdgeConfig) -> None:
        """EdgeDetector can be constructed from EdgeConfig."""
        det = EdgeDetector(right_edge_config)
        assert det is not None

    def test_observe_returns_none_when_cursor_far_from_edge(
        self, right_detector: EdgeDetector
    ) -> None:
        """observe() returns None when cursor is far from configured edge.

        REQ-MOUSE-EDGE-005: no spurious events away from edge.
        """
        result = right_detector.observe(500, 500)
        assert result is None


# ---------------------------------------------------------------------------
# REQ-MOUSE-EDGE-002: dwell threshold — 2 consecutive ticks within 2px
# ---------------------------------------------------------------------------


class TestDwellThreshold:
    def test_two_consecutive_ticks_within_threshold_emits_cross_out(
        self, right_detector: EdgeDetector
    ) -> None:
        """observe() returns CROSS_OUT after dwell_ticks=2 consecutive observations
        within threshold_px=2 of the right edge.

        REQ-MOUSE-EDGE-002.
        """
        # Right edge x = 1919; threshold 2px → x >= 1917
        right_detector.observe(1918, 500)  # tick 1 (within 2px of 1919)
        result = right_detector.observe(1919, 500)  # tick 2
        assert result is EdgeEvent.CROSS_OUT

    def test_first_tick_alone_does_not_emit(self, right_detector: EdgeDetector) -> None:
        """Single tick within threshold does not emit CROSS_OUT.

        REQ-MOUSE-EDGE-005.
        """
        result = right_detector.observe(1919, 500)
        assert result is None

    def test_three_ticks_emit_only_on_second_tick(
        self, right_detector: EdgeDetector
    ) -> None:
        """CROSS_OUT fires on the dwell_ticks-th tick; subsequent ticks return None
        (detector resets after emission).

        REQ-MOUSE-EDGE-002: emit once per dwell satisfaction.
        """
        right_detector.observe(1918, 500)  # tick 1
        result_2 = right_detector.observe(1919, 500)  # tick 2 → emits
        result_3 = right_detector.observe(1919, 500)  # tick 3 → no re-emit
        assert result_2 is EdgeEvent.CROSS_OUT
        assert result_3 is None


# ---------------------------------------------------------------------------
# REQ-MOUSE-EDGE-005: brief touch (dwell not satisfied)
# ---------------------------------------------------------------------------


class TestDwellNotSatisfied:
    @pytest.mark.parametrize(
        "tick_sequence",
        [
            # 1 tick inside, then outside
            [(1919, 500, True), (500, 500, False)],
            # 1 tick inside, outside gap, then inside again (continuity broken)
            [(1919, 500, True), (500, 500, False), (1919, 500, True)],
            # outside, inside once only
            [(500, 500, False), (1919, 500, True)],
        ],
        ids=["single_touch_then_leave", "touch_gap_touch", "outside_then_single"],
    )
    def test_brief_touch_does_not_emit(
        self,
        right_detector: EdgeDetector,
        tick_sequence: list[tuple[int, int, bool]],
    ) -> None:
        """Sequences where dwell is not satisfied must NOT emit CROSS_OUT.

        REQ-MOUSE-EDGE-005.
        """
        result = None
        for x, y, _in_threshold in tick_sequence:
            result = right_detector.observe(x, y)
        # The last observation should not be CROSS_OUT
        assert result is not EdgeEvent.CROSS_OUT

    def test_dwell_counter_resets_on_leaving_threshold(
        self, right_detector: EdgeDetector
    ) -> None:
        """Leaving the threshold resets the dwell counter; re-entry restarts count.

        REQ-MOUSE-EDGE-005.
        """
        right_detector.observe(1919, 500)  # tick 1 (count=1)
        right_detector.observe(500, 500)  # exit (count=0)
        right_detector.observe(1919, 500)  # tick 1 again (count=1)
        result = right_detector.observe(500, 500)  # exit again
        assert result is None


# ---------------------------------------------------------------------------
# REQ-MOUSE-EDGE-004: config overrides
# ---------------------------------------------------------------------------


class TestEdgeConfigOverrides:
    def test_custom_threshold_and_dwell_are_respected(self) -> None:
        """EdgeConfig with threshold_px=5, dwell_ticks=3 overrides defaults.

        REQ-MOUSE-EDGE-004.
        """
        cfg = EdgeConfig(
            edge="right",
            threshold_px=5,
            dwell_ticks=3,
            screen_bounds=(0, 0, 1919, 1079),
        )
        det = EdgeDetector(cfg)
        # Right edge x=1919; threshold 5px → x >= 1914
        det.observe(1915, 500)  # tick 1
        det.observe(1916, 500)  # tick 2
        # Still no emit after only 2 ticks with dwell_ticks=3
        det.observe(1914, 500)  # tick 3 (separate detector used below)
        # Re-run in isolation
        det2 = EdgeDetector(cfg)
        det2.observe(1915, 500)  # tick 1
        result_no_emit = det2.observe(1916, 500)  # tick 2 — NOT yet 3 ticks
        assert result_no_emit is None

        det3 = EdgeDetector(cfg)
        det3.observe(1915, 500)  # tick 1
        det3.observe(1916, 500)  # tick 2
        result_emit = det3.observe(1917, 500)  # tick 3 → emit
        assert result_emit is EdgeEvent.CROSS_OUT

    def test_from_dict_valid(self) -> None:
        """EdgeConfig.from_dict with valid keys constructs correctly.

        REQ-MOUSE-EDGE-004.
        """
        cfg = EdgeConfig.from_dict(
            {
                "edge": "left",
                "threshold_px": 3,
                "dwell_ticks": 4,
                "screen_bounds": [0, 0, 1919, 1079],
            }
        )
        assert cfg.edge == "left"
        assert cfg.threshold_px == 3
        assert cfg.dwell_ticks == 4

    def test_from_dict_unknown_key_raises_value_error(self) -> None:
        """EdgeConfig.from_dict with unknown keys raises ValueError.

        REQ-MOUSE-EDGE-004.
        """
        with pytest.raises(ValueError, match="unknown"):
            EdgeConfig.from_dict(
                {
                    "edge": "right",
                    "threshold_px": 2,
                    "dwell_ticks": 2,
                    "screen_bounds": [0, 0, 1919, 1079],
                    "bad_key": 99,
                }
            )


# ---------------------------------------------------------------------------
# REQ-MOUSE-EDGE-003: left edge (symmetric return monitoring)
# ---------------------------------------------------------------------------


class TestSymmetricReturnEdge:
    def test_left_edge_dwell_emits_cross_out(self) -> None:
        """observe() emits CROSS_OUT for left edge when dwell satisfied.

        REQ-MOUSE-EDGE-003: symmetric return edge uses same threshold/dwell rules.
        """
        cfg = EdgeConfig(
            edge="left",
            threshold_px=2,
            dwell_ticks=2,
            screen_bounds=(0, 0, 1919, 1079),
        )
        det = EdgeDetector(cfg)
        det.observe(1, 500)  # tick 1 — x <= 0+2 = 2 → within threshold
        result = det.observe(0, 500)  # tick 2
        assert result is EdgeEvent.CROSS_OUT

    def test_top_edge_dwell_emits_cross_out(self) -> None:
        """Top edge cross-out after dwell satisfaction.

        REQ-MOUSE-EDGE-003.
        """
        cfg = EdgeConfig(
            edge="top",
            threshold_px=2,
            dwell_ticks=2,
            screen_bounds=(0, 0, 1919, 1079),
        )
        det = EdgeDetector(cfg)
        det.observe(500, 1)  # tick 1 — y <= 0+2=2
        result = det.observe(500, 0)  # tick 2
        assert result is EdgeEvent.CROSS_OUT

    def test_bottom_edge_dwell_emits_cross_out(self) -> None:
        """Bottom edge cross-out after dwell satisfaction.

        REQ-MOUSE-EDGE-003.
        """
        cfg = EdgeConfig(
            edge="bottom",
            threshold_px=2,
            dwell_ticks=2,
            screen_bounds=(0, 0, 1919, 1079),
        )
        det = EdgeDetector(cfg)
        det.observe(500, 1078)  # tick 1 — y >= 1079-2=1077
        result = det.observe(500, 1079)  # tick 2
        assert result is EdgeEvent.CROSS_OUT
