# Strategy — SPEC-MOUSE-001

엣지 트리거 마우스 소유권 전환 (TCP 트랜스포트, Windows MVP) 구현 전략. 본 문서는 Phase 1 계획 단계의 산출물이며, 구현 코드는 포함하지 않는다. TDD (RED-GREEN-REFACTOR) 사이클로 4개의 수직 슬라이스를 순차 진행한다.

---

## 1. Execution Plan Summary

본 SPEC 의 26개 REQ 를 5개 모듈(ownership, edge, takeback, transport, protocol, visibility)로 그룹핑하고, 이를 4개의 수직 슬라이스로 분해한다. **Slice 1** 은 `transport/` (ABC + TCP 구현) 과 `protocol/` (메시지 타입 + msgpack 코덱) 을 세워 REQ-MOUSE-TRANSPORT-001~005 및 REQ-MOUSE-PROTOCOL-001~006 을 커버한다. **Slice 2** 는 `ownership/state.py` (3-state FSM), `ownership/edge_detector.py` (2px/2tick dwell), 그리고 takeback 감지 로직을 붙여 REQ-MOUSE-OWNERSHIP-001~006, REQ-MOUSE-EDGE-001~005, REQ-MOUSE-TAKEBACK-001~004 를 커버한다. **Slice 3** 는 `input/capture.py`, `input/inject.py`, `input/visibility.py` (`CursorVisibility` Protocol + `WindowsCursorVisibility` ctypes 구현 + `FakeCursorVisibility` 테스트 더블) 를 붙여 REQ-MOUSE-VISIBILITY-001~005 및 injected-event 태깅 경로를 완성한다. **Slice 4** 는 `host.py` / `remote.py` / `cli.py` 에서 DI 로 모든 레이어를 조립하고 `configs/eou.example.yaml` 로더를 추가하여 Acceptance Scenarios 1·3·6·7 을 루프백 TCP 기반 통합 테스트로 검증한다. 각 슬라이스는 직전 슬라이스가 녹색 테스트로 종료된 이후에만 착수하며, 모든 신규 코드는 RED → GREEN → REFACTOR 3단계 원자 태스크로 분해된다.

---

## 2. Architecture Decisions

