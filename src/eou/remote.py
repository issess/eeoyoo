"""Remote orchestration for SPEC-MOUSE-001.

Wires Transport + MouseBackend + MouseInjector + OwnershipFSM +
TakebackDetector + MouseCapture + MouseEventBridge into the REMOTE async run loop.

Design (strategy.md §2):
- Task A: drain bridge.receive() → TakebackDetector → if triggered, send
          SESSION_END(reason='takeback') and FSM → IDLE.
- Task B: await transport.recv() → decode → dispatch:
    * OwnershipRequest → send OwnershipGrant, FSM → CONTROLLED.
    * MouseMove → MouseInjector.inject_move() (injected tag set by backend).
    * SessionEnd → FSM → IDLE.
- Remote MUST NOT call visibility.hide() or visibility.show() ever
  (REQ-MOUSE-VISIBILITY-004).

# @MX:ANCHOR: [AUTO] Remote.run — top-level REMOTE orchestration entry point.
# @MX:REASON: cli.py calls asyncio.run(Remote(...).run()); E2E loopback tests
#             wrap this coroutine in asyncio.gather. fan_in >= 2.
#             Changing the run() contract breaks cli.py and E2E tests.
"""
from __future__ import annotations

import asyncio
import logging
import time

from eou.bridge import MouseEventBridge
from eou.input.backend import MouseBackend, MouseEvent
from eou.input.capture import MouseCapture
from eou.input.inject import MouseInjector
from eou.input.visibility import CursorVisibility
from eou.ownership.edge_detector import EdgeConfig
from eou.ownership.state import OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector
from eou.protocol.codec import decode, encode
from eou.protocol.messages import (
    Hello,
    MouseMove,
    OwnershipGrant,
    OwnershipRequest,
    SessionEnd,
)
from eou.transport.base import ConnectionClosedError, Transport

_logger = logging.getLogger(__name__)

_VERSION = "0.1.0"


