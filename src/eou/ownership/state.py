"""Ownership state machine for SPEC-MOUSE-001.

Implements REQ-MOUSE-OWNERSHIP-001..006 as a pure synchronous state machine
with no I/O, no threading, and no asyncio dependencies.

The FSM accepts discrete events and returns deterministically.
All clocks and side-effects are the responsibility of the orchestration
layer (host.py / remote.py in Slice 4).

REQ-MOUSE-OWNERSHIP-001: Exactly three mutually exclusive states.
REQ-MOUSE-OWNERSHIP-002: IDLE + GRANT_RECEIVED → CONTROLLED.
REQ-MOUSE-OWNERSHIP-003: IDLE + on_edge_cross_out() → pending; pending + GRANT_RECEIVED →
    CONTROLLING.
REQ-MOUSE-OWNERSHIP-004: CONTROLLING/CONTROLLED + SESSION_END → IDLE.
REQ-MOUSE-OWNERSHIP-005: CONTROLLED → IDLE emits unlock signal.
REQ-MOUSE-OWNERSHIP-006: CONTROLLING + GRANT_RECEIVED → discard + emit conflict SESSION_END.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] OwnershipState — invariant contract for the whole application.
# @MX:REASON: All components (edge detector, takeback, host, remote, coordinator)
#             depend on these three states. Adding/removing a state here is a
#             breaking change that cascades through every FSM transition and
#             every integration test.
class OwnershipState(Enum):
    """Three mutually exclusive ownership states.

    REQ-MOUSE-OWNERSHIP-001: exactly one of these is active per node at all times.
    """

    IDLE = "IDLE"
    CONTROLLING = "CONTROLLING"
    CONTROLLED = "CONTROLLED"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidTransitionError(RuntimeError):
    """Raised when an FSM event is not valid from the current state.

    REQ-MOUSE-OWNERSHIP-006: CONTROLLING + GRANT_RECEIVED raises this (caller
    is responsible for emitting SESSION_END conflict).
    """


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] OwnershipFSM — invariant contract for ownership transitions.
# @MX:REASON: Every caller that drives the ownership protocol (OwnershipCoordinator,
#             Host, Remote) routes events through this class. The transition table
#             must match REQ-MOUSE-OWNERSHIP-002..006 exactly; any deviation silently
#             breaks the protocol across both nodes.
class OwnershipFSM:
    """Pure-sync ownership state machine.

    Manages the IDLE / CONTROLLING / CONTROLLED three-state protocol.
    No I/O; no threading; no asyncio.

    Internal pending-grant flag (REQ-MOUSE-OWNERSHIP-003):
    on_edge_cross_out() sets _pending_grant = True (state stays IDLE).
    on_ownership_granted() transitions IDLE → CONTROLLING only when
    _pending_grant is True; otherwise raises InvalidTransitionError.

    # @MX:WARN: [AUTO] _pending_grant flag is not thread-safe.
    # @MX:REASON: OwnershipFSM is pure sync; the caller (Coordinator/Host) must
    #             ensure single-threaded (event-loop) access. Crossing thread
    #             boundaries without a lock causes silent state corruption.
    """

    def __init__(self) -> None:
        self._state: OwnershipState = OwnershipState.IDLE
        self._pending_grant: bool = False
        self._subscribers: list[Callable[[OwnershipState, OwnershipState], None]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> OwnershipState:
        """Current ownership state (read-only)."""
        return self._state

    def subscribe(
        self,
        callback: Callable[[OwnershipState, OwnershipState], None],
    ) -> None:
        """Register a callback invoked on every successful state transition.

        The callback receives (old_state, new_state).
        Callbacks are called synchronously inside the transition method.
        """
        self._subscribers.append(callback)

    # ------------------------------------------------------------------
    # Transition methods (T-012 / T-013 RED-GREEN)
    # ------------------------------------------------------------------

    def on_edge_cross_out(self) -> None:
        """HOST local cursor crossed the configured edge (IDLE only).

        Sets _pending_grant = True; state stays IDLE until on_ownership_granted().
        REQ-MOUSE-OWNERSHIP-003 (first half).
        """
        if self._state is not OwnershipState.IDLE:
            raise InvalidTransitionError(
                f"on_edge_cross_out() called from state {self._state.value}; "
                "only valid from IDLE."
            )
        self._pending_grant = True

    def on_ownership_granted(self) -> None:
        """OWNERSHIP_GRANT received (HOST side: IDLE → CONTROLLING, or conflict).

        REQ-MOUSE-OWNERSHIP-003: transitions IDLE → CONTROLLING when _pending_grant.
        REQ-MOUSE-OWNERSHIP-006: CONTROLLING + grant → raises InvalidTransitionError.
        """
        if self._state is OwnershipState.CONTROLLING:
            raise InvalidTransitionError(
                "OWNERSHIP_GRANT received while already CONTROLLING. "
                "Caller must emit SESSION_END(reason='conflict')."
            )
        if self._state is OwnershipState.CONTROLLED:
            raise InvalidTransitionError(
                "OWNERSHIP_GRANT received while CONTROLLED. Invalid transition."
            )
        # IDLE case
        if not self._pending_grant:
            raise InvalidTransitionError(
                "on_ownership_granted() called without prior on_edge_cross_out(). "
                "Unsolicited grant is invalid."
            )
        self._pending_grant = False
        self._transition(OwnershipState.CONTROLLING)

    def on_edge_return(self) -> None:
        """Cursor returned to its home edge (CONTROLLING → IDLE).

        REQ-MOUSE-OWNERSHIP-004: normal return path.
        """
        if self._state is not OwnershipState.CONTROLLING:
            raise InvalidTransitionError(
                f"on_edge_return() called from state {self._state.value}; "
                "only valid from CONTROLLING."
            )
        self._transition(OwnershipState.IDLE)

    def on_ownership_request_received(self) -> None:
        """OWNERSHIP_REQUEST received from peer (IDLE only — REMOTE side first half).

        Sets internal flag analogous to _pending_grant for the grant-sent flow.
        REQ-MOUSE-OWNERSHIP-002 (first half for REMOTE).
        """
        if self._state is not OwnershipState.IDLE:
            raise InvalidTransitionError(
                f"on_ownership_request_received() called from state {self._state.value}; "
                "only valid from IDLE."
            )
        self._pending_ownership_request: bool = True

    def on_grant_sent(self) -> None:
        """OWNERSHIP_GRANT sent to peer (IDLE → CONTROLLED).

        REQ-MOUSE-OWNERSHIP-002: IDLE + GRANT_RECEIVED → CONTROLLED.
        In our FSM the grant is sent by this node, mirroring the HOST flow.
        """
        if self._state is not OwnershipState.IDLE:
            raise InvalidTransitionError(
                f"on_grant_sent() called from state {self._state.value}; "
                "only valid from IDLE."
            )
        self._transition(OwnershipState.CONTROLLED)

    def on_local_input_detected(self) -> None:
        """Local physical input detected while CONTROLLED (takeback initiation).

        CONTROLLED → IDLE.
        REQ-MOUSE-OWNERSHIP-005 / TAKEBACK flow from REMOTE perspective.
        """
        if self._state is not OwnershipState.CONTROLLED:
            raise InvalidTransitionError(
                f"on_local_input_detected() called from state {self._state.value}; "
                "only valid from CONTROLLED."
            )
        self._transition(OwnershipState.IDLE)

    def on_session_end(self, reason: str) -> None:
        """SESSION_END received or sent — transition to IDLE from any active state.

        REQ-MOUSE-OWNERSHIP-004: CONTROLLING or CONTROLLED → IDLE.
        Valid reasons: 'takeback', 'transport_disconnect', 'shutdown', 'conflict',
        'edge_return'.
        """
        if self._state is OwnershipState.IDLE:
            # Already idle — no-op (idempotent on disconnect bursts)
            return
        self._transition(OwnershipState.IDLE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(self, new_state: OwnershipState) -> None:
        """Perform a state transition and notify all subscribers."""
        old_state = self._state
        self._state = new_state
        for cb in self._subscribers:
            cb(old_state, new_state)
