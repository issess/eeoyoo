"""OwnershipCoordinator — thin sync orchestrator wiring FSM + EdgeDetector + TakebackDetector.

Wires the three pure-sync primitives from Slice 2 into a single on_mouse_event()
entry point. No asyncio, no I/O, no threading.

Slice 4 (host.py / remote.py) will adapt this sync core into an async event loop.

Design:
- on_mouse_event() is called for every captured or injected mouse event.
- EdgeDetector.observe() is called with absolute cursor coordinates.
- TakebackDetector.observe() is called with relative deltas.
- When IDLE + edge cross-out → call FSM.on_edge_cross_out() + return OwnershipRequest.
- When CONTROLLED + takeback signal → call FSM.on_local_input_detected() + return SessionEnd.
"""

from __future__ import annotations

from collections.abc import Callable

from eou.ownership.edge_detector import EdgeDetector, EdgeEvent
from eou.ownership.state import OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackDetector
from eou.protocol.messages import AnyMessage


class OwnershipCoordinator:
    """Thin sync orchestrator.

    Connects FSM, EdgeDetector, and TakebackDetector into a single
    on_mouse_event() call that returns an outgoing message or None.

    The message_builder callable constructs protocol messages on demand.
    Accepted message type strings: "OWNERSHIP_REQUEST", "SESSION_END_TAKEBACK".
    """

    def __init__(
        self,
        fsm: OwnershipFSM,
        edge_detector: EdgeDetector,
        takeback_detector: TakebackDetector,
        message_builder: Callable[[str], AnyMessage],
    ) -> None:
        self._fsm = fsm
        self._edge_detector = edge_detector
        self._takeback_detector = takeback_detector
        self._message_builder = message_builder

    def on_mouse_event(
        self,
        x: int,
        y: int,
        dx: int,
        dy: int,
        is_injected: bool,
    ) -> AnyMessage | None:
        """Process one mouse event and return an outgoing message if applicable.

        Args:
            x: Absolute cursor x-coordinate (for edge detection).
            y: Absolute cursor y-coordinate (for edge detection).
            dx: Relative x delta (for takeback detection).
            dy: Relative y delta (for takeback detection).
            is_injected: True if this event was produced by a MOUSE_MOVE injection.

        Returns:
            OwnershipRequest when edge dwell is satisfied from IDLE state.
            SessionEnd(reason='takeback') when physical input triggers takeback from CONTROLLED.
            None otherwise.
        """
        state = self._fsm.state

        # IDLE: check for edge cross-out
        if state is OwnershipState.IDLE:
            edge_event = self._edge_detector.observe(x, y)
            if edge_event is EdgeEvent.CROSS_OUT:
                self._fsm.on_edge_cross_out()
                return self._message_builder("OWNERSHIP_REQUEST")
            return None

        # CONTROLLED: check for takeback (physical events only)
        if state is OwnershipState.CONTROLLED:
            triggered = self._takeback_detector.observe(dx=dx, dy=dy, is_injected=is_injected)
            if triggered:
                self._fsm.on_local_input_detected()
                return self._message_builder("SESSION_END_TAKEBACK")
            return None

        # CONTROLLING: mouse events are forwarded by the async layer (Slice 4).
        # The coordinator does not act on them in the sync domain.
        return None
