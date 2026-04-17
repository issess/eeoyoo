"""MouseInjector — commands relative/absolute mouse movement via MouseBackend.

# @MX:WARN: [AUTO] Injection tagging window size affects takeback accuracy.
# @MX:REASON: If the window is too small, injected events that arrive slightly
#             late are not recognized as injected, and TakebackDetector may fire
#             a false-positive takeback (REQ-MOUSE-TAKEBACK-003).  If the window
#             is too large, real physical events near an injection are silently
#             suppressed. The backend is responsible for tagging is_injected on
#             re-captured events; this class only issues the movement commands.

REQ-MOUSE-TAKEBACK-003: The backend is responsible for marking re-captured
events with is_injected=True.  MouseInjector only issues move commands.
"""
from __future__ import annotations

from eou.input.backend import MouseBackend

# Maximum allowed absolute value for dx or dy in a single inject_move call.
# Larger values indicate malformed or corrupted wire data.
_MAX_DELTA: int = 10000


class InjectionOutOfRangeError(ValueError):
    """Raised when inject_move receives a delta exceeding the allowed range.

    REQ-MOUSE-PROTOCOL-003: MOUSE_MOVE dx/dy are finite-range integers.
    A delta beyond _MAX_DELTA is treated as a malformed message.
    """


class MouseInjector:
    """Injects relative and absolute mouse movements via the MouseBackend.

    Args:
        backend: The OS-level backend that accepts move commands.
    """

    def __init__(self, backend: MouseBackend) -> None:
        self._backend = backend

    def inject_move(self, dx: int, dy: int) -> None:
        """Inject a relative mouse movement.

        Args:
            dx: Horizontal delta in pixels.
            dy: Vertical delta in pixels.

        Raises:
            InjectionOutOfRangeError: If |dx| > 10000 or |dy| > 10000.
        """
        if abs(dx) > _MAX_DELTA or abs(dy) > _MAX_DELTA:
            raise InjectionOutOfRangeError(
                f"Delta ({dx}, {dy}) exceeds maximum allowed range ±{_MAX_DELTA}. "
                "Message may be malformed."
            )
        self._backend.move(dx, dy)

    def inject_move_abs(self, x: int, y: int) -> None:
        """Inject an absolute cursor position.

        Args:
            x: Absolute x-coordinate.
            y: Absolute y-coordinate.
        """
        self._backend.move_abs(x, y)
