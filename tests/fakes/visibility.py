"""FakeCursorVisibility — deterministic in-memory test double.

# @MX:NOTE: [AUTO] FakeCursorVisibility is the test seam for visibility wiring.
# It is NOT production code.  Use it wherever WindowsCursorVisibility would be
# used in production, to verify that hide()/show() are called at the right
# ownership-state transitions without touching any OS API.
#
# This fake is stable across Slice 3 and Slice 4 integration tests; do not
# change its public API without updating all callers.

REQ-MOUSE-VISIBILITY-002: hide() while already hidden updates pre_hide_position.
REQ-MOUSE-VISIBILITY-003: show() while not hidden is a no-op but counts.
"""
from __future__ import annotations

from collections.abc import Callable


class FakeCursorVisibility:
    """In-memory CursorVisibility implementation for tests.

    Attributes:
        hidden: Current hidden state (True after hide(), False after show()).
        pre_hide_position: Last position passed to hide(), or None.
        hook_installed: Simulated hook installation state.
        show_call_count: Total number of times show() was called.
        hide_call_count: Total number of times hide() was called.
    """

    def __init__(self) -> None:
        self.hidden: bool = False
        self.pre_hide_position: tuple[int, int] | None = None
        self.hook_installed: bool = False
        self.show_call_count: int = 0
        self.hide_call_count: int = 0
        self.on_mouse_event: Callable[[int, int, int, int], None] | None = None
        self.on_synthetic_move: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # CursorVisibility Protocol
    # ------------------------------------------------------------------

    def hide(
        self,
        pre_hide_position: tuple[int, int],
        on_mouse_event: Callable[[int, int, int, int], None] | None = None,
        on_synthetic_move: Callable[[], None] | None = None,
    ) -> None:
        """Mark hidden and record position.

        Idempotent: if called while already hidden, updates pre_hide_position
        (models re-entry during the 50 ms restore window per strategy.md open
        question resolution — new transition preempts in-flight restore).
        """
        self.pre_hide_position = pre_hide_position
        self.on_mouse_event = on_mouse_event
        self.on_synthetic_move = on_synthetic_move
        self.hidden = True
        self.hook_installed = True
        self.hide_call_count += 1

    def show(self) -> None:
        """Mark not hidden. Increments counter even if not currently hidden."""
        self.show_call_count += 1
        if not self.hidden:
            # No-op but counter is still incremented for test observability
            return
        self.hidden = False
        self.hook_installed = False

    def is_hidden(self) -> bool:
        """Return current hidden state."""
        return self.hidden
