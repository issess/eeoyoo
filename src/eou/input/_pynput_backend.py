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

from eou.input.backend import MouseClickEvent, MouseEvent, MouseScrollEvent

# Map pynput Button enum values to wire-protocol button names.
_BUTTON_MAP: dict[mouse.Button, str] = {
    mouse.Button.left: "left",
    mouse.Button.right: "right",
    mouse.Button.middle: "middle",
}

# Reverse map for injection: wire name → pynput Button.
_BUTTON_REVERSE: dict[str, mouse.Button] = {v: k for k, v in _BUTTON_MAP.items()}


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
        # Injection tagging — two complementary modes guard against
        # pynput observing the cursor moves we issue ourselves:
        #
        # 1. Position queue (preferred): when the target coordinate of
        #    the synthetic move is known (relative move with known
        #    current position, absolute move), we record that target
        #    and tag the next pynput callback whose reported position
        #    sits within tolerance of any pending target. This is robust
        #    against high-frequency injects because each user event has
        #    an unpredictable position that will not match any pending
        #    target — so user motion is never falsely tagged.
        # 2. Counter (fallback): for sites that cannot predict the
        #    target (e.g., SetCursorPos to coordinates Windows clamps),
        #    a one-shot credit tags the next callback regardless of
        #    position. Race-prone if combined with continuous injects,
        #    so reserved for one-shot visibility hide/show.
        self._injection_credits: int = 0
        self._injection_deadline: float = 0.0
        self._pending_targets: list[tuple[int, int, float]] = []
        self._injection_lock = threading.Lock()
        # Tagging diagnostics (read from any thread under the lock).
        self._injection_tagged_position: int = 0
        self._injection_tagged_counter: int = 0
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
            #
            # Position queue is checked first so high-frequency injects
            # (REMOTE receiving HOST's MouseMove stream) cannot poison
            # the counter and falsely tag a real user takeback motion.
            now = time.monotonic()
            is_injected = False
            with self._injection_lock:
                # Prune expired position targets first so they do not
                # match a coincident user event arriving much later.
                still_valid: list[tuple[int, int, float]] = []
                for px, py, deadline in self._pending_targets:
                    if deadline >= now:
                        still_valid.append((px, py, deadline))
                    else:
                        self._injection_missed += 1
                self._pending_targets = still_valid

                # Position match (preferred).
                for i, (px, py, _deadline) in enumerate(self._pending_targets):
                    if (
                        abs(px - ix) <= self._POSITION_TOLERANCE_PX
                        and abs(py - iy) <= self._POSITION_TOLERANCE_PX
                    ):
                        del self._pending_targets[i]
                        self._injection_tagged_position += 1
                        is_injected = True
                        break

                # Counter fallback (visibility-style untargeted credit).
                if not is_injected:
                    if (
                        self._injection_credits > 0
                        and now < self._injection_deadline
                    ):
                        self._injection_credits -= 1
                        self._injection_tagged_counter += 1
                        is_injected = True
                    elif self._injection_credits > 0:
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

        def _on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> None:
            ix, iy = int(x), int(y)
            now = time.monotonic()
            # Map pynput Button enum to wire-protocol string.
            button_name = _BUTTON_MAP.get(button)
            if button_name is None:
                return
            ev = MouseClickEvent(
                button=button_name,
                pressed=pressed,
                abs_x=ix,
                abs_y=iy,
                is_injected=False,
                ts=now,
            )
            try:
                on_event(ev)  # type: ignore[arg-type]
            except Exception:
                pass

        def _on_scroll(x: float, y: float, sdx: int, sdy: int) -> None:
            ix, iy = int(x), int(y)
            now = time.monotonic()
            ev = MouseScrollEvent(
                dx=int(sdx),
                dy=int(sdy),
                abs_x=ix,
                abs_y=iy,
                is_injected=False,
                ts=now,
            )
            try:
                on_event(ev)  # type: ignore[arg-type]
            except Exception:
                pass

        listener = mouse.Listener(
            on_move=_on_move, on_click=_on_click, on_scroll=_on_scroll,
        )
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
    # Pixel tolerance for position-based injection matching. Accounts for
    # rounding when pynput rounds to integers and Windows clamps cursor
    # positions to monitor bounds.
    _POSITION_TOLERANCE_PX: int = 3

    def register_synthetic_move(self, count: int = 1) -> None:
        """Credit the next ``count`` pynput callbacks as synthetic echoes.

        COUNTER mode: tags the next callback regardless of position. Use
        only when the post-move target coordinate cannot be predicted
        (e.g., SetCursorPos to a virtual-screen coordinate that Windows
        clamps to the visible monitor). Race-prone if combined with
        high-frequency injects — prefer ``register_synthetic_move_to``
        whenever the target is known.
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

    def register_synthetic_move_to(self, x: int, y: int) -> None:
        """POSITION mode: tag the next callback whose pos matches (x, y).

        Robust against high-frequency injects (REMOTE receiving HOST's
        MouseMove stream) because user physical events have unpredictable
        positions that will not match any pending target.
        """
        deadline = time.monotonic() + self._INJECTION_WINDOW_S
        with self._injection_lock:
            self._pending_targets.append((int(x), int(y), deadline))

    def move(self, dx: int, dy: int) -> None:
        """Inject a relative mouse movement (tags the echo as injected).

        Reads the current cursor position to compute the absolute target
        coordinate so that position-based tagging can match the echo
        precisely. Falls back to counter mode if the read fails.
        """
        try:
            cur_x, cur_y = self._controller.position
            target_x = int(cur_x) + int(dx)
            target_y = int(cur_y) + int(dy)
            self.register_synthetic_move_to(target_x, target_y)
        except Exception:  # noqa: BLE001 — defensive
            self.register_synthetic_move()
        self._controller.move(dx, dy)

    def click(self, button: str, pressed: bool) -> None:
        """Inject a mouse button press or release via pynput."""
        btn = _BUTTON_REVERSE.get(button)
        if btn is None:
            return
        if pressed:
            self._controller.press(btn)
        else:
            self._controller.release(btn)

    def scroll(self, dx: int, dy: int) -> None:
        """Inject a mouse scroll event via pynput."""
        self._controller.scroll(dx, dy)

    def move_abs(self, x: int, y: int) -> None:
        """Move the cursor to an absolute screen coordinate (tags echo)."""
        self.register_synthetic_move_to(int(x), int(y))
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
            targets_open:    Position-mode credits queued but not yet
                             consumed (expected synthetic echoes still
                             in flight, position-matched).
            credits_open:    Counter-mode credits queued but not yet
                             consumed (position-agnostic, fallback path).
            tagged_position: Echoes successfully marked is_injected=True
                             via position match (preferred path).
            tagged_counter:  Echoes marked via counter fallback.
            missed:          Credits retired by deadline without a
                             matching callback (pynput coalescing or a
                             position mismatch).
        """
        with self._injection_lock:
            return {
                "targets_open": len(self._pending_targets),
                "credits_open": self._injection_credits,
                "tagged_position": self._injection_tagged_position,
                "tagged_counter": self._injection_tagged_counter,
                "missed": self._injection_missed,
            }
