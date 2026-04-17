# eou — Edge-Triggered Mouse Ownership Transfer

EOU (Edge-triggered Ownership Utility) enables seamless mouse control transfer between two
Windows PCs over a local network. Move the cursor to a screen edge to hand off control; the
remote user can reclaim it instantly with any physical mouse input.

## Quick Start

```bash
pip install -e ".[full]"
eou host --config configs/eou.example.yaml   # on the HOST PC
eou remote --config configs/eou.example.yaml # on the REMOTE PC
```

## Design

Core specification: [SPEC-MOUSE-001](.moai/specs/SPEC-MOUSE-001/spec.md)

Layers: `transport/` (TCP ABC + impl) → `protocol/` (msgpack codec) → `ownership/` (FSM +
edge detector) → `input/` (pynput capture/inject + Windows cursor visibility).

Transport is pluggable; a future BLE implementation only requires changes inside
`src/eou/transport/`.
