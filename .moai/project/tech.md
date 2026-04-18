# Technology

## Language & Runtime

- **Python 3.11+** (target, per spec.md)
- **Python 3.10** (minimum for development; pragmatic concession for broader dev environment compatibility)
- Type hints required throughout (`from __future__ import annotations`)
- `asyncio` for transport I/O; input capture runs on dedicated thread (pynput requirement)

## Dependencies (MVP)

| Purpose | Library | Version | Status | Notes |
|---|---|---|---|---|
| Mouse capture + injection | `pynput` | ≥ 1.7.6 | Runtime | Cross-platform; Windows uses SendInput under the hood |
| Screen geometry | `screeninfo` | ≥ 0.8.1 | Runtime | Multi-monitor bounds for edge detection |
| Wire format | `msgpack` | ≥ 1.0.7 | Runtime | Compact, fast, binary-safe; swap-friendly vs JSON |
| Config | `pyyaml` | ≥ 6.0 | Runtime | YAML config loading |
| CLI | `typer` | ≥ 0.12 | Runtime | `eou host` / `eou remote` subcommands (promoted from dev-only Slice 4) |
| Windows helpers (optional) | `pywin32` | ≥ 306 | Optional | Fallback for low-level events if pynput proves insufficient |

**Test stack:**
- `pytest` + `pytest-asyncio`
- `hypothesis` for protocol round-trip properties
- Coverage target: 85%+ (TRUST 5)

## Transport Abstraction

```python
# src/eou/transport/base.py (sketch — not implementation)
class Transport(Protocol):
    async def connect(self, endpoint: str) -> None: ...
    async def send(self, frame: bytes) -> None: ...
    async def recv(self) -> bytes: ...
    async def close(self) -> None: ...
```

- **TCP impl (MVP):** length-prefixed (4-byte BE) framing over `asyncio.StreamReader/Writer`.
- **BLE impl (future):** GATT characteristic chunking; same `Transport` interface.
- Framing is the transport's responsibility; `protocol/codec.py` only serializes/deserializes complete messages.

## OS Targets

- **MVP:** Windows 10/11 x64
- **Phase 2+:** macOS (pynput + accessibility permission), Linux (evdev/uinput)

## Known Constraints

- pynput on Windows requires running as the interactive user (not service account)
- Global mouse hook can conflict with some games/anti-cheat; document as known limitation
- `screeninfo` detects physical monitor layout but does NOT know virtual desktop configs — edge detection treats each PC as single logical screen in MVP

## Performance Targets (MVP)

| Metric | Target |
|---|---|
| Edge-trigger → REMOTE cursor start | ≤ 250 ms (LAN) |
| REMOTE local-input → HOST takeback | ≤ 100 ms |
| Mouse move throughput | ≥ 120 Hz sustained |
| CPU (idle/controlling) | ≤ 3% / ≤ 8% on modern desktop |

## Security Posture (MVP)

- LAN-only trust model; no auth, no encryption in MVP (documented as known limit)
- BLE phase will reintroduce pairing-based trust — out of MVP scope
- Localhost loopback tests required before any LAN bind
