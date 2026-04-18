# EOU — 크로스-PC 마우스 공유 (Cross-PC Mouse Sharing)

**EOU** (Edge-triggered Ownership Utility)는 Synergy와 같이 두 대의 Windows PC 간 마우스 커서 제어를 자동으로 공유합니다. 한 세트의 마우스로 여러 PC를 제어하며, 화면 가장자리로 커서를 밀기만 하면 자동으로 다른 PC로 제어권이 넘어갑니다.

## Features (v0.2.0 MVP)

- **엣지 기반 자동 전환**: 화면 가장자리에서 2px 이상 2틱 동안 근접하면 자동으로 제어권 이동
- **즉시 제어권 반납**: REMOTE PC의 사용자가 마우스를 움직이면 100ms 이내 HOST로 제어권 반환
- **HOST 커서 숨김**: REMOTE 제어 중 HOST 커서는 오프스크린 좌표로 파킹되고 저수준 훅으로 물리 입력 소비
- **플러그형 트랜스포트**: TCP 구현 + BLE 교체 가능한 추상화 인터페이스
- **비동기 오케스트레이션**: asyncio 기반, pynput 스레드 안전 통합

## Status

- **플랫폼**: Windows 10/11 x64 전용 (MVP)
- **Python**: 3.10+ (개발), 3.11+ (타깃 per spec)
- **테스트**: 289개 통과, 85.34% 커버리지
- **SPEC**: [SPEC-MOUSE-001 v0.2.0](.moai/specs/SPEC-MOUSE-001/spec.md) (implemented)

## Quick Start

### 설치 (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# 또는 scripts\install.bat를 더블클릭
```

스크립트가 `uv`를 설치하고 `.venv`를 생성한 후 `eou[full]`를 편집 모드로 설치합니다.

### 수동 설치 (Linux/macOS)

```bash
# 1. uv 설치 (이미 설치됨면 skip)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. venv 생성 및 eou 설치
uv venv
uv pip install -e ".[full]"
```

### 실행

```bash
# HOST PC에서
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
eou host --config configs/eou.host.example.yaml

# REMOTE PC에서 (다른 터미널)
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
eou remote --config configs/eou.remote.example.yaml
```

> **Windows (한국 로캘) 주의**: `UnicodeEncodeError: 'cp949' codec` 오류가 나면 쉘에서 UTF-8 모드 설정:
> ```powershell
> $env:PYTHONUTF8 = "1"
> ```
> `install.ps1`이 자동 설정합니다.

## Configuration

### HOST 설정 (`configs/eou.host.example.yaml`)

```yaml
role: host
endpoint: "192.168.1.5:7001"  # REMOTE PC 주소:포트

edge:
  threshold_px: 2    # 엣지로부터 px 단위 거리
  dwell_ticks: 2     # 이 거리 내에 머물러야 할 폴링 틱 수 (≥120Hz)
```

### REMOTE 설정 (`configs/eou.remote.example.yaml`)

```yaml
role: remote
endpoint: "0.0.0.0:7001"  # 모든 인터페이스에서 수신 (또는 고정 LAN IP)

takeback:
  pixel_threshold: 5    # 누적 이동 거리 (px)
  event_count_threshold: 2  # 비주입 이벤트 수
  time_window_ms: 100   # 윈도우 기간 (ms)
```

전체 설정 형식은 `configs/eou.host.example.yaml` 및 `configs/eou.remote.example.yaml`을 참조하세요.

## Architecture

```
HOST PC                          REMOTE PC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pynput listener     ────────→   TCP socket
        ↓                              ↓
ownership FSM  ────[MOUSE_MOVE]────→ inject (pynput)
        ↓                              
ownership FSM  ←─[SESSION_END]────── takeback detector
        ↓
cursor visibility (WH_MOUSE_LL hook)
```

**계층 구조:**
- `transport/`: TCP ABC + impl (BLE 교체 가능)
- `protocol/`: msgpack 코덱 (4바이트 BE 길이 prefix)
- `ownership/`: 3-state FSM (IDLE/CONTROLLING/CONTROLLED) + edge detector + takeback detector
- `input/`: pynput capture/inject + Windows cursor visibility (파킹 + 훅)
- `host.py` / `remote.py`: 오케스트레이션
- `cli.py`: typer CLI (eou host / eou remote 서브커맨드)

## Development

### 테스트 실행

```bash
pytest --cov=src/eou --cov-report=term-missing
```

### Linting

```bash
ruff check src/eou tests/
ruff format src/eou tests/
```

### 커버리지 타깃

85% 이상. 현재: **85.34%**

## Roadmap

| Feature | Status | SPEC |
|---------|--------|------|
| Mouse ownership transfer | ✓ Implemented | SPEC-MOUSE-001 v0.2.0 |
| Keyboard event sharing | Planned | SPEC-KEYBOARD-001 |
| Clipboard sync | Planned | SPEC-CLIPBOARD-001 |
| BLE transport (via phone gateway) | Planned | SPEC-BLE-001 |
| macOS support | Planned | SPEC-OS-MACOS |
| Linux support | Planned | SPEC-OS-LINUX |
| 3+ node topology | Planned | SPEC-TOPOLOGY-NODES |

## Known Limitations

- **Windows 전용**: MVP는 Windows 10/11에서만 동작 (pynput/ctypes.windll 사용)
- **인증/암호화 없음**: LAN trust 모델 가정 (BLE 단계에서 재평가)
- **안티체트 호환성**: WH_MOUSE_LL 훅이 보안 소프트웨어에 의해 거부될 수 있음 (Valorant, BattlEye 등)
- **단일 논리 화면**: 다중 모니터 가상 데스크탑은 이후 단계에서 지원 (SPEC-EDGE-VIRTUAL)

## License

MIT (LICENSE 파일 참조)

## References

- **Full Specification**: [.moai/specs/SPEC-MOUSE-001/spec.md](.moai/specs/SPEC-MOUSE-001/spec.md)
- **Acceptance Criteria**: [.moai/specs/SPEC-MOUSE-001/acceptance.md](.moai/specs/SPEC-MOUSE-001/acceptance.md)
- **TRUST 5 Audit**: [.moai/reports/trust5-SPEC-MOUSE-001.md](.moai/reports/trust5-SPEC-MOUSE-001.md)
