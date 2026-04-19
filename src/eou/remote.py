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
import sys
import time

from eou.bridge import MouseEventBridge
from eou.input.backend import MouseBackend, MouseEvent
from eou.input.capture import MouseCapture
from eou.input.inject import MouseInjector
from eou.input.visibility import CursorVisibility

# Display-wake helpers are Windows-only. Imported lazily so the module
# remains importable on non-Windows platforms; functions degrade to
# no-ops there.
if sys.platform == "win32":
    from eou.input._display_wake_windows import (  # type: ignore[import]
        allow_display_sleep,
        prevent_display_sleep,
        wake_display_now,
    )
else:  # pragma: no cover — non-Windows fallback
    def prevent_display_sleep() -> bool: return False
    def allow_display_sleep() -> bool: return False
    def wake_display_now() -> bool: return False
from eou.ownership.edge_detector import EdgeConfig, EdgeDetector
from eou.ownership.state import OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector
from eou.protocol.codec import decode, encode
from eou.protocol.messages import (
    Hello,
    MouseClick,
    MouseMove,
    MouseScroll,
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
        # Return-edge detector: while CONTROLLED, if the user pushes the
        # physical cursor against the configured return edge (typically
        # the LEFT edge of the REMOTE screen, mirroring HOST's RIGHT
        # edge), trigger a SESSION_END(reason='edge_return'). This
        # complements the motion-threshold takeback path with the
        # standard KVM "go back to the home machine via the screen edge"
        # gesture. Only physical events (is_injected=False) feed the
        # detector — HOST inject moves do not count.
        self._edge_detector = EdgeDetector(config=self._edge_config)
        self._injector = MouseInjector(backend=self._backend)

        self._capture = MouseCapture(
            backend=self._backend,
            queue=lambda ev: self._bridge.submit(ev),
        )

        # Log FSM transitions for visibility (Remote never manipulates the
        # cursor but state changes are useful for operators tracking
        # ownership transfer during a session).
        self._fsm.subscribe(self._on_state_change)

        # Tell Windows to keep the display awake for the duration of
        # this session. No-op on non-Windows. Released in the finally
        # block below.
        prevent_display_sleep()

        try:
            # Step 1: Handshake — await HOST hello
            _logger.info("Remote: awaiting Hello(role=host) from peer")
            await self._do_handshake()
            _logger.info(
                "Remote: handshake complete; Hello(role=remote, version=%s) sent",
                _VERSION,
            )

            # Start capture
            self._capture.start()
            _logger.info(
                "Remote: mouse capture started (takeback detection armed)"
            )

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
            # Release the display-sleep override so the system can
            # power down the screen normally after the session ends.
            allow_display_sleep()
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

        # Per-CONTROLLED-session counters reset on entry. Surfaced via the
        # 2 s heartbeat below so an operator can see whether physical
        # events are reaching the detector and whether they are being
        # filtered as injected.
        observed_total = 0
        observed_physical = 0
        observed_injected = 0
        last_heartbeat = 0.0
        controlled_session_seen = False
        # Edge proximity bookkeeping (REMOTE return-edge gesture).
        # Tracks whether the cursor is currently inside the configured
        # return-edge band, and whether CROSS_OUT has already fired in
        # this approach so we don't spam SESSION_END frames while the
        # user holds the cursor against the edge waiting for HOST to
        # acknowledge. Reset on proximity exit.
        in_edge_proximity = False
        edge_crossed_in_window = False

        while True:
            try:
                event: object = await self._bridge.receive()
            except Exception:
                break

            if not isinstance(event, MouseEvent):
                continue

            state = self._fsm.state
            if state is not OwnershipState.CONTROLLED:
                # Reset counters when leaving CONTROLLED so the next
                # session starts fresh.
                if controlled_session_seen:
                    _logger.info(
                        "Remote: leaving CONTROLLED (takeback monitor) — "
                        "observed=%d physical=%d injected=%d "
                        "injection_stats=%s",
                        observed_total, observed_physical, observed_injected,
                        self._injection_stats_str(),
                    )
                    observed_total = 0
                    observed_physical = 0
                    observed_injected = 0
                    controlled_session_seen = False
                continue

            if not controlled_session_seen:
                controlled_session_seen = True
                last_heartbeat = time.monotonic()
                _logger.info(
                    "Remote: entering CONTROLLED takeback monitor — "
                    "first event abs=(%d, %d) dx=%d dy=%d injected=%s",
                    event.abs_x, event.abs_y, event.dx, event.dy,
                    event.is_injected,
                )

            observed_total += 1
            if event.is_injected:
                observed_injected += 1
            else:
                observed_physical += 1

            now = time.monotonic()
            if now - last_heartbeat >= 2.0:
                _logger.info(
                    "Remote: takeback monitor stats — observed=%d "
                    "physical=%d injected=%d last_event=(%d,%d) "
                    "dx=%d dy=%d injected_flag=%s injection_stats=%s",
                    observed_total, observed_physical, observed_injected,
                    event.abs_x, event.abs_y, event.dx, event.dy,
                    event.is_injected, self._injection_stats_str(),
                )
                last_heartbeat = now

            # Return-edge detection (physical events only). HOST-injected
            # cursor moves must not look like a takeback gesture, so the
            # is_injected flag gates this entire block.
            if not event.is_injected:
                near = self._edge_detector._within_threshold(
                    event.abs_x, event.abs_y
                )
                if near and not in_edge_proximity:
                    _logger.info(
                        "Remote: cursor entered %s return-edge proximity at "
                        "(%d, %d) (threshold=%dpx bounds=%s) — dwell counting "
                        "started",
                        self._edge_config.edge, event.abs_x, event.abs_y,
                        self._edge_config.threshold_px,
                        self._edge_config.screen_bounds,
                    )
                    in_edge_proximity = True
                    edge_crossed_in_window = False
                elif not near and in_edge_proximity:
                    _logger.info(
                        "Remote: cursor left return-edge proximity at "
                        "(%d, %d) — dwell reset",
                        event.abs_x, event.abs_y,
                    )
                    in_edge_proximity = False
                    edge_crossed_in_window = False

                if near and not edge_crossed_in_window:
                    edge_event = self._edge_detector.observe(
                        event.abs_x, event.abs_y
                    )
                    if edge_event is not None:
                        edge_crossed_in_window = True
                        _logger.info(
                            "Remote: return-edge crossed (%s) at (%d, %d); "
                            "sending SESSION_END(reason=edge_return)",
                            edge_event.name, event.abs_x, event.abs_y,
                        )
                        self._fsm.on_local_input_detected()
                        try:
                            await self._transport.send(
                                encode(SessionEnd(
                                    reason="edge_return",
                                    ts=time.monotonic(),
                                ))
                            )
                        except ConnectionClosedError:
                            pass
                        # Skip motion-takeback for this same event so we
                        # don't double-fire SESSION_END.
                        continue

            triggered = self._takeback_detector.observe(
                dx=event.dx,
                dy=event.dy,
                is_injected=event.is_injected,
            )
            if triggered:
                _logger.info(
                    "Remote: takeback triggered after observed=%d "
                    "physical=%d injected=%d; sending SESSION_END",
                    observed_total, observed_physical, observed_injected,
                )
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

        frame_count = 0
        move_count = 0
        last_heartbeat = 0.0

        while True:
            try:
                raw = await self._transport.recv()
            except ConnectionClosedError as exc:
                _logger.info(
                    "Remote: transport disconnected (%s); exiting inbound loop",
                    exc,
                )
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break
            except Exception as exc:
                _logger.warning(
                    "Remote: inbound error: %r; exiting inbound loop",
                    exc, exc_info=True,
                )
                if self._fsm.state is not OwnershipState.IDLE:
                    self._fsm.on_session_end(reason="transport_disconnect")
                break

            frame_count += 1
            try:
                msg = decode(raw)
            except Exception as exc:
                _logger.warning(
                    "Remote: decode error (frame %d discarded): %s",
                    frame_count, exc,
                )
                continue

            if isinstance(msg, MouseMove):
                move_count += 1
                now = time.monotonic()
                if now - last_heartbeat > 1.0:
                    _logger.info(
                        "Remote: inbound heartbeat frames=%d moves=%d state=%s "
                        "last_delta=(%d,%d)",
                        frame_count, move_count, self._fsm.state.name,
                        msg.dx, msg.dy,
                    )
                    last_heartbeat = now
            else:
                _logger.info(
                    "Remote: inbound %s received (state=%s)",
                    type(msg).__name__, self._fsm.state.name,
                )

            await self._dispatch_inbound(msg)

    async def _dispatch_inbound(self, msg: object) -> None:
        """Dispatch a decoded inbound message."""
        assert self._fsm is not None
        assert self._injector is not None

        if isinstance(msg, OwnershipRequest):
            if self._fsm.state is OwnershipState.IDLE:
                _logger.info(
                    "Remote: OwnershipRequest accepted; sending OwnershipGrant"
                )
                self._fsm.on_ownership_request_received()
                self._fsm.on_grant_sent()
                try:
                    await self._transport.send(
                        encode(OwnershipGrant(ts=time.monotonic()))
                    )
                except ConnectionClosedError:
                    _logger.warning(
                        "Remote: failed to send OwnershipGrant — connection closed"
                    )
            else:
                _logger.info(
                    "Remote: OwnershipRequest ignored in state %s",
                    self._fsm.state.name,
                )

        elif isinstance(msg, MouseMove):
            if self._fsm.state is OwnershipState.CONTROLLED:
                try:
                    self._injector.inject_move(dx=msg.dx, dy=msg.dy)
                except Exception as exc:
                    _logger.warning("Remote: inject_move error: %s", exc)

        elif isinstance(msg, MouseClick):
            if self._fsm.state is OwnershipState.CONTROLLED:
                try:
                    self._injector.inject_click(
                        button=msg.button, pressed=msg.pressed
                    )
                except Exception as exc:
                    _logger.warning("Remote: inject_click error: %s", exc)

        elif isinstance(msg, MouseScroll):
            if self._fsm.state is OwnershipState.CONTROLLED:
                try:
                    self._injector.inject_scroll(dx=msg.dx, dy=msg.dy)
                except Exception as exc:
                    _logger.warning("Remote: inject_scroll error: %s", exc)

        elif isinstance(msg, SessionEnd):
            if self._fsm.state is not OwnershipState.IDLE:
                _logger.info(
                    "Remote: SessionEnd received (reason=%s); returning to IDLE",
                    msg.reason,
                )
                self._fsm.on_session_end(reason=msg.reason)

    # ------------------------------------------------------------------
    # Internal: FSM state change callback (logging only)
    # ------------------------------------------------------------------

    def _on_state_change(
        self,
        old_state: OwnershipState,
        new_state: OwnershipState,
    ) -> None:
        """Log FSM transitions and wake the display on CONTROLLED entry.

        Remote never manipulates cursor visibility, but it does need to
        wake the screen when HOST first takes control — otherwise the
        operator cannot see the injected cursor on a blanked monitor.
        """
        _logger.info(
            "Remote: FSM state change %s -> %s",
            old_state.name, new_state.name,
        )
        if (
            old_state is OwnershipState.IDLE
            and new_state is OwnershipState.CONTROLLED
        ):
            wake_display_now()

    def _injection_stats_str(self) -> str:
        """Compact one-line backend injection-tagging counters.

        Returns "n/a" if the backend does not expose injection_stats
        (e.g., test fakes) or "error" if the call raises.
        """
        getter = getattr(self._backend, "injection_stats", None)
        if getter is None:
            return "n/a"
        try:
            stats = getter()
        except Exception:  # noqa: BLE001 — diagnostic only
            return "error"
        if isinstance(stats, dict):
            return " ".join(f"{k}={v}" for k, v in stats.items())
        return str(stats)
