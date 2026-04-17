"""MouseCapture — thin bridge between MouseBackend and the event queue.

# @MX:WARN: [AUTO] MouseCapture may be driven from a separate OS thread.
# @MX:REASON: When used with the production PynputMouseBackend the callback
#             is invoked on pynput's dedicated listener thread, not the asyncio
#             event loop thread.  If queue is an asyncio.Queue, callers MUST
#             use loop.call_soon_threadsafe(queue.put_nowait, event) instead of
#             calling queue.put_nowait() directly.  Using FakeMouseBackend in
#             tests avoids this concern entirely.

REQ-MOUSE-TAKEBACK-003: is_injected flag on MouseEvent is forwarded unchanged.
"""
from __future__ import annotations

from collections.abc import Callable

from eou.input.backend import MouseBackend, MouseEvent


class MouseCapture:
    """Forwards OS mouse events from a MouseBackend to a queue callable.

    Args:
        backend: The OS abstraction layer for mouse capture.
        queue: A callable that accepts a MouseEvent.  In production this is
            typically ``loop.call_soon_threadsafe(asyncio_queue.put_nowait, event)``
            bound at construction time.  In unit tests it is a plain list.append.
    """

    def __init__(
        self,
        backend: MouseBackend,
        queue: Callable[[MouseEvent], None],
    ) -> None:
        self._backend = backend
        self._queue = queue
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin capturing OS mouse events. Idempotent."""
        if self._started:
            return
        self._started = True
        self._backend.start_capture(self._on_event)

    def stop(self) -> None:
        """Stop capturing. Idempotent; safe to call before start()."""
        if not self._started:
            return
        self._started = False
        self._backend.stop_capture()

    # ------------------------------------------------------------------
    # Internal callback
    # ------------------------------------------------------------------

    def _on_event(self, event: MouseEvent) -> None:
        """Forward event to the queue. Called by the backend."""
        self._queue(event)
