"""Acceptance scenario traces for SPEC-MOUSE-001 (pure logic — no transport, no capture).

T-019: Replay Scenarios 1, 2, 3, 5 from acceptance.md as pure logic traces.
Mouse events are fed directly; FSM state and emitted messages are verified.

Excluded: Scenarios 6/7 (visibility — Slice 3), Scenario 4 (transport disconnect — Slice 4).

Scenarios covered:
- Scenario 1: HOST IDLE → edge dwell → OWNERSHIP_REQUEST emitted → CONTROLLING
- Scenario 2: HOST CONTROLLING → REMOTE return edge → SESSION_END(edge_return) → IDLE
- Scenario 3: REMOTE CONTROLLED → physical input 5px → SESSION_END(takeback) → IDLE
- Scenario 5: Edge touch without dwell → no OWNERSHIP_REQUEST (negative test)
"""

from __future__ import annotations

import time

from eou.ownership.coordinator import OwnershipCoordinator
from eou.ownership.edge_detector import EdgeConfig, EdgeDetector
from eou.ownership.state import OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector
from eou.protocol.messages import AnyMessage, OwnershipRequest, SessionEnd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self._t = t

    def __call__(self) -> float:
        return self._t

    def advance(self, ms: float) -> None:
        self._t += ms / 1000.0


def make_host_coordinator(
    edge: str = "right",
    screen_bounds: tuple[int, int, int, int] = (0, 0, 1919, 1079),
    threshold_px: int = 2,
    dwell_ticks: int = 2,
) -> tuple[OwnershipCoordinator, OwnershipFSM, list[AnyMessage]]:
    """Build a coordinator representing the HOST node."""
    fsm = OwnershipFSM()
    edge_cfg = EdgeConfig(
        edge=edge,  # type: ignore[arg-type]
        threshold_px=threshold_px,
        dwell_ticks=dwell_ticks,
        screen_bounds=screen_bounds,
    )
    edge_det = EdgeDetector(edge_cfg)
    takeback_cfg = TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)
    clock = FakeClock()
    takeback_det = TakebackDetector(config=takeback_cfg, now=clock)

    messages: list[AnyMessage] = []

    def builder(msg_type: str) -> AnyMessage:
        ts = time.monotonic()
        if msg_type == "OWNERSHIP_REQUEST":
            msg: AnyMessage = OwnershipRequest(ts=ts)
        elif msg_type == "SESSION_END_TAKEBACK":
            msg = SessionEnd(reason="takeback", ts=ts)
        else:
            raise ValueError(f"Unknown message type: {msg_type}")
        messages.append(msg)
        return msg

    coordinator = OwnershipCoordinator(
        fsm=fsm,
        edge_detector=edge_det,
        takeback_detector=takeback_det,
        message_builder=builder,
    )
    return coordinator, fsm, messages


def make_remote_coordinator(
    return_edge: str = "left",
    screen_bounds: tuple[int, int, int, int] = (0, 0, 1919, 1079),
    threshold_px: int = 2,
    dwell_ticks: int = 2,
) -> tuple[OwnershipCoordinator, OwnershipFSM, FakeClock, list[AnyMessage]]:
    """Build a coordinator representing the REMOTE node."""
    fsm = OwnershipFSM()
    edge_cfg = EdgeConfig(
        edge=return_edge,  # type: ignore[arg-type]
        threshold_px=threshold_px,
        dwell_ticks=dwell_ticks,
        screen_bounds=screen_bounds,
    )
    edge_det = EdgeDetector(edge_cfg)
    takeback_cfg = TakebackConfig(pixel_threshold=5, event_count_threshold=2, time_window_ms=100)
    clock = FakeClock()
    takeback_det = TakebackDetector(config=takeback_cfg, now=clock)

    messages: list[AnyMessage] = []

    def builder(msg_type: str) -> AnyMessage:
        ts = time.monotonic()
        if msg_type == "OWNERSHIP_REQUEST":
            msg: AnyMessage = OwnershipRequest(ts=ts)
        elif msg_type == "SESSION_END_TAKEBACK":
            msg = SessionEnd(reason="takeback", ts=ts)
        else:
            raise ValueError(f"Unknown message type: {msg_type}")
        messages.append(msg)
        return msg

    coordinator = OwnershipCoordinator(
        fsm=fsm,
        edge_detector=edge_det,
        takeback_detector=takeback_det,
        message_builder=builder,
    )
    return coordinator, fsm, clock, messages


# ---------------------------------------------------------------------------
# Scenario 1 — Happy-path edge transfer HOST → REMOTE
# ---------------------------------------------------------------------------


def test_scenario_1_host_idle_edge_dwell_emits_ownership_request() -> None:
    """Scenario 1 (acceptance.md §1): HOST IDLE → right-edge dwell → OWNERSHIP_REQUEST.

    Given HOST state is IDLE.
    When cursor stays within 2px of right edge for 2 consecutive ticks.
    Then coordinator returns OwnershipRequest; FSM has pending grant (still IDLE).
    """
    # Given
    coordinator, fsm, messages = make_host_coordinator(edge="right")
    assert fsm.state is OwnershipState.IDLE

    # When — tick 1 (1px from right edge x=1919)
    result1 = coordinator.on_mouse_event(x=1918, y=500, dx=0, dy=0, is_injected=False)

    # Then — no message yet (dwell not satisfied)
    assert result1 is None
    assert fsm.state is OwnershipState.IDLE

    # When — tick 2 (at the edge)
    result2 = coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)

    # Then — OWNERSHIP_REQUEST emitted
    assert isinstance(result2, OwnershipRequest)
    assert len(messages) == 1
    assert isinstance(messages[0], OwnershipRequest)

    # FSM pending_grant set; state still IDLE (awaiting OWNERSHIP_GRANT from peer)
    assert fsm.state is OwnershipState.IDLE
    assert fsm._pending_grant is True  # type: ignore[attr-defined]

    # Simulate receiving OWNERSHIP_GRANT from REMOTE
    fsm.on_ownership_granted()
    assert fsm.state is OwnershipState.CONTROLLING


