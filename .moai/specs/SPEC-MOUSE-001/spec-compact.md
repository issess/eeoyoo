# SPEC-MOUSE-001 — Compact

- id: SPEC-MOUSE-001
- version: 0.2.0
- status: draft
- priority: high
- author: senicy
- created: 2026-04-18
- updated: 2026-04-18

## REQ IDs

### REQ-MOUSE-OWNERSHIP
- REQ-MOUSE-OWNERSHIP-001 — Ubiquitous — FSM: IDLE | CONTROLLING | CONTROLLED (mutually exclusive)
- REQ-MOUSE-OWNERSHIP-002 — Event-driven — IDLE + OWNERSHIP_GRANT → CONTROLLED
- REQ-MOUSE-OWNERSHIP-003 — Event-driven — IDLE + OWNERSHIP_REQUEST/GRANT round-trip → CONTROLLING
- REQ-MOUSE-OWNERSHIP-004 — Event-driven — SESSION_END → IDLE within 50 ms
- REQ-MOUSE-OWNERSHIP-005 — State-driven — CONTROLLED: local cursor locked+hidden; on IDLE: unlock+restore
- REQ-MOUSE-OWNERSHIP-006 — Unwanted — CONTROLLING + OWNERSHIP_GRANT → discard + SESSION_END(reason=conflict)

### REQ-MOUSE-EDGE
- REQ-MOUSE-EDGE-001 — Ubiquitous — cursor sample ≥ 120 Hz in IDLE/CONTROLLING
- REQ-MOUSE-EDGE-002 — Event-driven — HOST: within 2 px of edge for ≥ 2 consecutive ticks → OWNERSHIP_REQUEST
- REQ-MOUSE-EDGE-003 — State-driven — CONTROLLED: monitor return edge with same rules → return OWNERSHIP_REQUEST
- REQ-MOUSE-EDGE-004 — Optional-feature — per-edge config overrides (px threshold, dwell count) honored
- REQ-MOUSE-EDGE-005 — Unwanted — dwell not satisfied → no OWNERSHIP_REQUEST

### REQ-MOUSE-TAKEBACK
- REQ-MOUSE-TAKEBACK-001 — Event-driven — CONTROLLED: ≥ 5 px or ≥ 2 non-injected events in 100 ms → takeback trigger
- REQ-MOUSE-TAKEBACK-002 — Event-driven — on takeback: stop injection, SESSION_END(reason=takeback), → IDLE within 100 ms
- REQ-MOUSE-TAKEBACK-003 — Ubiquitous — injected events MUST NOT trigger takeback (tagging required)
- REQ-MOUSE-TAKEBACK-004 — Unwanted — takeback never emitted in IDLE/CONTROLLING

### REQ-MOUSE-TRANSPORT
- REQ-MOUSE-TRANSPORT-001 — Ubiquitous — Transport ABC (connect/send/recv/close, async)
- REQ-MOUSE-TRANSPORT-002 — Ubiquitous — non-transport modules depend on ABC only; DI-injected
- REQ-MOUSE-TRANSPORT-003 — Unwanted — direct import of transport.tcp/transport.ble outside transport/ → layer-check fails
- REQ-MOUSE-TRANSPORT-004 — Event-driven — unrecoverable I/O → force FSM IDLE + restore local cursor
- REQ-MOUSE-TRANSPORT-005 — Optional-feature — BLE swap modifies only transport/; upper layers unchanged

### REQ-MOUSE-PROTOCOL
- REQ-MOUSE-PROTOCOL-001 — Ubiquitous — framing = 4-byte BE length prefix + msgpack payload (length excludes prefix)
- REQ-MOUSE-PROTOCOL-002 — Ubiquitous — message types ⊇ {HELLO, MOUSE_MOVE, OWNERSHIP_REQUEST, OWNERSHIP_GRANT, SESSION_END, HEARTBEAT}
- REQ-MOUSE-PROTOCOL-003 — Ubiquitous — MOUSE_MOVE = {dx:int, dy:int, abs_x?:int, abs_y?:int, ts:float}
- REQ-MOUSE-PROTOCOL-004 — Event-driven — CONTROLLING captures move → MOUSE_MOVE emitted within 10 ms
- REQ-MOUSE-PROTOCOL-005 — Event-driven — idle 1s → HEARTBEAT; 3 consecutive misses → teardown (per REQ-MOUSE-TRANSPORT-004)
- REQ-MOUSE-PROTOCOL-006 — Unwanted — frame > 64 KiB OR invalid msgpack OR unknown type → discard + log; no FSM mutation

