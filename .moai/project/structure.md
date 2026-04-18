# Structure

## Directory Layout (Planned)

```
eou/
├── src/
│   └── eou/
│       ├── __init__.py
│       ├── cli.py                  # entry: `eou host` / `eou remote` (typer CLI)
│       ├── config.py               # YAML config loader
│       ├── bridge.py               # asyncio↔thread bridge for pynput integration
│       │
│       ├── transport/              # ★ Protocol abstraction layer
│       │   ├── __init__.py
│       │   ├── base.py             # Transport ABC (connect/send/recv/close)
│       │   ├── tcp.py              # TCP implementation (Phase 1)
│       │   ├── ble.py              # BLE implementation (Phase N, stub)
│       │   └── _factory.py         # DI factory (make_tcp_transport) — preserves layer boundary
│       │
│       ├── protocol/               # Wire protocol (transport-agnostic)
│       │   ├── __init__.py
│       │   ├── messages.py         # MouseMove, OwnershipTransfer, SessionEnd, ...
│       │   └── codec.py            # msgpack / 4-byte BE length-prefixed framing
│       │
│       ├── ownership/              # State machine
│       │   ├── __init__.py
│       │   ├── state.py            # OwnershipFSM (IDLE/CONTROLLING/CONTROLLED, 3-state)
│       │   ├── edge_detector.py    # screen-edge proximity detection (2px/2-tick default)
│       │   ├── takeback_detector.py# local input detection (5px/2-events/100ms default)
│       │   └── config.py           # EdgeConfig, TakebackConfig dataclasses
│       │
│       ├── input/                  # OS-level capture & injection
│       │   ├── __init__.py
│       │   ├── backend.py          # MouseBackend Protocol + pynput Windows impl
│       │   ├── capture.py          # MouseCapture (pynput listener → asyncio queue)
│       │   ├── inject.py           # MouseInjector (REMOTE side, delta clamping)
│       │   ├── visibility.py       # CursorVisibility Protocol + NullCursorVisibility
│       │   └── _visibility_windows.py  # WindowsCursorVisibility (WH_MOUSE_LL hook + park)
│       │
│       ├── host.py                 # HOST role orchestration (owns physical input)
│       └── remote.py               # REMOTE role orchestration (receives injected input)
│
├── tests/
│   ├── unit/                       # transport, protocol, ownership, input, config (mocked I/O)
│   ├── integration/                # TCP loopback, E2E scenarios, CLI smoke test
│   ├── fakes/                      # Test doubles (FakeTransport, FakeMouseBackend, FakeCursorVisibility)
│   └── meta/                       # Architecture enforcement (import boundaries)
│
├── configs/
│   ├── eou.host.example.yaml      # HOST role example config
│   └── eou.remote.example.yaml    # REMOTE role example config
│
├── .moai/                          # MoAI-ADK artifacts
├── CHANGELOG.md                    # Release notes (new, v0.2.0)
└── pyproject.toml
```

## Layer Boundaries

| Layer | Depends on | Must NOT depend on |
|---|---|---|
| `transport` | stdlib only | protocol, ownership, input |
| `protocol` | transport (interface only) | ownership, input |
| `ownership` | protocol | transport impl, input |
| `input` | OS libs (pynput) | transport, protocol |
| `host` / `remote` | all above | — |

**Rule:** `transport.base.Transport` is the seam for BLE swap. No module outside `transport/` imports `transport.tcp` or `transport.ble` directly — they receive a `Transport` instance via DI.

## Runtime Topology (Phase 1, TCP)

```
┌──────────────── HOST PC ────────────────┐       ┌─────────────── REMOTE PC ──────────────┐
│  capture(pynput) → ownership.state →    │       │   ← ownership.state ← protocol.decode  │
│  protocol.encode → transport.tcp.send ──┼──TCP──┼──→ transport.tcp.recv → inject(pynput) │
└─────────────────────────────────────────┘       └────────────────────────────────────────┘
```

## Phase N (BLE) Topology

```
HOST PC ──BLE──→ Phone (BLE GATT server, relay) ──BLE──→ REMOTE PC
```
Only `transport/ble.py` changes; everything above is intact.
