# Structure

## Directory Layout (Planned)

```
eou/
├── src/
│   └── eou/
│       ├── __init__.py
│       ├── cli.py                  # entry: `eou host` / `eou remote`
│       ├── config.py               # YAML config loader
│       │
│       ├── transport/              # ★ Protocol abstraction layer
│       │   ├── __init__.py
│       │   ├── base.py             # Transport ABC (connect/send/recv/close)
│       │   ├── tcp.py              # TCP implementation (Phase 1)
│       │   └── ble.py              # BLE implementation (Phase N, stub)
│       │
│       ├── protocol/               # Wire protocol (transport-agnostic)
│       │   ├── __init__.py
│       │   ├── messages.py         # MouseMove, OwnershipTransfer, Nack, ...
│       │   └── codec.py            # msgpack / length-prefixed framing
│       │
│       ├── ownership/              # State machine
│       │   ├── __init__.py
│       │   ├── state.py            # OwnershipState (IDLE/CONTROLLING/CONTROLLED)
│       │   └── edge_detector.py    # screen-edge proximity detection
│       │
│       ├── input/                  # OS-level capture & injection
│       │   ├── __init__.py
│       │   ├── capture.py          # pynput listener (HOST)
│       │   └── inject.py           # pynput controller (REMOTE)
│       │
│       ├── host.py                 # HOST role orchestration
│       └── remote.py               # REMOTE role orchestration
│
├── tests/
│   ├── unit/                       # transport, protocol, ownership (mocked I/O)
│   └── integration/                # loopback TCP, fake screens
│
├── configs/
│   └── eou.example.yaml
│
├── .moai/                          # MoAI-ADK artifacts
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
