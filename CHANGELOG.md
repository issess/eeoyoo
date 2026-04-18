# Changelog

모든 주목할 만한 변경 사항은 이 파일에 기록됩니다.
형식: [Keep a Changelog](https://keepachangelog.com/ko/).
버전 관리: [SemVer](https://semver.org/).

## [0.2.0] - 2026-04-19

### Added

- **SPEC-MOUSE-001 MVP 구현 완료**
  - 4개 수직 슬라이스, 36개 태스크 완성
  - 289개 단위·통합·메타 테스트 passing
  - 85.34% 코드 커버리지 달성

- **Transport ABC (`src/eou/transport/base.py`)**
  - `Transport` 추상 기본 클래스
  - 비동기 `connect(endpoint)`, `send(frame)`, `recv()`, `close()` 연산
  - TCP 구현 포함 (Slice 1)
  - BLE 교체 가능한 플러그형 설계

- **Wire Protocol (`src/eou/protocol/`)**
  - 4바이트 빅엔디언 길이 prefix + msgpack payload
  - 최대 16 MiB 프레임 크기
  - 6개 메시지 타입: HELLO, MOUSE_MOVE, OWNERSHIP_REQUEST/GRANT, SESSION_END, HEARTBEAT
  - msgpack 기반 인코딩 (compact, fast, binary-safe)

- **Ownership FSM (`src/eou/ownership/state.py`)**
  - 3-state 상태 머신 (IDLE, CONTROLLING, CONTROLLED)
  - Pending-grant 내부 플래그
  - REQ-MOUSE-OWNERSHIP-001..006 전부 매핑

- **Edge Detector (`src/eou/ownership/edge_detector.py`)**
  - 화면 엣지 근처 커서 위치 모니터링
  - 2px 임계값, 2-tick dwell 조건 (기본값)
  - Per-edge 설정 오버라이드 지원

- **Takeback Detector (`src/eou/ownership/takeback_detector.py`)**
  - REMOTE PC 로컬 입력 감지
  - 5px 누적 이동 또는 2건 비주입 이벤트 within 100ms 윈도우
  - 주입 태그를 통한 false positive 방지

- **Input Capture & Injection (`src/eou/input/`)**
  - `MouseBackend` Protocol (pynput 기반 Windows 구현)
  - `MouseCapture`: pynput listener → asyncio 큐 브리지
  - `MouseInjector`: delta clamping with range validation
  - `CursorVisibility` Protocol + `WindowsCursorVisibility` (WH_MOUSE_LL 훅)
    - 오프스크린 파킹 좌표 `(-32000, -32000)`
    - 로컬 입력 소비 (hook callback returns 1)
    - `pre_hide_position` 복원 계약

- **Asyncio↔Thread Bridge (`src/eou/bridge.py`)**
  - `MouseEventBridge`: pynput 스레드 안전 통합
  - 256-slot 백프레셔 큐
  - `loop.call_soon_threadsafe()` 기반

- **CLI & Configuration (`src/eou/cli.py`, `src/eou/config.py`)**
  - typer 기반 `eou host` / `eou remote` 서브커맨드
  - YAML config loader (`ConfigError`, `load_config()`)
  - HOST/REMOTE 역할 전용 예시 설정 (`configs/eou.host.example.yaml`, `configs/eou.remote.example.yaml`)

- **Orchestration (`src/eou/host.py`, `src/eou/remote.py`)**
  - HOST: 마우스 capture → edge detection → OWNERSHIP_REQUEST 발신 → MOUSE_MOVE 전송
  - REMOTE: OWNERSHIP_REQUEST 수신 → GRANT 응답 → 입력 주입 → takeback 감지
  - 양측 HEARTBEAT 기반 세션 감시 (3회 연속 미수신 시 SESSION_END)
  - 전송 장애 감지 → FSM 강제 IDLE 전이

- **DI Factory (`src/eou/transport/_factory.py`)**
  - `make_tcp_transport()` 함수
  - 계층 경계 강제 (transport/ 외부는 tcp/ble 직접 임포트 금지)
  - REQ-MOUSE-TRANSPORT-003 준수

- **Meta & Integration Tests**
  - `tests/fakes/`: FakeTransport, FakeMouseBackend, FakeCursorVisibility
  - `tests/meta/test_import_boundaries.py`: 계층 경계 AST 검증
  - `tests/integration/test_e2e_loopback.py`: 전체 파이프라인 loopback 테스트
  - 8개 인수 시나리오 검증 (Scenario 1~8)

### Known Limitations

- **Windows 전용**: MVP는 Windows 10/11 (pynput, ctypes.windll 요구)
- **인증/암호화 없음**: LAN trust 모델 (BLE 단계에서 재평가)
- **WH_MOUSE_LL 훅 거부**: 안티체트 소프트웨어 또는 보안 데스크탑이 훅 설치 거부 가능
  - Fallback: 파킹만 가능, takeback 정확도 저하
- **Python 3.10 최소 버전** (개발): 타깃은 3.11+ per spec

### Quality Gates — TRUST 5

- **Tested** ✓
  - 289 tests passing, 85.34% coverage
  - REQ-to-test mapping: 122개 docstring 참조
  - 8개 인수 시나리오 full coverage
  - Hypothesis property test for codec round-trip

- **Readable** ✓
  - snake_case functions, PascalCase classes
  - 공개 API 전부 타입 힌트 + docstring
  - ruff warnings: 0

- **Unified** ✓
  - 일관된 예외 계층 (TransportError, ProtocolError, ConfigError, InvalidTransitionError)
  - async/sync 경계 명확 (FSM은 sync-only, Transport는 async-only)
  - 타입 힌트 100% (from __future__ import annotations)

- **Secured** ✓
  - 입력 검증 (codec 64 KiB, transport frame size, config unknown-key 거부)
  - Delta clamping on mouse injection
  - 하드코드 비밀 없음, subprocess/eval/exec 없음
  - LAN trust 문서화

- **Trackable** ✓
  - Conventional commits with SPEC-MOUSE-001 reference
  - 모든 REQ-ID 1:1 매핑
  - tasks.md 36/36 완성
  - progress.md 슬라이스 exit 블록 전부 완성

### Security

- 기본 바인드 `127.0.0.1` (로컬호스트)
- LAN 바인드는 명시적 CLI 플래그 필요
- 입력 경로 (codec) 64 KiB 상한 강제
- 암호화 부재는 README / spec.md Known Limitations로 문서화

### Git Commits

- Bootstrap: bd316fe
- Slice 1 (T-001..T-009): 603574a, 4fcfdc7, 64483ca
- Slice 2 (T-010..T-019): 2cc7d53, 99d513d, 3fdaaf0
- Slice 3 (T-020..T-029): 385bffc, a042889, 7d85705, af050a7, 21a5169
- Slice 4 (T-030..T-036): 1340009, ad87046, 3379034, 9ec4845, a8c6020 (final)

---

## [0.1.0] - TBD

Reserved for future releases.