- **Framing 위치**: 4-byte BE unsigned length prefix 는 **transport 레이어**(`src/eou/transport/tcp.py`) 의 책임이다. `protocol/codec.py` 는 완결된 메시지 단위의 msgpack encode/decode 만 수행하며 프레이밍을 알지 못한다. 이유: REQ-MOUSE-PROTOCOL-001 은 "on the wire" 를 명시하며, BLE 트랜스포트(후속 SPEC)는 GATT chunking 을 직접 수행해야 하므로 코덱이 프레이밍에 결합되면 안 된다.
- **비동기 모델**: `asyncio` 를 transport I/O 의 단일 이벤트 루프로 사용한다. `asyncio.StreamReader/StreamWriter` 기반 TCP. 시간 제약(edge → REMOTE ≤ 250 ms, takeback ≤ 100 ms)은 asyncio 가 충분히 만족한다.
- **Thread ↔ Event Loop Bridge**: pynput listener 는 별도 `threading.Thread` 에서 구동되며, 캡처된 이벤트는 `asyncio.Queue` 에 `loop.call_soon_threadsafe(queue.put_nowait, event)` 로만 전달된다. 락 공유 금지. orchestration 에서는 `await queue.get()` 로 pull.
- **Ownership FSM 순수성**: `ownership/state.py` 의 `OwnershipState` 는 **sync, pure logic** (I/O · 시간 의존성 없음). 외부 입력 이벤트(`GRANT_RECEIVED`, `REQUEST_SENT`, `SESSION_END_RECEIVED` 등)를 받아 결정적으로 다음 상태와 방출할 side-effect 목록을 반환하는 형태. orchestration (`host.py`/`remote.py`) 가 FSM 을 돌리고 async side-effect 를 수행한다.
- **CursorVisibility Protocol**: `src/eou/input/visibility.py` 에 `CursorVisibility` 를 `typing.Protocol` 로 정의 (`hide(pre_hide_pos) -> None`, `show() -> None`, `is_hidden() -> bool`, `pre_hide_position() -> tuple[int, int] | None`, `hook_callback_count() -> int` 테스트 관측용). Windows 구현 `WindowsCursorVisibility` 는 `ctypes` + `user32` (`SetCursorPos`, `SetWindowsHookExW(WH_MOUSE_LL, ...)`, `UnhookWindowsHookEx`, `GetSystemMetrics(SM_*VIRTUALSCREEN)`) 를 래핑한다. `WH_MOUSE_LL` 훅은 전용 스레드의 `GetMessage` 루프에서만 구동된다 (R-06 대응). `FakeCursorVisibility` 는 `tests/fakes/cursor_visibility.py` 에 두고 호출 시퀀스·파크 좌표·훅 카운트를 기록하여 Slice 2/4 의 단위/통합 테스트에서 Windows API 모킹 없이 재사용된다.
- **Config 전략**: YAML → 순수 dataclass 로더. `configs/eou.example.yaml` 은 `transport`, `edges`, `thresholds` 등 단순 dict 구조만 노출. 로더(`src/eou/config.py`)는 `@dataclass(frozen=True)` 와 `typing.get_type_hints` 만 사용하며 **pydantic 은 도입하지 않는다** (tech.md 미정의 의존성이므로).
- **Layer Boundary 강제**: `transport/` 외부 모듈이 `src.eou.transport.tcp` 또는 `src.eou.transport.ble` 를 직접 import 하면 실패하는 meta-test (`tests/meta/test_import_boundaries.py`) 를 `ast` 기반으로 작성. 보완적으로 `ruff` 의 `isort` / `flake8-tidy-imports` 설정에 `banned-module-level-imports` 정책을 기록한다 (pyproject.toml, Slice 1 T-001).
- **Plaform Gate**: Windows 전용 동작(실제 `user32` 호출, 실제 `WH_MOUSE_LL` 설치, 실제 pynput listener)은 `@pytest.mark.windows` 로 마킹하고 `pytest.ini` / `pyproject.toml` 의 `markers` 등록 + `conftest.py` 의 `pytest.skip(..., allow_module_level=True)` 처리로 non-Windows CI 에서 자동 스킵. 단위 테스트는 `unittest.mock.patch` 로 `ctypes.windll.user32` / `pynput` 을 모킹하여 Linux/macOS 개발 머신에서도 녹색 유지.

---

## 3. Dependencies Finalisation

tech.md 에 정의된 런타임 의존성만 사용한다. 버전은 해당 문서의 minimum 을 그대로 고정한다.

| Purpose | Library | Min Version | Usage |
|---|---|---|---|
| Mouse capture + injection | `pynput` | 1.7.6 | `input/capture.py`, `input/inject.py` (Slice 3) |
| Screen geometry | `screeninfo` | 0.8.1 | `ownership/edge_detector.py` 화면 경계 조회 (Slice 2) |
| Wire format | `msgpack` | 1.0.7 | `protocol/codec.py` (Slice 1) |
| Config | `pyyaml` | 6.0 | `config.py` YAML 로더 (Slice 4) |
| CLI | `typer` | 0.12 | `cli.py` `eou host` / `eou remote` (Slice 4) |
| Windows helpers (optional) | `pywin32` | 306 | MVP 에서는 import 하지 않음. `pyproject.toml` 의 `[project.optional-dependencies]` 에 `windows-extra` 로 선언만 |

**테스트 의존성** (`[project.optional-dependencies].dev`):

| Purpose | Library | Min Version | Usage |
|---|---|---|---|
| Test runner | `pytest` | 8.0 | 전체 |
| Async tests | `pytest-asyncio` | 0.23 | transport 루프백, orchestration |
| Coverage | `pytest-cov` | 5.0 | 85% 게이트 |
| Property tests | `hypothesis` | 6.0 | protocol round-trip (Slice 1) |
| Linter/formatter | `ruff` | 0.5 | TRUST 5 Readable/Unified |

**명시적 제외**: `pydantic` 없음, `msgpack-numpy` 없음, `attrs` 없음, `structlog` 없음, 기타 tech.md 미정의 의존성 전부 금지. 추가가 필요하면 별도 SPEC 개정으로 다룬다.

---

## 4. Test Strategy

### 4.1 Frameworks

- `pytest` + `pytest-asyncio` + `hypothesis` + `pytest-cov`
- 단일 `pyproject.toml` 의 `[tool.pytest.ini_options]` 에 `asyncio_mode = "auto"`, `markers = ["windows: ..."]`, `testpaths = ["tests"]` 등록.

