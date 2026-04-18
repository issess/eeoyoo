"""MouseEventBridge — thread-safe asyncio ↔ capture-thread event forwarder.

# @MX:WARN: [AUTO] submit() is called from the capture thread (pynput OS thread).
# @MX:REASON: Only loop.call_soon_threadsafe() may be used to schedule work
#             onto the event loop from a foreign thread. Calling any asyncio
#             primitive (queue.put, queue.put_nowait, coroutine scheduling)
#             directly from a non-loop thread is undefined behaviour and will
#             cause race conditions or silent deadlocks (plan.md R-09).

strategy.md §2: capture thread posts events via loop.call_soon_threadsafe;
orchestration awaits via bridge.receive().

R-09 drop policy: when queue is full, pop the OLDEST event and push the new
one.  Log a WARNING once per 100 drops to alert without flooding the log.

Usage (in host.py / remote.py):
    bridge = MouseEventBridge(loop=asyncio.get_event_loop(), maxsize=256)
    capture = MouseCapture(backend, lambda ev: bridge.submit(ev))
    ...
    event = await bridge.receive()
"""
from __future__ import annotations

import asyncio
import logging

_logger = logging.getLogger(__name__)

# Log a backpressure warning every N drops to avoid flooding.
_WARN_INTERVAL: int = 100


class MouseEventBridge:
    """Thread-safe forwarder from the capture thread to the asyncio event loop.

    The asyncio.Queue is created and owned by the event loop.  submit() is the
    only method safe to call from another thread; it uses call_soon_threadsafe
    to schedule the enqueue operation on the loop, avoiding any direct crossing
    of the thread-asyncio boundary.

    # @MX:WARN: [AUTO] Backpressure drop on full queue (R-09).
    # @MX:REASON: When the consumer (host.py / remote.py async loop) falls
    #             behind the producer (pynput OS thread), the queue fills up.
    #             Blocking put() would deadlock (plan.md R-09).  We drop the
    #             OLDEST event (dequeue front, enqueue new) to maintain recency.
    #             This is a data-loss policy; the WARNING counter makes it
    #             observable so operators can tune maxsize.

    Args:
        loop: The asyncio event loop that owns the queue.
        maxsize: Maximum number of events buffered before dropping begins.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, maxsize: int = 256) -> None:
        self._loop = loop
        self._maxsize = maxsize
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._drop_count: int = 0

    # ------------------------------------------------------------------
    # Thread-safe producer API
    # ------------------------------------------------------------------

    def submit(self, event: object) -> None:
        """Enqueue *event* from any thread.

        Thread-safe: uses loop.call_soon_threadsafe to schedule the put
        on the event loop.  Never blocks.

        When the queue is full, the oldest event is discarded and a WARNING
        is logged every 100 drops (plan.md R-09).

        If called from the event loop thread itself (e.g. in tests), the
        enqueue runs synchronously via call_soon_threadsafe which is still
        valid (it re-schedules onto the loop's ready queue).

        # @MX:WARN: [AUTO] submit() MUST NOT call any asyncio API directly.
        # @MX:REASON: Calling queue.put_nowait() from a non-loop thread is
        #             a data race. call_soon_threadsafe schedules it safely.
        """
        # call_soon_threadsafe is safe from both the loop thread and foreign
        # threads.  It schedules _enqueue to run on the next loop iteration,
        # which makes drop_count immediately observable after all scheduled
        # callbacks are processed.  We call _enqueue directly here only when
        # we are already on the loop thread (e.g. test code), so that
        # drop_count is visible without awaiting a coroutine.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            # We are on the event loop thread — execute synchronously so that
            # callers can observe drop_count without an extra await.
            self._enqueue(event)
        else:
            self._loop.call_soon_threadsafe(self._enqueue, event)

    # ------------------------------------------------------------------
    # Async consumer API (loop thread only)
    # ------------------------------------------------------------------

    async def receive(self) -> object:
        """Await the next event. Must only be called from the event loop thread.

        Returns:
            The next event in FIFO order (after any drops).
        """
        return await self._queue.get()

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def drop_count(self) -> int:
        """Total number of events dropped due to queue overflow."""
        return self._drop_count

    # ------------------------------------------------------------------
    # Internal helpers (run on the event loop)
    # ------------------------------------------------------------------

    def _enqueue(self, event: object) -> None:
        """Schedule the event into the queue.  Runs on the event loop thread."""
        if self._queue.full():
            # Drop the oldest event (pop front, push new at back).
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._drop_count += 1
            if self._drop_count % _WARN_INTERVAL == 0:
                _logger.warning(
                    "MouseEventBridge: %d events dropped due to queue overflow "
                    "(maxsize=%d). Consumer may be falling behind.",
                    self._drop_count,
                    self._maxsize,
                )
        self._queue.put_nowait(event)
