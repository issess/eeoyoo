# eou — Edge-Triggered Mouse Ownership Transfer

EOU (Edge-triggered Ownership Utility) enables seamless mouse control transfer between two
Windows PCs over a local network. Move the cursor to a screen edge to hand off control; the
remote user can reclaim it instantly with any physical mouse input.

## Quick Start

EOU uses [uv](https://docs.astral.sh/uv/) for Python environment management.

### Windows (one-shot installer)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# or double-click scripts\install.bat
```

The script installs `uv` if missing, creates `.venv`, and installs `eou[full,windows-extra]`
in editable mode.

### Linux / macOS / manual

```bash
# 1. install uv (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. create venv and install eou
uv venv
uv pip install -e ".[full]"
```

### Run

```bash
source .venv/bin/activate                    # Windows: .\.venv\Scripts\Activate.ps1
eou host   --config configs/eou.example.yaml # on the HOST PC
eou remote --config configs/eou.example.yaml # on the REMOTE PC
```

## Design

Core specification: [SPEC-MOUSE-001](.moai/specs/SPEC-MOUSE-001/spec.md)

Layers: `transport/` (TCP ABC + impl) → `protocol/` (msgpack codec) → `ownership/` (FSM +
edge detector) → `input/` (pynput capture/inject + Windows cursor visibility).

Transport is pluggable; a future BLE implementation only requires changes inside
`src/eou/transport/`.