### 4.2 Directory Layout

```
tests/
├── conftest.py                         # 전역 fixtures, windows marker skip
├── fakes/
│   ├── __init__.py
│   ├── cursor_visibility.py            # FakeCursorVisibility
│   ├── transport.py                    # FakeTransport (in-memory duplex)
│   └── input.py                        # FakeMouseListener / FakeController
├── meta/
│   └── test_import_boundaries.py       # ast 기반 레이어 검사
├── unit/
│   ├── transport/
│   │   ├── test_base.py                # Transport ABC 계약
│   │   └── test_tcp_framing.py         # 4-byte BE 길이 프리픽스
│   ├── protocol/
│   │   ├── test_messages.py            # 6개 메시지 dataclass
│   │   └── test_codec.py               # msgpack encode/decode + hypothesis round-trip
│   ├── ownership/
│   │   ├── test_state.py               # FSM REQ-MOUSE-OWNERSHIP-001~006
│   │   ├── test_edge_detector.py       # REQ-MOUSE-EDGE-001~005
│   │   └── test_takeback.py            # REQ-MOUSE-TAKEBACK-001~004
│   └── input/
│       ├── test_capture.py             # pynput listener bridge
│       ├── test_inject.py              # injected event tagging window
│       ├── test_visibility_protocol.py # CursorVisibility Protocol contract
│       └── test_windows_visibility.py  # ctypes-mocked WindowsCursorVisibility
└── integration/
    ├── test_tcp_loopback.py            # 로컬 서버/클라이언트 메시지 왕복
    ├── test_config_loader.py           # YAML → dataclass
    └── test_orchestration_e2e.py       # Scenarios 1/3/6/7 루프백 E2E
```

### 4.3 Naming & Coverage

- 테스트 파일명 규칙: `test_<module>.py` 또는 `test_<module>_<aspect>.py`.
- 각 REQ 에 최소 1개의 테스트가 1:1 매핑된다 (REQ-ID 를 테스트 docstring 에 명시).
- 커버리지 게이트: `pytest --cov=src/eou --cov-fail-under=85`. `src/eou/input/visibility.py` 는 Windows API 모킹된 상태에서 85% 이상 달성.
- hypothesis profile: `settings(max_examples=200, deadline=200)` 을 `conftest.py` 에 기본값으로 등록.

### 4.4 Platform Gating

- `tests/conftest.py` 에 `pytest_collection_modifyitems` 훅으로 `@pytest.mark.windows` 아이템을 non-Windows 러너에서 자동 skip.
- CI 매트릭스(향후 Slice 4 문서화): Linux/macOS 러너는 windows marker 제외, Windows 러너는 전체 실행.

---

## 5. Risks & Mitigations

plan.md §3 의 R-01 ~ R-08 를 그대로 승계하고, 전략 수준에서 발견된 추가 리스크를 덧붙인다.

