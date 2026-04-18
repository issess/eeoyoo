"""Host orchestration for SPEC-MOUSE-001.

Wires Transport + MouseBackend + CursorVisibility + EdgeDetector +
OwnershipFSM + MouseCapture + MouseEventBridge into the HOST async run loop.

Design (strategy.md §2):
- MouseCapture runs on the OS (pynput) thread; events bridge to asyncio via
  MouseEventBridge.
- Two concurrent asyncio tasks:
    Task A: drain bridge.receive() → EdgeDetector → FSM → send outgoing messages;
            while CONTROLLING, also send MouseMove frames.
    Task B: await transport.recv() → decode → dispatch inbound messages.
- On CONTROLLING entry: call visibility.hide(pre_hide_position).
- On CONTROLLING exit (any cause): call visibility.show().
- On transport disconnect: force FSM to IDLE, call visibility.show().

# @MX:ANCHOR: [AUTO] Host.run — top-level HOST orchestration entry point.
# @MX:REASON: This coroutine is the composition root for the HOST side.
#             cli.py calls asyncio.run(Host(...).run()). All HOST-side
#             side-effects (send, hide, show) are driven from here.
#             Changing the run() contract breaks cli.py and E2E tests.

# @MX:NOTE: [AUTO] Handshake sequencing: Hello exchange precedes main loop.
# @MX:REASON: Both nodes must know each other's role before the first
#             mouse event can be processed. If the main loop starts before
#             HELLO is received, edge events could trigger OwnershipRequest
#             to a peer that hasn't initialised its FSM yet, causing a
#             protocol race (REQ-MOUSE-PROTOCOL-002).
"""
from __future__ import annotations

import asyncio
import logging
import time

from eou.bridge import MouseEventBridge
from eou.input.backend import MouseBackend, MouseEvent
from eou.input.capture import MouseCapture
from eou.input.visibility import CursorVisibility
from eou.ownership.edge_detector import EdgeConfig, EdgeDetector
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


