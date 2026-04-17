"""Tests for OwnershipCoordinator (T-018 — pure sync wiring unit test).

Tests the thin synchronous orchestrator that wires FSM + EdgeDetector +
TakebackDetector. Uses fakes for all inner primitives; no real I/O.

This coordinator is the sync core that Slice 4 will adapt with asyncio.
"""

from __future__ import annotations

from eou.ownership.coordinator import OwnershipCoordinator
from eou.ownership.edge_detector import EdgeConfig, EdgeDetector
from eou.ownership.state import OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector
from eou.protocol.messages import AnyMessage, OwnershipRequest, SessionEnd

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self._t = t

    def __call__(self) -> float:
        return self._t

    def advance(self, ms: float) -> None:
        self._t += ms / 1000.0


def make_coordinator() -> tuple[
    OwnershipCoordinator,
    OwnershipFSM,
    EdgeDetector,
    TakebackDetector,
    FakeClock,
    list[AnyMessage],
]:
    """Build a wired coordinator with fresh fakes. Returns all parts for inspection."""
    fsm = OwnershipFSM()
    edge_cfg = EdgeConfig(
        edge="right",
        threshold_px=2,
        dwell_ticks=2,
        screen_bounds=(0, 0, 1919, 1079),
    )
    edge_det = EdgeDetector(edge_cfg)
    clock = FakeClock(0.0)
    takeback_cfg = TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)
    takeback_det = TakebackDetector(config=takeback_cfg, now=clock)

    messages_built: list[AnyMessage] = []

    import time as _time

    def message_builder(msg_type: str) -> AnyMessage:
        ts = _time.monotonic()
        if msg_type == "OWNERSHIP_REQUEST":
            msg: AnyMessage = OwnershipRequest(ts=ts)
        elif msg_type == "SESSION_END_TAKEBACK":
            msg = SessionEnd(reason="takeback", ts=ts)
        else:
            raise ValueError(f"Unknown message type: {msg_type}")
        messages_built.append(msg)
        return msg

    coordinator = OwnershipCoordinator(
        fsm=fsm,
        edge_detector=edge_det,
        takeback_detector=takeback_det,
        message_builder=message_builder,
    )
    return coordinator, fsm, edge_det, takeback_det, clock, messages_built


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoordinatorEdgeCrossOut:
    """EdgeEvent.CROSS_OUT while IDLE → OWNERSHIP_REQUEST message returned."""

    def test_edge_cross_out_while_idle_returns_ownership_request(self) -> None:
        """on_mouse_event() with an EdgeEvent.CROSS_OUT while IDLE calls FSM and
        returns an outgoing OwnershipRequest message.

        Wiring: EdgeDetector.observe() returns CROSS_OUT → FSM.on_edge_cross_out()
        → coordinator returns OwnershipRequest.
        """
        coordinator, fsm, edge_det, takeback_det, clock, messages = make_coordinator()

        # Feed two ticks that produce CROSS_OUT from the right edge detector
        result1 = coordinator.on_mouse_event(x=1918, y=500, dx=0, dy=0, is_injected=False)
        assert result1 is None  # first tick — dwell not yet satisfied

        result2 = coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)
        assert isinstance(result2, OwnershipRequest)

        # FSM should now have pending grant (state still IDLE until grant received)
        assert fsm.state is OwnershipState.IDLE
        assert fsm._pending_grant is True  # type: ignore[attr-defined]

    def test_ownership_request_added_to_message_builder_output(self) -> None:
        """message_builder is called with 'OWNERSHIP_REQUEST' on edge cross-out."""
        coordinator, fsm, _, _, _, messages = make_coordinator()
        coordinator.on_mouse_event(x=1918, y=500, dx=0, dy=0, is_injected=False)
        coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)
        assert len(messages) == 1
        assert isinstance(messages[0], OwnershipRequest)


class TestCoordinatorTakeback:
    """Takeback signal while CONTROLLED → SESSION_END message returned."""

    def _make_controlled(
        self,
    ) -> tuple[OwnershipCoordinator, OwnershipFSM, FakeClock, list[AnyMessage]]:
        coordinator, fsm, edge_det, takeback_det, clock, messages = make_coordinator()
        # Manually put FSM into CONTROLLED state (REMOTE perspective)
        fsm.on_ownership_request_received()
        fsm.on_grant_sent()
        assert fsm.state is OwnershipState.CONTROLLED
        return coordinator, fsm, clock, messages

    def test_takeback_while_controlled_returns_session_end(self) -> None:
        """5px physical movement while CONTROLLED triggers takeback →
        coordinator returns SessionEnd(reason='takeback').

        on_local_input_detected() → FSM → IDLE.
        """
        coordinator, fsm, clock, messages = self._make_controlled()

        # Feed a 5px non-injected movement
        result = coordinator.on_mouse_event(x=500, y=500, dx=5, dy=0, is_injected=False)
        assert isinstance(result, SessionEnd)
        assert result.reason == "takeback"
        assert fsm.state is OwnershipState.IDLE

    def test_takeback_fsm_transitions_to_idle(self) -> None:
        """After takeback, FSM state is IDLE."""
        coordinator, fsm, clock, messages = self._make_controlled()
        coordinator.on_mouse_event(x=500, y=500, dx=5, dy=0, is_injected=False)
        assert fsm.state is OwnershipState.IDLE

    def test_injected_events_do_not_trigger_takeback_while_controlled(self) -> None:
        """is_injected=True events while CONTROLLED must not trigger takeback.

        REQ-MOUSE-TAKEBACK-003.
        """
        coordinator, fsm, clock, messages = self._make_controlled()
        for _ in range(10):
            result = coordinator.on_mouse_event(
                x=500, y=500, dx=5, dy=0, is_injected=True
            )
        assert result is None
        assert fsm.state is OwnershipState.CONTROLLED

    def test_edge_events_while_controlled_do_not_produce_ownership_request(
        self,
    ) -> None:
        """Edge cross-out events should NOT produce OwnershipRequest while CONTROLLED.

        The coordinator must suppress edge events when FSM is not IDLE.
        Uses injected events to avoid triggering takeback while testing edge logic.
        """
        coordinator, fsm, clock, messages = self._make_controlled()
        # Use injected events — they're ignored by takeback detector, so the FSM
        # stays CONTROLLED. Edge detection is not called for CONTROLLED state,
        # so no OwnershipRequest can be produced.
        result1 = coordinator.on_mouse_event(x=1918, y=500, dx=0, dy=0, is_injected=True)
        result2 = coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=True)
        # Neither result should be an OwnershipRequest
        assert not isinstance(result1, OwnershipRequest)
        assert not isinstance(result2, OwnershipRequest)
        # FSM should still be CONTROLLED (no spurious edge trigger)
        assert fsm.state is OwnershipState.CONTROLLED
