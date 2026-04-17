"""Takeback detector for SPEC-MOUSE-001.

Detects physical (non-injected) mouse activity that should trigger ownership
return from REMOTE to HOST while the local node is in CONTROLLED state.

REQ-MOUSE-TAKEBACK-001: Triggers when:
    (a) cumulative |dx|+|dy| of non-injected events within time_window_ms >= pixel_threshold, OR
    (b) number of non-injected events within time_window_ms >= event_count_threshold.
REQ-MOUSE-TAKEBACK-002: Detector resets after each trigger.
REQ-MOUSE-TAKEBACK-003: is_injected=True events are completely ignored.
REQ-MOUSE-TAKEBACK-004: State guard is the caller's responsibility
    (TakebackDetector is stateless w.r.t. OwnershipState).
"""

from __future__ import annotations

import collections
import dataclasses
import time
from typing import Callable


# ---------------------------------------------------------------------------
# TakebackConfig
# ---------------------------------------------------------------------------

# @MX:NOTE: [AUTO] TakebackConfig default heuristic rationale (REQ-MOUSE-TAKEBACK-001):
#   - pixel_threshold=5: matches typical cursor micro-jitter (1-3px) while
#     being safely below deliberate movement (10+ px). Chosen to balance
#     false-positive (drift triggers takeback) vs false-negative (real input
#     not detected). Configurable to address R-04 (takeback false-positive risk).
#   - event_count_threshold=2: single-event clicks may be accidental; two events
#     in the window reliably indicate intentional local use.
#   - time_window_ms=100: 100 ms is the REQ-MOUSE-TAKEBACK-002 latency budget.
#     A rolling window wider than this would delay takeback detection.
@dataclasses.dataclass(frozen=True)
class TakebackConfig:
    """Configuration for the takeback detector.

    All fields are immutable after construction.
    """

    pixel_threshold: int = 5
    event_count_threshold: int = 2
    time_window_ms: int = 100


# ---------------------------------------------------------------------------
# Internal event record
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _EventRecord:
    ts: float  # monotonic seconds
    pixels: int  # |dx| + |dy|


# ---------------------------------------------------------------------------
# TakebackDetector
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] TakebackDetector.observe — entry point for physical input classification.
# @MX:REASON: Slice 4 (host.py/remote.py), Slice 3 (capture bridge), and the
#             OwnershipCoordinator all call observe() to classify each input event.
#             fan_in will reach 3+ in Slice 4. Changing the return semantics
#             (bool vs None vs enum) silently breaks takeback triggering.
class TakebackDetector:
    """Pure-sync takeback detector.

    Maintains a rolling window of non-injected mouse events and fires when
    either the cumulative pixel displacement or the event count crosses its
    configured threshold.

    The now parameter accepts any Callable[[], float] returning monotonic
    seconds. Defaults to time.monotonic for production; inject a fake clock
    for deterministic unit tests.
    """

    def __init__(
        self,
        config: TakebackConfig | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or TakebackConfig()
        self._now = now
        self._window: collections.deque[_EventRecord] = collections.deque()

    def observe(self, dx: int, dy: int, is_injected: bool) -> bool:
        """Classify a mouse event and return True if a takeback should be triggered.

        Injected events (is_injected=True) are ignored entirely.

        Args:
            dx: Horizontal pixel delta (signed; absolute value used).
            dy: Vertical pixel delta (signed; absolute value used).
            is_injected: True if this event originated from a MOUSE_MOVE injection.

        Returns:
            True if the takeback threshold is crossed; False otherwise.

        REQ-MOUSE-TAKEBACK-003: injected events contribute nothing.
        REQ-MOUSE-TAKEBACK-001: rolling window pixel + count checks.
        REQ-MOUSE-TAKEBACK-002: resets after trigger.
        """
        if is_injected:
            return False

        ts_now = self._now()
        pixels = abs(dx) + abs(dy)
        self._window.append(_EventRecord(ts=ts_now, pixels=pixels))
        self._prune_window(ts_now)

        cumulative_px = sum(r.pixels for r in self._window)
        event_count = len(self._window)

        triggered = (
            cumulative_px >= self._config.pixel_threshold
            or event_count >= self._config.event_count_threshold
        )

        if triggered:
            self._window.clear()

        return triggered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_window(self, now: float) -> None:
        """Remove events older than time_window_ms from the left of the deque."""
        cutoff = now - self._config.time_window_ms / 1000.0
        while self._window and self._window[0].ts <= cutoff:
            self._window.popleft()