class Remote:
    """Async REMOTE orchestrator.

    Args:
        transport: Connected or connectable Transport instance.
        backend: OS mouse backend (real or fake for tests).
        visibility: CursorVisibility instance — Remote MUST NOT call hide/show.
            Kept as a parameter for DI completeness; Remote ignores it.
        edge_config: Kept for DI completeness; Remote uses return-edge detection
            if needed. In current MVP, edge detection on REMOTE is not wired
            (Host drives CONTROLLING state via messages).
        takeback_config: Takeback detection parameters.
    """

    def __init__(
        self,
        transport: Transport,
        backend: MouseBackend,
        visibility: CursorVisibility,
        edge_config: EdgeConfig,
        takeback_config: TakebackConfig,
    ) -> None:
        self._transport = transport
        self._backend = backend
        self._visibility = visibility  # stored but NOT called (REQ-MOUSE-VISIBILITY-004)
        self._edge_config = edge_config
        self._takeback_config = takeback_config

        self._fsm: OwnershipFSM | None = None
        self._bridge: MouseEventBridge | None = None
        self._capture: MouseCapture | None = None
        self._injector: MouseInjector | None = None
        self._takeback_detector: TakebackDetector | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # @MX:ANCHOR: [AUTO] Remote.run — REMOTE async entry point.
    # @MX:REASON: cli.py calls asyncio.run(remote.run()); E2E tests wrap in
    #             asyncio.gather. fan_in >= 2. Changing this contract breaks
    #             the entire REMOTE-side wiring.
    async def run(self) -> None:
        """Start the REMOTE event loop.

        1. Await Hello(role='host') from peer.
        2. Send Hello(role='remote').
        3. Start capture → bridge.
        4. Run task A (takeback monitor) and task B (inbound dispatcher).
        5. On exit: stop capture, close transport.
        """
        loop = asyncio.get_event_loop()

        self._fsm = OwnershipFSM()
        self._bridge = MouseEventBridge(loop=loop, maxsize=256)
        self._takeback_detector = TakebackDetector(config=self._takeback_config)
        self._injector = MouseInjector(backend=self._backend)

        self._capture = MouseCapture(
            backend=self._backend,
            queue=lambda ev: self._bridge.submit(ev),
        )

        try:
            # Step 1: Handshake — await HOST hello
            await self._do_handshake()

            # Start capture
            self._capture.start()

            # Step 2: Concurrent tasks
            task_a = asyncio.create_task(self._takeback_loop())
            task_b = asyncio.create_task(self._inbound_loop())

            done, pending = await asyncio.wait(
                [task_a, task_b],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        except (ConnectionClosedError, asyncio.CancelledError):
            pass
        except Exception as exc:
            _logger.warning(
                "Remote.run: unexpected error: %s: %r",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
        finally:
            if self._capture:
                self._capture.stop()
            if self._fsm and self._fsm.state is not OwnershipState.IDLE:
                self._fsm.on_session_end(reason="shutdown")
            await self._transport.close()

    # ------------------------------------------------------------------
    # Internal: handshake
    # ------------------------------------------------------------------

    async def _do_handshake(self) -> None:
        """Await Hello from host; reply Hello(role='remote')."""
        raw = await asyncio.wait_for(self._transport.recv(), timeout=10.0)
        msg = decode(raw)
        if not isinstance(msg, Hello):
            raise ConnectionError(f"Expected Hello, got {type(msg).__name__}")
        if msg.role != "host":
            raise ConnectionError(f"Expected role='host', got {msg.role!r}")
        await self._transport.send(encode(Hello(version=_VERSION, role="remote")))

    # ------------------------------------------------------------------
    # Internal: Task A — takeback monitor
    # ------------------------------------------------------------------

    async def _takeback_loop(self) -> None:
        """Drain capture events; detect takeback while CONTROLLED.

        # @MX:WARN: [AUTO] Backpressure drop on full capture queue (R-09).
        # @MX:REASON: If Remote's consumer loop is slow, the bridge will start
        #             dropping oldest events. This means some physical mouse events
        #             may be lost before they reach TakebackDetector. If enough
        #             events are dropped, a real takeback gesture could be missed.
        #             Monitor bridge.drop_count in production logs.
        """
        assert self._bridge is not None
        assert self._fsm is not None
        assert self._takeback_detector is not None

        while True:
            try:
                event: object = await self._bridge.receive()
            except Exception:
                break

            if not isinstance(event, MouseEvent):
                continue

            state = self._fsm.state
            if state is not OwnershipState.CONTROLLED:
                continue

            triggered = self._takeback_detector.observe(
                dx=event.dx,
                dy=event.dy,
                is_injected=event.is_injected,
            )
            if triggered:
                _logger.info("Remote: takeback triggered, sending SESSION_END")
                self._fsm.on_local_input_detected()
                try:
                    await self._transport.send(
                        encode(SessionEnd(reason="takeback", ts=time.monotonic()))
                    )
                except ConnectionClosedError:
                    pass

    # ------------------------------------------------------------------
    # Internal: Task B — inbound dispatcher
    # ------------------------------------------------------------------

    async def _inbound_loop(self) -> None:
        """Read frames from transport; dispatch OwnershipRequest and MouseMove."""
        assert self._fsm is not None
        assert self._injector is not None

        while True:
            try:
                raw = await self._transport.recv()
            except ConnectionClosedError:
                _logger.info("Remote: transport disconnected")
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break
            except Exception as exc:
                _logger.warning("Remote: inbound error: %s", exc)
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break

            try:
                msg = decode(raw)
            except Exception as exc:
                _logger.warning("Remote: decode error (frame discarded): %s", exc)
                continue

            await self._dispatch_inbound(msg)

    async def _dispatch_inbound(self, msg: object) -> None:
        """Dispatch a decoded inbound message."""
        assert self._fsm is not None
        assert self._injector is not None

        if isinstance(msg, OwnershipRequest):
            if self._fsm.state is OwnershipState.IDLE:
                self._fsm.on_ownership_request_received()
                self._fsm.on_grant_sent()
                try:
                    await self._transport.send(
                        encode(OwnershipGrant(ts=time.monotonic()))
                    )
                except ConnectionClosedError:
                    pass

        elif isinstance(msg, MouseMove):
            if self._fsm.state is OwnershipState.CONTROLLED:
                try:
                    self._injector.inject_move(dx=msg.dx, dy=msg.dy)
                except Exception as exc:
                    _logger.warning("Remote: inject_move error: %s", exc)

        elif isinstance(msg, SessionEnd):
            if self._fsm.state is not OwnershipState.IDLE:
                self._fsm.on_session_end(reason=msg.reason)
