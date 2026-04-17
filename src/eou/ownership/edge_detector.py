"""Edge detector for SPEC-MOUSE-001 ownership transfer trigger.

Implements REQ-MOUSE-EDGE-001..005 as a pure synchronous observer.
No asyncio, no threading, no I/O. The sampling frequency (≥ 120 Hz)
is the responsibility of the orchestration layer (Slice 4).

REQ-MOUSE-EDGE-001: Each observe() call is O(1) (≥ 120 Hz sampling enforced
    by caller; no internal clock dependency).
REQ-MOUSE-EDGE-002: CROSS_OUT emitted only after dwell_ticks consecutive ticks
    within threshold_px of the configured edge.
REQ-MOUSE-EDGE-003: Symmetric return edge uses identical threshold/dwell rules.
REQ-MOUSE-EDGE-004: Per-edge config overrides via EdgeConfig.from_dict.
REQ-MOUSE-EDGE-005: Single brief touch must NOT emit CROSS_OUT.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Literal


# ---------------------------------------------------------------------------
# EdgeEvent
# ---------------------------------------------------------------------------


class EdgeEvent(Enum):
    """Events emitted by EdgeDetector.observe()."""

    CROSS_OUT = "CROSS_OUT"


# ---------------------------------------------------------------------------
# EdgeConfig
# ---------------------------------------------------------------------------

_KNOWN_KEYS = frozenset({"edge", "threshold_px", "dwell_ticks", "screen_bounds"})


@dataclasses.dataclass(frozen=True)
class EdgeConfig:
    """Configuration for a single monitored screen edge.

    REQ-MOUSE-EDGE-004: per-edge override support via from_dict().
    """

    edge: Literal["left", "right", "top", "bottom"]
    screen_bounds: tuple[int, int, int, int]  # (x1, y1, x2, y2) inclusive
    threshold_px: int = 2
    dwell_ticks: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "EdgeConfig":
        """Construct EdgeConfig from a plain dict.

        Raises:
            ValueError: If any unknown key is present in *data*.

        REQ-MOUSE-EDGE-004.
        """
        unknown = set(data.keys()) - _KNOWN_KEYS
        if unknown:
            raise ValueError(
                f"EdgeConfig.from_dict: unknown key(s): {sorted(unknown)}"
            )
        bounds_raw = data.get("screen_bounds", (0, 0, 0, 0))
        bounds: tuple[int, int, int, int] = tuple(int(v) for v in bounds_raw)  # type: ignore[assignment]
        return cls(
            edge=data["edge"],  # type: ignore[arg-type]
            threshold_px=int(data.get("threshold_px", 2)),
            dwell_ticks=int(data.get("dwell_ticks", 2)),
            screen_bounds=bounds,
        )


# ---------------------------------------------------------------------------
# EdgeDetector
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] EdgeDetector.observe — primary sampling entry point (REQ-MOUSE-EDGE-001).
# @MX:REASON: Slice 4 orchestration calls observe() at ≥ 120 Hz from the asyncio
#             event loop. fan_in will reach 3+ when Host, Remote, and the
#             coordinator all call it. Changing the return type or semantics here
#             silently breaks the dwell contract across all callers.
class EdgeDetector:
    """Pure-sync screen-edge proximity detector.

    Tracks consecutive ticks within the configured edge proximity threshold.
    Emits EdgeEvent.CROSS_OUT once the dwell condition is satisfied.

    # @MX:WARN: [AUTO] _dwell_count mutation is not thread-safe.
    # @MX:REASON: observe() must only be called from a single thread (asyncio
    #             event loop). pynput callbacks run on a separate OS thread —
    #             they must bridge via call_soon_threadsafe, never call observe()
    #             directly.
    """

    def __init__(self, config: EdgeConfig) -> None:
        self._config = config
        self._dwell_count: int = 0

    def observe(self, x: int, y: int) -> EdgeEvent | None:
        """Sample cursor position and return EdgeEvent.CROSS_OUT when dwell is satisfied.

        Args:
            x: Current cursor x-coordinate (screen pixels).
            y: Current cursor y-coordinate (screen pixels).

        Returns:
            EdgeEvent.CROSS_OUT if dwell condition just became satisfied; else None.

        REQ-MOUSE-EDGE-001: O(1) per call.
        REQ-MOUSE-EDGE-002: Emits CROSS_OUT after dwell_ticks consecutive ticks within threshold.
        REQ-MOUSE-EDGE-005: Single tick or non-consecutive ticks never emit.
        """
        if self._within_threshold(x, y):
            self._dwell_count += 1
            if self._dwell_count == self._config.dwell_ticks:
                # Reset so the same dwell run does not re-fire on the next tick
                self._dwell_count = 0
                return EdgeEvent.CROSS_OUT
        else:
            self._dwell_count = 0
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _within_threshold(self, x: int, y: int) -> bool:
        """Return True if (x, y) is within threshold_px of the configured edge."""
        x1, y1, x2, y2 = self._config.screen_bounds
        t = self._config.threshold_px
        edge = self._config.edge

        if edge == "right":
            return x >= x2 - t
        if edge == "left":
            return x <= x1 + t
        if edge == "bottom":
            return y >= y2 - t
        if edge == "top":
            return y <= y1 + t
        return False  # unreachable for valid Literal values