| ID | 리스크 | 영향 | 완화 |
|---|---|---|---|
| R-01 | pynput 주입 지연 (Windows SendInput 경로 튐) | 엣지 → REMOTE 250 ms 예산 초과 | 주입을 입력 스레드에서 직접 실행, p95 벤치마크 기록, `pywin32` fallback TODO |
| R-02 | Windows UAC / admin 창 위에서 주입 무시 | 특정 창 조작 불가 | MVP 는 "비관리자 세션 한정" 명문화, capture/inject 동일 권한 CLI 가이드 |
| R-03 | Transport 추상화 누출 | BLE 교체 시 상위 계층 수정 | `transport.base` 는 bytes API 만, 직접 import 금지 meta-test, BLE stub 을 MVP 에 `NotImplementedError` 로 미리 둠 |
| R-04 | takeback false-positive (드리프트·진동) | 세션 의도치 않은 종료 | 임계 config 노출, 이동평균 윈도우, E2E idle 30초 오탐 0 |
| R-05 | MVP 인증·암호화 부재 | LAN 스푸핑 | Known Limitation 명시, 기본 바인드 127.0.0.1, LAN 은 CLI 플래그 |
| R-06 | `WH_MOUSE_LL` 훅 스레드 stall | 시스템 전역 마우스 프리즈 | 전용 스레드 + `GetMessage` 루프, 콜백은 `return 1` 만, 메타는 `queue.Queue` 로 오프로드 |
| R-07 | 가상 스크린 음수 좌표 multi-monitor 클리핑 | HOST 커서가 보임 | `SM_*VIRTUALSCREEN` 조회 후 `(sm_x - 1000, sm_y - 1000)`, fallback `(-32000, -32000)` |
| R-08 | Anti-cheat / Secure Desktop 의 `WH_MOUSE_LL` 거부 | 훅 NULL, takeback 저하 | Known Limitation, `GetLastError` 로깅, `warnings.warn`, degraded fallback 진입 |
| **R-09** | **asyncio ↔ pynput 스레드 브리지 데드락** (예: pynput listener 스레드 안에서 `queue.put` 이 백프레셔로 블로킹되고, 이벤트 루프 쪽이 그 스레드가 해제하는 락을 기다림) | capture 정지, 엣지 감지 실패 | `asyncio.Queue(maxsize=256)` 유한 버퍼 + `put_nowait` 드랍 정책 (오래된 이벤트 드롭, WARN 로그), `call_soon_threadsafe` 만 사용 (직접 `await` 금지), Slice 3 T-020 계열 테스트에서 burst 1000 이벤트 드롭 수치 관측 |
| **R-10** | **pytest-asyncio event loop scope 충돌로 TCP 루프백 테스트 flakiness** | Slice 1 통합 테스트 간헐 실패 | `pytest-asyncio` `loop_scope="function"` 고정, 각 테스트마다 `asyncio.start_server` + `asyncio.open_connection` 을 `async with` 컨텍스트로 수명 관리, 포트 바인딩은 OS 랜덤(`port=0`) 사용 |
| **R-11** | **hypothesis가 msgpack 직렬화 한계(64 KiB, 특수 float)를 넘는 입력을 생성하여 round-trip 실패** | 가짜 플래키 (실제 버그 아님) | `hypothesis.strategies` 를 spec 허용 범위로 제한 (dx/dy int32 범위, ts finite float), oversize 는 별도 negative 테스트로 분리 |

---

## 6. Success Criteria (REQ × Scenario Matrix)

각 REQ 모듈의 완료는 아래 scenario 로 관측 가능하게 검증된다. 괄호 안은 검증 주체.

- **REQ-MOUSE-TRANSPORT-001~005** → Slice 1 `tests/unit/transport/test_base.py` + `test_tcp_framing.py` + `tests/integration/test_tcp_loopback.py` + `tests/meta/test_import_boundaries.py`. Acceptance Scenario **S4** (transport disconnect) 는 Slice 4 통합 테스트에서 최종 검증.
- **REQ-MOUSE-PROTOCOL-001~006** → Slice 1 `tests/unit/protocol/test_codec.py` (hypothesis round-trip, oversize, unknown type) + `test_messages.py`.
- **REQ-MOUSE-OWNERSHIP-001~006** → Slice 2 `tests/unit/ownership/test_state.py` (1:1 매핑). Acceptance Scenario **S1·S2** 는 Slice 4 E2E.
- **REQ-MOUSE-EDGE-001~005** → Slice 2 `tests/unit/ownership/test_edge_detector.py`. Acceptance Scenario **S1·S5**.
- **REQ-MOUSE-TAKEBACK-001~004** → Slice 2 `tests/unit/ownership/test_takeback.py`. Acceptance Scenario **S3·S8**.
- **REQ-MOUSE-VISIBILITY-001~005** → Slice 3 `tests/unit/input/test_visibility_protocol.py` (FakeCursorVisibility) + `test_windows_visibility.py` (ctypes-mocked). Acceptance Scenario **S6·S7·S8** 는 Slice 4 E2E 에서 FakeCursorVisibility 주입으로 검증.
- **Layer Boundary (REQ-MOUSE-TRANSPORT-003)** → `tests/meta/test_import_boundaries.py` (ast walk, Slice 1 T-009).
- **Performance (250/100/50 ms)** → Acceptance `acceptance.md` §2 의 수동 수치 덤프는 Slice 4 이후 수동 벤치 스크립트로 수집. 본 SPEC 의 Phase 1 범위에서는 벤치 스크립트 **설계**까지만 명시.

---

Version: 1.0.0 (Phase 1 planning artifact)
Last Updated: 2026-04-18
