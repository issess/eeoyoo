"""Latency benchmarks for SPEC-MOUSE-001.

# @MX:TODO: [AUTO] Run manually after Slice 4 E2E; not part of pytest suite.
# These benchmarks require real OS mouse input and a LAN peer.
# They document the Performance Acceptance criteria from acceptance.md §2.

Usage (on HOST PC with REMOTE already running):
    python benchmarks/bench_latency.py --config configs/eou.yaml --iterations 20

Measurements:
    1. Edge dwell → REMOTE first MOUSE_MOVE latency (target: ≤ 250ms p95).
    2. REMOTE physical input → HOST cursor unlock latency (target: ≤ 100ms p95).
    3. CONTROLLING → IDLE cursor restore latency (target: ≤ 50ms p95).
    4. MOUSE_MOVE send frequency during CONTROLLING (target: ≥ 120 Hz).
    5. 1-hour stability test: zero crash/hang.
"""
from __future__ import annotations

# Benchmark script skeleton — implementation deferred to post-MVP manual validation.
# See acceptance.md §2 Performance Acceptance for measurement methodology.

print("Benchmark script — run manually post-Slice 4 with real hardware.")
print("See acceptance.md §2 for measurement methodology.")
print("")
print("Targets:")
print("  Edge dwell → REMOTE first move  : ≤ 250ms p95")
print("  REMOTE input → HOST unlock       : ≤ 100ms p95")
print("  CONTROLLING→IDLE cursor restore  : ≤ 50ms  p95")
print("  MOUSE_MOVE send frequency        : ≥ 120 Hz")
print("  1-hour stability                 : 0 crashes")
