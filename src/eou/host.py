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
from eou.ownership.takeback_detector import TakebackConfig
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
            _logger.info("Host: sending Hello(role=host, version=%s)", _VERSION)
            await self._transport.send(encode(Hello(version=_VERSION, role="host")))
            await self._do_handshake()
            _logger.info("Host: handshake complete; peer is REMOTE")

            # Start capture
            self._capture.start()
            _logger.info(
                "Host: mouse capture started (edge=%s screen_bounds=%s "
                "threshold_px=%d dwell_ticks=%d)",
                self._edge_config.edge, self._edge_config.screen_bounds,
                self._edge_config.threshold_px, self._edge_config.dwell_ticks,
            )

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
            _logger.warning(
                "Host.run: unexpected error: %s: %r",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
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

        event_count = 0
        debug_events = _logger.isEnabledFor(logging.DEBUG)
        # Tracks whether the cursor is currently inside the edge proximity
        # band so we can log enter/leave transitions exactly once.
        in_edge_proximity = False
        # Idle-position logging: emit one INFO line per stable position
        # (no mouse events observed for >= 1 s). Suppresses motion spam.
        last_pos: tuple[int, int] | None = None
        idle_logged: bool = False
        # Per-CONTROLLING-session counters (reset on IDLE -> CONTROLLING).
        controlling_event_count = 0
        controlling_move_frames_sent = 0
        controlling_zero_delta_skipped = 0
        # Last state we observed on the FSM; used to detect entry into
        # CONTROLLING so we can reset counters and emit a state banner.
        observed_state: OwnershipState = OwnershipState.IDLE
        controlling_last_summary = 0.0

        while True:
            try:
                event: object = await asyncio.wait_for(
                    self._bridge.receive(), timeout=1.0
                )
            except asyncio.TimeoutError:
                if last_pos is not None and not idle_logged:
                    _logger.info(
                        "Host: cursor idle 1s at pos=(%d, %d) state=%s "
                        "dwell=%d/%d",
                        last_pos[0], last_pos[1],
                        self._fsm.state.name,
                        self._edge_detector._dwell_count,
                        self._edge_config.dwell_ticks,
                    )
                    idle_logged = True
                # While CONTROLLING, emit a periodic diagnostic so the
                # operator can tell whether the event pipeline is alive.
                now = time.monotonic()
                if (
                    self._fsm.state is OwnershipState.CONTROLLING
                    and now - controlling_last_summary >= 2.0
                ):
                    hook_stats = self._get_visibility_hook_stats()
                    pynput_count = self._get_pynput_event_count()
                    _logger.info(
                        "Host: CONTROLLING pipeline stats — "
                        "outbound_received=%d frames_sent=%d "
                        "skipped_zero_delta=%d pynput_events=%s "
                        "hook=%s",
                        controlling_event_count,
                        controlling_move_frames_sent,
                        controlling_zero_delta_skipped,
                        pynput_count,
                        hook_stats,
                    )
                    controlling_last_summary = now
                continue
            except Exception:
                _logger.debug(
                    "Host: bridge.receive raised; outbound loop exiting",
                    exc_info=True,
                )
                break

            if not isinstance(event, MouseEvent):
                continue

            event_count += 1
            if event_count == 1:
                _logger.info(
                    "Host: first mouse event received at (%d, %d); "
                    "edge_detector is now observing",
                    event.abs_x, event.abs_y,
                )

            new_pos = (event.abs_x, event.abs_y)
            if new_pos != last_pos:
                idle_logged = False
            last_pos = new_pos

            state = self._fsm.state

            # Detect FSM state change since our last observed event, so we
            # can reset per-session counters and log an entry banner.
            if state is not observed_state:
                if state is OwnershipState.CONTROLLING:
                    controlling_event_count = 0
                    controlling_move_frames_sent = 0
                    controlling_zero_delta_skipped = 0
                    controlling_last_summary = time.monotonic()
                    _logger.info(
                        "Host: entering CONTROLLING event loop — "
                        "will forward MouseMove frames until state leaves "
                        "CONTROLLING"
                    )
                elif observed_state is OwnershipState.CONTROLLING:
                    _logger.info(
                        "Host: leaving CONTROLLING — received=%d sent=%d "
                        "skipped_zero_delta=%d",
                        controlling_event_count,
                        controlling_move_frames_sent,
                        controlling_zero_delta_skipped,
                    )
                observed_state = state

            if state is OwnershipState.IDLE:
                near = self._edge_detector._within_threshold(
                    event.abs_x, event.abs_y
                )
                if near and not in_edge_proximity:
                    _logger.info(
                        "Host: mouse entered %s edge proximity at (%d, %d) "
                        "(threshold=%dpx bounds=%s) — dwell counting started",
                        self._edge_config.edge, event.abs_x, event.abs_y,
                        self._edge_config.threshold_px,
                        self._edge_config.screen_bounds,
                    )
                    in_edge_proximity = True
                elif not near and in_edge_proximity:
                    _logger.info(
                        "Host: mouse left edge proximity at (%d, %d) — "
                        "dwell reset",
                        event.abs_x, event.abs_y,
                    )
                    in_edge_proximity = False

                edge_event = self._edge_detector.observe(event.abs_x, event.abs_y)
                if edge_event is not None:
                    in_edge_proximity = False  # detector resets internal dwell
                    if self._fsm.pending_grant:
                        # A prior OwnershipRequest is still awaiting Grant.
                        # Resending would duplicate on the wire and race
                        # the REMOTE's FSM (see REMOTE "ignored" logs).
                        _logger.info(
                            "Host: edge crossed (%s) at (%d, %d) while "
                            "waiting for Grant — suppressing duplicate "
                            "OwnershipRequest",
                            edge_event.name, event.abs_x, event.abs_y,
                        )
                    else:
                        _logger.info(
                            "Host: edge crossed (%s) at (%d, %d); sending "
                            "OwnershipRequest",
                            edge_event.name, event.abs_x, event.abs_y,
                        )
                        self._fsm.on_edge_cross_out()
                        await self._transport.send(
                            encode(OwnershipRequest(ts=time.monotonic()))
                        )
                elif debug_events:
                    _logger.debug(
                        "Host: IDLE tick pos=(%d, %d) dwell=%d/%d near=%s",
                        event.abs_x, event.abs_y,
                        self._edge_detector._dwell_count,
                        self._edge_config.dwell_ticks, near,
                    )

            elif state is OwnershipState.CONTROLLING:
                controlling_event_count += 1
                if controlling_event_count == 1:
                    _logger.info(
                        "Host: first CONTROLLING event received at "
                        "(%d, %d) dx=%d dy=%d — pipeline is live",
                        event.abs_x, event.abs_y, event.dx, event.dy,
                    )
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
                    controlling_move_frames_sent += 1
                else:
                    controlling_zero_delta_skipped += 1

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
        _logger.info(
            "Host: FSM state change %s -> %s", old_state.name, new_state.name
        )
        if old_state is OwnershipState.IDLE and new_state is OwnershipState.CONTROLLING:
            # Capture current position before hiding
            pos = self._backend.get_position()
            # The visibility hook consumes WH_MOUSE_LL events, so pynput no
            # longer receives them. Register a hook-thread callback so the
            # hook itself becomes the MouseEvent source for the outbound
            # loop during CONTROLLING.
            self._visibility.hide(
                pre_hide_position=pos,
                on_mouse_event=self._forward_hook_event,
            )

        elif old_state is OwnershipState.CONTROLLING and new_state is OwnershipState.IDLE:
            self._visibility.show()

    # ------------------------------------------------------------------
    # Internal: WH_MOUSE_LL hook-thread callback (Windows only)
    # ------------------------------------------------------------------

    def _forward_hook_event(
        self, dx: int, dy: int, abs_x: int, abs_y: int
    ) -> None:
        """Bridge a mouse event observed on the OS hook thread to asyncio.

        Invoked from the WH_MOUSE_LL hook thread while the visibility
        layer is hiding the cursor. ``bridge.submit`` is thread-safe via
        ``loop.call_soon_threadsafe``, so this call does not cross the
        thread/asyncio boundary directly.
        """
        if self._bridge is None:
            return
        self._bridge.submit(
            MouseEvent(
                dx=dx,
                dy=dy,
                abs_x=abs_x,
                abs_y=abs_y,
                is_injected=False,
                ts=time.monotonic(),
            )
        )

    def _get_pynput_event_count(self) -> str:
        """Return the cumulative event count from the pynput backend, if any."""
        getter = getattr(self._backend, "event_count", None)
        if getter is None:
            return "n/a"
        try:
            return str(getter())
        except Exception:  # noqa: BLE001 — diagnostic only
            return "error"

    def _get_visibility_hook_stats(self) -> str:
        """Return a compact one-line string with visibility hook counters.

        Tolerates backends that do not expose hook stats (NullCursorVisibility,
        FakeCursorVisibility, non-Windows) by falling back to "n/a".
        """
        getter = getattr(self._visibility, "get_hook_stats", None)
        if getter is None:
            return "n/a"
        try:
            stats = getter()
        except Exception:  # noqa: BLE001 — diagnostic only
            return "error"
        if isinstance(stats, dict):
            return " ".join(f"{k}={v}" for k, v in stats.items())
        return str(stats)