### REQ-MOUSE-VISIBILITY (v0.2.0)
- REQ-MOUSE-VISIBILITY-001 — Ubiquitous — HOST maintains cursor visibility state bound to OwnershipState; exposes `pre_hide_position: tuple[int, int]`
- REQ-MOUSE-VISIBILITY-002 — Event-driven — IDLE → CONTROLLING: capture pre_hide_position, park cursor at virtual-screen (-32000, -32000), install WH_MOUSE_LL hook that consumes (returns 1) all mouse events
- REQ-MOUSE-VISIBILITY-003 — Event-driven — CONTROLLING → IDLE (via edge return OR session_end/takeback OR transport disconnect): uninstall WH_MOUSE_LL hook, restore cursor to pre_hide_position, within 50 ms
- REQ-MOUSE-VISIBILITY-004 — Unwanted — NO ShowCursor(FALSE), NO SetSystemCursor, NO overlay/tray windows, NO REMOTE-side cursor visibility manipulation
- REQ-MOUSE-VISIBILITY-005 — State-driven — WHILE HOST in CONTROLLED: no hiding/parking/hook applied on HOST (reserved for Phase 2, no-op in 2-node MVP)

## Acceptance Scenarios

- S1 edge transfer HOST → REMOTE (happy path, ≤ 250 ms)
- S2 return transfer REMOTE → HOST (symmetric edge)
- S3 takeback on REMOTE local input (≤ 100 ms)
- S4 transport disconnect mid-session (peer reset / 3 missed heartbeats)
- S5 edge touch without dwell satisfaction → NO transfer
- S6 HOST cursor parking + WH_MOUSE_LL consumes local input during CONTROLLING; REMOTE cursor unaffected (REQ-MOUSE-VISIBILITY-001/002/004)
- S7 normal return edge: cursor restored to pre_hide_position within ≤ 50 ms (REQ-MOUSE-VISIBILITY-003)
- S8 takeback path AND transport-disconnect path: cursor restored to same pre_hide_position, hook uninstalled (REQ-MOUSE-VISIBILITY-003)

## Performance

- edge → REMOTE cursor start ≤ 250 ms (p95, LAN)
- REMOTE local input → HOST cursor unlock ≤ 100 ms (p95)
- Cursor restore (CONTROLLING → IDLE transition → OS cursor at pre_hide_position) ≤ 50 ms (p95)
- MOUSE_MOVE sustained ≥ 120 Hz
- 1-hour continuous run: no crash/hang; CONTROLLING ↔ IDLE repeat transitions with zero restore miss

## Quality Gates

- coverage ≥ 85%
- src/eou/input/visibility.py coverage ≥ 85% with Windows API mocked via unittest.mock.patch
- transport/ importable and testable in isolation
- ruff warnings = 0
- layer-check test enforces transport boundary
- MOUSE_MOVE oversize/unknown frame rejection
- REQ-MOUSE-VISIBILITY-001..005 each has ≥ 1 corresponding unit test

## Affected Files

- src/eou/transport/base.py
- src/eou/transport/tcp.py
- src/eou/protocol/messages.py
- src/eou/protocol/codec.py
- src/eou/ownership/state.py
- src/eou/ownership/edge_detector.py
- src/eou/input/capture.py
- src/eou/input/inject.py
- src/eou/input/visibility.py  (NEW v0.2.0 — CursorVisibility abstraction + Windows impl)
- src/eou/host.py
- src/eou/remote.py
- src/eou/cli.py
- configs/eou.example.yaml
- tests/unit/**
- tests/integration/**

## Exclusions (What NOT to Build)

- keyboard event sharing
- clipboard sharing
- BLE transport (actual implementation)
- mobile pairing app
- macOS / Linux support
- 3+ node topology
- encryption / authentication (MVP LAN trust)
- GUI configuration app
- high-refresh gaming sync (≥ 240 Hz)
- virtual desktop / multi-logical-screen awareness
- REMOTE-side cursor image / visibility manipulation (REQ-MOUSE-VISIBILITY-004)
- system-wide ShowCursor(FALSE) / SetSystemCursor
- overlay / tray / topmost visibility indicator windows
