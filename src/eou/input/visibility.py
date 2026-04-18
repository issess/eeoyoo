"""CursorVisibility Protocol and factory.

Defines the seam for OS-specific cursor hide/show operations.
The Protocol allows Slice 4 orchestration to wire up the real Windows
implementation or a NullCursorVisibility for non-Windows development.

REQ-MOUSE-VISIBILITY-001: CursorVisibility tracks pre_hide_position.
REQ-MOUSE-VISIBILITY-002: hide() parks cursor and installs hook.
REQ-MOUSE-VISIBILITY-003: show() restores cursor and removes hook.
REQ-MOUSE-VISIBILITY-004: No ShowCursor/SetSystemCursor/overlay.
REQ-MOUSE-VISIBILITY-005: No-op for CONTROLLED state on HOST (2-node MVP).

# @MX:ANCHOR: [AUTO] CursorVisibility — invariant OS-swap seam.
# @MX:REASON: All ownership state transitions that affect cursor visibility
#             (IDLE→CONTROLLING, CONTROLLING→IDLE) call through this Protocol.
#             Replacing the implementation for macOS/Linux requires only a
#             different concrete class passed to create_cursor_visibility().
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Optional callback fed by the WH_MOUSE_LL hook on Windows while the
# cursor is hidden. Arguments: (dx, dy, abs_x, abs_y). Allows HOST to
# receive mouse deltas from the hook itself during CONTROLLING, since
# the hook consumes events before they reach pynput's listener.
HookMouseCallback = Callable[[int, int, int, int], None]


@runtime_checkable
class CursorVisibility(Protocol):
    """Protocol for host-side cursor parking and event consumption.

    Implementations:
        - WindowsCursorVisibility: SetCursorPos + WH_MOUSE_LL hook (Windows).
        - NullCursorVisibility: no-op with state tracking (Linux/macOS dev).
        - FakeCursorVisibility: deterministic test double (tests/fakes/visibility.py).
    """

    def hide(
        self,
        pre_hide_position: tuple[int, int],
        on_mouse_event: HookMouseCallback | None = None,
        on_synthetic_move: Callable[[], None] | None = None,
    ) -> None:
        """Park the cursor and consume local mouse events.

        Args:
            pre_hide_position: OS cursor coordinates recorded just before
                the IDLE→CONTROLLING transition.  Used to restore the cursor
                when show() is called (REQ-MOUSE-VISIBILITY-003).
            on_mouse_event: Optional callback invoked from the OS hook
                thread for every WM_MOUSEMOVE while hidden. Arguments are
                (dx, dy, abs_x, abs_y). Implementations that do not install
                a global hook (Null, Fake) may ignore this argument.
            on_synthetic_move: Optional callback invoked immediately before
                any SetCursorPos call issued by this method. Backends use
                this to pre-tag the echoing pynput callback as injected so
                it is not confused with physical input. Ignored by no-op
                implementations.
        """
        ...

    def show(self) -> None:
        """Restore the cursor to pre_hide_position and remove the hook.

        Idempotent: safe to call when not hidden.
        """
        ...

    def is_hidden(self) -> bool:
        """Return True when the cursor is currently parked/hidden."""
        ...


class NullCursorVisibility:
    """No-op CursorVisibility for non-Windows platforms.

    Tracks internal state so tests and orchestration code can observe
    hide/show calls without touching the real OS cursor.

    Used automatically on Linux and macOS by create_cursor_visibility().
    """

    def __init__(self) -> None:
        self._hidden: bool = False
        self._pre_hide_position: tuple[int, int] | None = None

    def hide(
        self,
        pre_hide_position: tuple[int, int],
        on_mouse_event: HookMouseCallback | None = None,
        on_synthetic_move: Callable[[], None] | None = None,
    ) -> None:
        """Record position and mark hidden. Idempotent: updates position.

        ``on_mouse_event`` and ``on_synthetic_move`` are accepted for
        Protocol compatibility but ignored (no OS hook is installed
        off-Windows and no SetCursorPos is issued).
        """
        del on_mouse_event, on_synthetic_move  # unused on non-Windows backends
        self._pre_hide_position = pre_hide_position
        self._hidden = True

    def show(self) -> None:
        """Mark not hidden. Idempotent."""
        self._hidden = False
        self._pre_hide_position = None

    def is_hidden(self) -> bool:
        """Return hidden state."""
        return self._hidden


def create_cursor_visibility(platform_name: str | None = None) -> CursorVisibility:
    """Factory that returns the appropriate CursorVisibility implementation.

    Args:
        platform_name: Override for sys.platform (used in tests).
            Accepts "win32", "linux", "darwin", etc.
            Defaults to sys.platform when None.

    Returns:
        WindowsCursorVisibility on win32, NullCursorVisibility elsewhere.
    """
    target = platform_name if platform_name is not None else sys.platform
    if target == "win32":
        from eou.input._visibility_windows import WindowsCursorVisibility

        return WindowsCursorVisibility()
    return NullCursorVisibility()
