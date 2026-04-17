"""FakeMouseBackend — deterministic in-memory mouse backend for tests.

# @MX:NOTE: [AUTO] FakeMouseBackend is the test seam for all mouse capture/inject
# tests. It does not spawn threads, does not call pynput, and does not touch the
# OS. Use feed_event() to simulate OS events arriving at the capture callback.
"""
from __future__ import annotations

from collections.abc import Callable

from eou.input.backend import MouseEvent


class FakeMouseBackend:
    """In-memory, single-threaded implementation of the MouseBackend Protocol.

    Attributes:
        move_calls: List of (dx, dy) tuples passed to move().
        move_abs_calls: List of (x, y) tuples passed to move_abs().
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._callback: Callable[[MouseEvent], None] | None = None
        self._position: tuple[int, int] = (0, 0)
        self.move_calls: list[tuple[int, int]] = []
        self.move_abs_calls: list[tuple[int, int]] = []

    # ------------------------------------------------------------------
    # MouseBackend Protocol implementation
    # ------------------------------------------------------------------

    def start_capture(self, on_event: Callable[[MouseEvent], None]) -> None:
        """Register callback and mark backend as running."""
        self._callback = on_event
        self._running = True

    def stop_capture(self) -> None:
        """Stop capture. Idempotent."""
        self._running = False
        self._callback = None

    def move(self, dx: int, dy: int) -> None:
        """Record relative move without touching the OS."""
        self.move_calls.append((dx, dy))

    def move_abs(self, x: int, y: int) -> None:
        """Record absolute move and update internal position."""
        self.move_abs_calls.append((x, y))
        self._position = (x, y)

    def get_position(self) -> tuple[int, int]:
        """Return the last position set by move_abs, or (0, 0)."""
        return self._position

    def is_running(self) -> bool:
        """Return True if start_capture has been called and not yet stopped."""
        return self._running

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def feed_event(self, event: MouseEvent) -> None:
        """Deliver an event directly to the registered callback.

        Call this from test code to simulate OS mouse events without
        spawning real threads or touching pynput.

        If no callback is registered (before start_capture), this is a no-op.
        """
        if self._callback is not None:
            self._callback(event)
