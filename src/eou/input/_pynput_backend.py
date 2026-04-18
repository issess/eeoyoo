"""Production MouseBackend implementation backed by pynput.

Runs ``pynput.mouse.Listener`` on its own OS thread. Each observed cursor
position is converted into a ``MouseEvent`` with ``dx`` / ``dy`` computed
relative to the previously observed position.

# @MX:WARN: [AUTO] on_event is invoked from pynput's listener OS thread.
# @MX:REASON: Callers (MouseCapture -> MouseEventBridge.submit) must remain
#             thread-safe. bridge.submit() already uses call_soon_threadsafe,
#             so this backend passes events through directly.

This backend intentionally does not populate the ``is_injected`` flag with
the Windows LLMHF_INJECTED bit: pynput does not expose it. ``is_injected``
is only consumed by REMOTE-side TakebackDetector; capturing physical input
on HOST does not need the distinction.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pynput import mouse  # type: ignore[import-untyped]

from eou.input.backend import MouseEvent


class PynputMouseBackend:
    """Concrete MouseBackend wrapping pynput.mouse.Listener + Controller."""

    def __init__(self) -> None:
        self._listener: mouse.Listener | None = None
        self._controller: mouse.Controller = mouse.Controller()
        self._prev_pos: tuple[int, int] | None = None
        self._lock = threading.Lock()
        # Cumulative count of events emitted to the user callback since
        # start_capture(). Readable from any thread; used by HOST for
        # diagnostic logging (no mutation from asyncio thread).
        self._event_count: int = 0

    def start_capture(self, on_event: Callable[[MouseEvent], None]) -> None:
        """Begin listening for OS mouse events. Idempotent."""
        if self._listener is not None and self._listener.is_alive():
            return

        def _on_move(x: float, y: float) -> None:
            ix, iy = int(x), int(y)
            with self._lock:
                prev = self._prev_pos
                self._prev_pos = (ix, iy)
            dx = 0 if prev is None else ix - prev[0]
            dy = 0 if prev is None else iy - prev[1]
            ev = MouseEvent(
                dx=dx, dy=dy,
                abs_x=ix, abs_y=iy,
                is_injected=False,
                ts=time.monotonic(),
            )
            self._event_count += 1
            try:
                on_event(ev)
            except Exception:
                # Never let a user callback crash the listener thread.
                pass

        listener = mouse.Listener(on_move=_on_move)
        listener.daemon = True
        listener.start()
        self._listener = listener

    def stop_capture(self) -> None:
        """Stop the OS mouse listener. Idempotent."""
        listener = self._listener
        if listener is None:
            return
        self._listener = None
        try:
            listener.stop()
        except Exception:
            pass

    def move(self, dx: int, dy: int) -> None:
        """Inject a relative mouse movement."""
        self._controller.move(dx, dy)

    def move_abs(self, x: int, y: int) -> None:
        """Move the cursor to an absolute screen coordinate."""
        self._controller.position = (x, y)

    def get_position(self) -> tuple[int, int]:
        """Return the current cursor position as (x, y)."""
        x, y = self._controller.position
        return int(x), int(y)

    def is_running(self) -> bool:
        """Return True if the backend is actively capturing events."""
        listener = self._listener
        return listener is not None and listener.is_alive()

    def event_count(self) -> int:
        """Return cumulative count of events delivered since start_capture().

        Used by HOST for diagnostic logging to confirm that the pynput
        listener is actually producing events while CONTROLLING.
        """
        return self._event_count