# ---------------------------------------------------------------------------
# Scenario 2 — Return transfer REMOTE → HOST (pure logic)
# ---------------------------------------------------------------------------


def test_scenario_2_controlling_session_end_returns_to_idle() -> None:
    """Scenario 2 (acceptance.md §1): CONTROLLING → SESSION_END(edge_return) → IDLE.

    Given HOST is in CONTROLLING state.
    When SESSION_END is received (simulating REMOTE return-edge trigger).
    Then HOST FSM transitions to IDLE.

    Note: The return-edge OWNERSHIP_REQUEST→GRANT exchange and cursor restoration
    are handled in Slice 3/4. Here we test the pure FSM logic path.
    """
    # Given — put HOST into CONTROLLING state
    coordinator, fsm, messages = make_host_coordinator()
    fsm.on_edge_cross_out()
    fsm.on_ownership_granted()
    assert fsm.state is OwnershipState.CONTROLLING

    # When — SESSION_END received from REMOTE (edge_return path)
    transitions: list[tuple[OwnershipState, OwnershipState]] = []
    fsm.subscribe(lambda old, new: transitions.append((old, new)))
    fsm.on_session_end("edge_return")

    # Then — FSM is IDLE
    assert fsm.state is OwnershipState.IDLE
    assert transitions == [(OwnershipState.CONTROLLING, OwnershipState.IDLE)]


# ---------------------------------------------------------------------------
# Scenario 3 — Takeback on REMOTE local input
# ---------------------------------------------------------------------------


def test_scenario_3_remote_physical_input_triggers_takeback() -> None:
    """Scenario 3 (acceptance.md §1): REMOTE CONTROLLED → 5px → SESSION_END(takeback) → IDLE.

    Given REMOTE is in CONTROLLED state.
    When local physical mouse produces 5px cumulative within 100ms.
    Then coordinator returns SessionEnd(reason='takeback'); FSM → IDLE.
    """
    # Given — REMOTE FSM in CONTROLLED state
    coordinator, fsm, clock, messages = make_remote_coordinator(return_edge="left")
    fsm.on_ownership_request_received()
    fsm.on_grant_sent()
    assert fsm.state is OwnershipState.CONTROLLED

    # When — physical movement: 5px non-injected in a single event
    result = coordinator.on_mouse_event(x=500, y=500, dx=5, dy=0, is_injected=False)

    # Then — SessionEnd(reason='takeback') emitted and FSM is IDLE
    assert isinstance(result, SessionEnd)
    assert result.reason == "takeback"
    assert fsm.state is OwnershipState.IDLE
    assert len(messages) == 1
    assert isinstance(messages[0], SessionEnd)


def test_scenario_3_injected_events_do_not_trigger_takeback() -> None:
    """Scenario 3 corollary: injected MOUSE_MOVE events do NOT trigger takeback.

    REQ-MOUSE-TAKEBACK-003.
    """
    coordinator, fsm, clock, messages = make_remote_coordinator(return_edge="left")
    fsm.on_ownership_request_received()
    fsm.on_grant_sent()
    assert fsm.state is OwnershipState.CONTROLLED

    # Many injected events — none should trigger takeback
    for _ in range(20):
        result = coordinator.on_mouse_event(x=500, y=500, dx=10, dy=0, is_injected=True)
    assert result is None
    assert fsm.state is OwnershipState.CONTROLLED
    assert len(messages) == 0


# ---------------------------------------------------------------------------
# Scenario 5 — Edge touch without dwell (negative test)
# ---------------------------------------------------------------------------


def test_scenario_5_single_tick_touch_no_ownership_request() -> None:
    """Scenario 5 (acceptance.md §1): single tick within 2px, then leave → no OWNERSHIP_REQUEST.

    Given HOST=IDLE.
    When cursor touches edge for only 1 tick, then moves away.
    Then no OWNERSHIP_REQUEST is emitted; FSM stays IDLE.

    REQ-MOUSE-EDGE-005.
    """
    # Given
    coordinator, fsm, messages = make_host_coordinator(edge="right")
    assert fsm.state is OwnershipState.IDLE

    # When — single tick within threshold
    result1 = coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)
    # Then — no message
    assert result1 is None

    # When — cursor leaves threshold
    result2 = coordinator.on_mouse_event(x=500, y=500, dx=0, dy=0, is_injected=False)

    # Then — still no message; FSM still IDLE
    assert result2 is None
    assert fsm.state is OwnershipState.IDLE
    assert len(messages) == 0


def test_scenario_5_gap_between_ticks_resets_dwell() -> None:
    """Scenario 5: tick inside → gap outside → tick inside again; dwell NOT satisfied.

    REQ-MOUSE-EDGE-005: continuity required.
    """
    coordinator, fsm, messages = make_host_coordinator(edge="right")

    coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)  # tick 1
    coordinator.on_mouse_event(x=500, y=500, dx=0, dy=0, is_injected=False)  # gap (reset)
    # tick 1 again
    result = coordinator.on_mouse_event(x=1919, y=500, dx=0, dy=0, is_injected=False)

    assert result is None
    assert fsm.state is OwnershipState.IDLE
    assert len(messages) == 0
