"""Ownership package — pure-sync domain logic for SPEC-MOUSE-001 Slice 2.

Public re-exports for convenience. All modules are pure synchronous;
no asyncio, no threading, no I/O.
"""

from __future__ import annotations

from eou.ownership.coordinator import OwnershipCoordinator
from eou.ownership.edge_detector import EdgeConfig, EdgeDetector, EdgeEvent
from eou.ownership.state import InvalidTransitionError, OwnershipFSM, OwnershipState
from eou.ownership.takeback_detector import TakebackConfig, TakebackDetector

__all__ = [
    "OwnershipState",
    "OwnershipFSM",
    "InvalidTransitionError",
    "EdgeConfig",
    "EdgeDetector",
    "EdgeEvent",
    "TakebackConfig",
    "TakebackDetector",
    "OwnershipCoordinator",
]
