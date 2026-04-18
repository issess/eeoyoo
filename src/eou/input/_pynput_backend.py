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
        # Injection tagging: each call to move()/move_abs() is about to
        # cause one or more callback re-entries on the listener thread
        # (pynput observes its own synthetic Windows events). We track
        # a bounded credit counter so the next N on_move callbacks are
        # marked is_injected=True, which lets TakebackDetector filter
        # them out. The deadline guards against stale credits when
        # pynput coalesces or drops the synthetic callback.
        self._injection_credits: int = 0
        self._injection_deadline: float = 0.0
        self._injection_lock = threading.Lock()
        # Tagging diagnostics (read from any thread under the lock).
        self._injection_tagged: int = 0
        self._injection_missed: int = 0

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

            # Determine whether this callback is the echo of one of our
            # own synthetic moves (visibility.hide SetCursorPos on HOST,
            # or MouseInjector.inject_move on REMOTE). When it is, the
            # downstream takeback/outbound logic must treat it as a
            # software-injected event rather than physical user input.
            now = time.monotonic()
            is_injected = False
            with self._injection_lock:
                if self._injection_credits > 0 and now < self._injection_deadline:
                    self._injection_credits -= 1
                    self._injection_tagged += 1
                    is_injected = True
                elif self._injection_credits > 0:
                    # Deadline passed without a callback to consume the
                    # credit — pynput coalesced or dropped the event.
                    # Release stale credits so subsequent physical events
                    # are not mis-tagged.
                    self._injection_missed += self._injection_credits
                    self._injection_credits = 0

            ev = MouseEvent(
                dx=dx, dy=dy,
                abs_x=ix, abs_y=iy,
                is_injected=is_injected,
                ts=now,
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

    # Window in which a pynput callback following a synthetic move is
    # considered an "echo" of that move rather than physical user input.
    _INJECTION_WINDOW_S: float = 0.1

    def register_synthetic_move(self, count: int = 1) -> None:
        """Credit the next ``count`` pynput callbacks as synthetic echoes.

        Callers (MouseInjector on REMOTE, WindowsCursorVisibility on HOST)
        invoke this immediately before an API that moves the cursor via
        Windows (SetCursorPos, pynput Controller.move/position=). Each
        credit is consumed by the first pynput on_move callback that
        arrives within ``_INJECTION_WINDOW_S``, which then surfaces as
        ``MouseEvent.is_injected=True`` so TakebackDetector and similar
        consumers can filter out the self-inflicted event.
        """
        if count <= 0:
            return
        deadline = time.monotonic() + self._INJECTION_WINDOW_S
        with self._injection_lock:
            self._injection_credits += count
            # Always extend the deadline so later injections don't expire
            # earlier injections' credits.
            if deadline > self._injection_deadline:
                self._injection_deadline = deadline

    def move(self, dx: int, dy: int) -> None:
        """Inject a relative mouse movement (tags the echo as injected)."""
        self.register_synthetic_move()
        self._controller.move(dx, dy)

    def move_abs(self, x: int, y: int) -> None:
        """Move the cursor to an absolute screen coordinate (tags echo)."""
        self.register_synthetic_move()
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

    def injection_stats(self) -> dict[str, int]:
        """Return counters for the injection-tagging bookkeeping.

        Keys:
            credits_open:  Credits queued but not yet consumed (expected
                           synthetic echoes still in flight).
            tagged:        Events successfully marked is_injected=True.
            missed:        Credits retired by deadline without a matching
                           callback (indicates pynput coalescing).
        """
        with self._injection_lock:
            return {
                "credits_open": self._injection_credits,
                "tagged": self._injection_tagged,
                "missed": self._injection_missed,
            }
