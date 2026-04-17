"""Tests for OwnershipState enum and OwnershipFSM skeleton.

RED phase tests — T-010 (state/FSM skeleton).

Coverage:
- REQ-MOUSE-OWNERSHIP-001: exactly three mutually exclusive states
- FSM initial state, state property, subscribe() signature
"""

from __future__ import annotations

import pytest

from eou.ownership.state import InvalidTransitionError, OwnershipFSM, OwnershipState


class TestOwnershipStateEnum:
    """REQ-MOUSE-OWNERSHIP-001: exactly three mutually exclusive states."""

    def test_enum_has_exactly_three_members(self) -> None:
        """OwnershipState must have exactly three members: IDLE, CONTROLLING, CONTROLLED.

        REQ-MOUSE-OWNERSHIP-001: mutually exclusive, no fourth state.
        """
        members = list(OwnershipState)
        assert len(members) == 3

    def test_idle_member_exists(self) -> None:
        """IDLE state must exist as an OwnershipState member."""
        assert OwnershipState.IDLE is not None

    def test_controlling_member_exists(self) -> None:
        """CONTROLLING state must exist as an OwnershipState member."""
        assert OwnershipState.CONTROLLING is not None

    def test_controlled_member_exists(self) -> None:
        """CONTROLLED state must exist as an OwnershipState member."""
        assert OwnershipState.CONTROLLED is not None

    def test_states_are_mutually_exclusive(self) -> None:
        """No two state members share the same value (mutually exclusive).

        REQ-MOUSE-OWNERSHIP-001.
        """
        idle = OwnershipState.IDLE
        controlling = OwnershipState.CONTROLLING
        controlled = OwnershipState.CONTROLLED
        assert idle != controlling
        assert idle != controlled
        assert controlling != controlled

    def test_is_enum(self) -> None:
        """OwnershipState must be an Enum subclass."""
        from enum import Enum

        assert issubclass(OwnershipState, Enum)


class TestOwnershipFSMSkeleton:
    """Tests for OwnershipFSM skeleton (state, subscribe, initial state)."""

    def test_initial_state_is_idle(self) -> None:
        """Default initial state must be IDLE.

        REQ-MOUSE-OWNERSHIP-001: IDLE is the rest state.
        """
        fsm = OwnershipFSM()
        assert fsm.state is OwnershipState.IDLE

    def test_state_property_is_read_only(self) -> None:
        """FSM exposes a read-only `state` property — assignment must raise."""
        fsm = OwnershipFSM()
        with pytest.raises(AttributeError):
            fsm.state = OwnershipState.CONTROLLING  # type: ignore[misc]

    def test_subscribe_accepts_callback(self) -> None:
        """subscribe() must accept a Callable[[OwnershipState, OwnershipState], None]."""
        fsm = OwnershipFSM()
        called_with: list[tuple[OwnershipState, OwnershipState]] = []

        def cb(old: OwnershipState, new: OwnershipState) -> None:
            called_with.append((old, new))

        # Must not raise
        fsm.subscribe(cb)

    def test_no_subscriber_calls_on_construction(self) -> None:
        """No subscriber calls occur during FSM construction (no side effects)."""
        calls: list[tuple[OwnershipState, OwnershipState]] = []

        def cb(old: OwnershipState, new: OwnershipState) -> None:
            calls.append((old, new))

        fsm = OwnershipFSM()
        fsm.subscribe(cb)
        assert calls == []

    def test_multiple_subscribers_accepted(self) -> None:
        """Multiple callbacks may be subscribed without error."""
        fsm = OwnershipFSM()
        fsm.subscribe(lambda old, new: None)
        fsm.subscribe(lambda old, new: None)

    def test_invalid_transition_error_exists(self) -> None:
        """InvalidTransitionError must be importable from eou.ownership.state."""
        assert issubclass(InvalidTransitionError, RuntimeError)