class Host:
    """Async HOST orchestrator.

    Args:
        transport: Connected or connectable Transport instance.
        backend: OS mouse backend (real or fake for tests).
        visibility: CursorVisibility implementation (real or fake).
        edge_config: Edge detection parameters.
        takeback_config: Takeback detection parameters (for completeness;
            HOST does not process takeback but reuses TakebackConfig type).
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
        self._visibility = visibility
        self._edge_config = edge_config
        self._takeback_config = takeback_config

        # Lazily initialised in run()
        self._fsm: OwnershipFSM | None = None
        self._bridge: MouseEventBridge | None = None
        self._capture: MouseCapture | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # @MX:ANCHOR: [AUTO] run — HOST async entry point.
    # @MX:REASON: cli.py calls asyncio.run(host.run()); E2E loopback tests
    #             wrap this coroutine in asyncio.gather. fan_in >= 2.
    async def run(self) -> None:
        """Start the HOST event loop.

        1. Send Hello(role='host').
        2. Await Hello(role='remote') from peer.
        3. Start capture → bridge.
        4. Run task A (outbound) and task B (inbound) concurrently.
        5. On exit: stop capture, show cursor, close transport.
        """
        loop = asyncio.get_event_loop()

        # Initialise sub-components
        self._fsm = OwnershipFSM()
        self._bridge = MouseEventBridge(loop=loop, maxsize=256)
        self._edge_detector = EdgeDetector(config=self._edge_config)

        # Capture feeds the bridge
        self._capture = MouseCapture(
            backend=self._backend,
            queue=lambda ev: self._bridge.submit(ev),
        )

        # Subscribe to FSM transitions for visibility management
        self._fsm.subscribe(self._on_state_change)

        try:
            # Step 1: Handshake
            await self._transport.send(encode(Hello(version=_VERSION, role="host")))
            await self._do_handshake()

            # Start capture
            self._capture.start()

            # Step 2: Concurrent tasks
            task_a = asyncio.create_task(self._outbound_loop())
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
            _logger.warning("Host.run: unexpected error: %s", exc)
        finally:
            if self._capture:
                self._capture.stop()
            # Ensure cursor is restored on any exit
            if self._fsm and self._fsm.state is not OwnershipState.IDLE:
                self._fsm.on_session_end(reason="shutdown")
            await self._transport.close()

    # ------------------------------------------------------------------
    # Internal: handshake
    # ------------------------------------------------------------------

    async def _do_handshake(self) -> None:
        """Await HELLO from remote; raise on timeout or wrong role."""
        raw = await asyncio.wait_for(self._transport.recv(), timeout=10.0)
        msg = decode(raw)
        if not isinstance(msg, Hello):
            raise ConnectionError(f"Expected Hello, got {type(msg).__name__}")
        if msg.role != "remote":
            raise ConnectionError(f"Expected role='remote', got {msg.role!r}")

    # ------------------------------------------------------------------
    # Internal: outbound loop (Task A)
    # ------------------------------------------------------------------

    async def _outbound_loop(self) -> None:
        """Drain bridge events; drive edge detection and send outgoing messages."""
        assert self._bridge is not None
        assert self._fsm is not None

        while True:
            try:
                event: object = await self._bridge.receive()
            except Exception:
                break

            if not isinstance(event, MouseEvent):
                continue

            state = self._fsm.state

            if state is OwnershipState.IDLE:
                edge_event = self._edge_detector.observe(event.abs_x, event.abs_y)
                if edge_event is not None:
                    # Edge cross-out: send OwnershipRequest
                    self._fsm.on_edge_cross_out()
                    await self._transport.send(
                        encode(OwnershipRequest(ts=time.monotonic()))
                    )

            elif state is OwnershipState.CONTROLLING:
                # Forward mouse movement to REMOTE
                if event.dx != 0 or event.dy != 0:
                    await self._transport.send(
                        encode(
                            MouseMove(
                                dx=event.dx,
                                dy=event.dy,
                                abs_x=event.abs_x,
                                abs_y=event.abs_y,
                                ts=event.ts,
                            )
                        )
                    )

    # ------------------------------------------------------------------
    # Internal: inbound loop (Task B)
    # ------------------------------------------------------------------

    async def _inbound_loop(self) -> None:
        """Read frames from transport; process OwnershipGrant and SessionEnd."""
        assert self._fsm is not None

        while True:
            try:
                raw = await self._transport.recv()
            except ConnectionClosedError:
                # Transport disconnect — force IDLE
                _logger.info("Host: transport disconnected, forcing IDLE")
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break
            except Exception as exc:
                _logger.warning("Host: inbound error: %s", exc)
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break

            try:
                msg = decode(raw)
            except Exception as exc:
                _logger.warning("Host: decode error (frame discarded): %s", exc)
                continue

            await self._dispatch_inbound(msg)

    async def _dispatch_inbound(self, msg: object) -> None:
        """Dispatch a decoded inbound message."""
        assert self._fsm is not None

        if isinstance(msg, OwnershipGrant):
            try:
                self._fsm.on_ownership_granted()
            except Exception as exc:
                _logger.warning("Host: unexpected OwnershipGrant in state %s: %s",
                                self._fsm.state, exc)
                await self._transport.send(
                    encode(SessionEnd(reason="shutdown", ts=time.monotonic()))
                )

        elif isinstance(msg, SessionEnd):
            if self._fsm.state is not OwnershipState.IDLE:
                self._fsm.on_session_end(reason=msg.reason)

    # ------------------------------------------------------------------
    # Internal: FSM state change callback
    # ------------------------------------------------------------------

    def _on_state_change(
        self,
        old_state: OwnershipState,
        new_state: OwnershipState,
    ) -> None:
        """React to FSM transitions: hide/show cursor."""
        if old_state is OwnershipState.IDLE and new_state is OwnershipState.CONTROLLING:
            # Capture current position before hiding
            pos = self._backend.get_position()
            self._visibility.hide(pre_hide_position=pos)

        elif old_state is OwnershipState.CONTROLLING and new_state is OwnershipState.IDLE:
            self._visibility.show()
