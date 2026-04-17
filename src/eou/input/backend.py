"""MouseBackend Protocol and MouseEvent dataclass.

Defines the seam between the OS mouse layer and the rest of the input stack.
Concrete backends (pynput, ctypes, etc.) are injected at construction time;
unit tests inject FakeMouseBackend from tests/fakes/mouse.py.

# @MX:ANCHOR: [AUTO] MouseBackend — invariant seam for OS mouse abstraction.
# @MX:REASON: All capture and injection paths depend on this Protocol. Swapping
#             the backend (e.g., pynput → pywin32, or for test injection) is done
#             by providing a different MouseBackend implementation. The method
#             signatures here are a breaking contract.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class MouseEvent:
    """A single mouse event captured from or injected into the OS.

    Attributes:
        dx: Relative x movement in pixels (positive = right).
        dy: Relative y movement in pixels (positive = down).
        abs_x: Absolute cursor x-coordinate at event time.
        abs_y: Absolute cursor y-coordinate at event time.
        is_injected: True when this event originated from MouseInjector,
            not from the physical device.  Used by TakebackDetector to
            distinguish physical from synthetic input (REQ-MOUSE-TAKEBACK-003).
        ts: Monotonic timestamp (seconds) when the event was created.
    """

    dx: int
    dy: int
    abs_x: int
    abs_y: int
    is_injected: bool
    ts: float


@runtime_checkable
class MouseBackend(Protocol):
    """Protocol for OS-level mouse capture and injection.

    Implementations:
        - PynputMouseBackend: production backend using pynput (lazy import).
        - FakeMouseBackend (tests/fakes/mouse.py): deterministic in-memory backend.

    # @MX:ANCHOR: [AUTO] MouseBackend Protocol — must not change without updating
    # @MX:REASON: all concrete backends and callers (MouseCapture, MouseInjector).
    """

    def start_capture(self, on_event: Callable[[MouseEvent], None]) -> None:
        """Begin listening for OS mouse events.

        Args:
            on_event: Callback invoked synchronously (in the calling thread)
                for each received event.  Must be non-blocking.
        """
        ...

    def stop_capture(self) -> None:
        """Stop the OS mouse listener. Idempotent."""
        ...

    def move(self, dx: int, dy: int) -> None:
        """Inject a relative mouse movement.

        Args:
            dx: Horizontal delta in pixels.
            dy: Vertical delta in pixels.
        """
        ...

    def move_abs(self, x: int, y: int) -> None:
        """Move the cursor to an absolute screen coordinate.

        Args:
            x: Absolute x-coordinate.
            y: Absolute y-coordinate.
        """
        ...

    def get_position(self) -> tuple[int, int]:
        """Return the current cursor position as (x, y)."""
        ...

    def is_running(self) -> bool:
        """Return True if the backend is actively capturing events."""
        ...
