# Plan — SPEC-MOUSE-001

엣지 트리거 마우스 소유권 전환 (TCP 트랜스포트, Windows MVP) 구현 계획.

> **원칙**
> - 시간 추정 대신 **Priority (High / Medium / Low)** 와 **Phase ordering** 만 사용한다.
> - 기술 스택은 `.moai/project/tech.md`를 단일 원본으로 참조하며 본 문서에 중복 기재하지 않는다.

---

## 1. 접근 방식 (Technical Approach)

### 1.1 전체 전략

1. **트랜스포트 시드 먼저**: `Transport` ABC와 TCP 구현, 그리고 루프백 기반 통합 테스트를 먼저 세운다. 이후의 모든 계층은 이 ABC를 모킹하여 독립 검증한다.
2. **프로토콜과 상태 머신 분리 개발**: `protocol/`은 pure function 성격으로 개발하며 `hypothesis`로 왕복 속성 검증을 한다. `ownership/` 상태 머신은 transport·OS에 의존하지 않는 순수 FSM으로 테스트한다.
3. **입력 계층은 가장 늦게 통합**: pynput은 스레드·권한 이슈가 많아, 앞선 순수 계층 검증이 끝난 뒤 최소 어댑터로 붙인다.
4. **HOST/REMOTE orchestration**: 최종적으로 `host.py`, `remote.py`가 위 계층을 DI로 조립한다.

### 1.2 아키텍처 요점

- `capture` 스레드 → `asyncio` 이벤트 루프 경계는 `asyncio.Queue` + `loop.call_soon_threadsafe`로만 통신한다 (락 공유 금지).
- 주입된 이벤트와 물리 이벤트를 구분하기 위해 `inject.py`가 주입한 이벤트에는 "직전 주입 타임스탬프/위치" 윈도우를 유지하고, `capture.py`가 해당 윈도우 내 이벤트를 injected로 태깅한다.
- 엣지 감지는 `asyncio` 타이머 기반이 아닌, 캡처 이벤트에 의해 구동되며 dwell 카운터만 유지한다.

### 1.3 참조 기술

기술 스택과 라이브러리 버전은 `.moai/project/tech.md` 의 **Dependencies** 및 **Performance Targets** 섹션을 참조한다.

---

## 2. 마일스톤 (Priority-ordered)

각 마일스톤은 직전 마일스톤이 **녹색 테스트로 종료된 이후**에만 착수한다. 내부 과제는 병렬 실행 가능 여부를 표기한다.

### Milestone M1 — Transport Seam (Priority: High)

- **M1-T1** `transport/base.py`에 `Transport` ABC 정의 (connect/send/recv/close, 타입 힌트 포함).
- **M1-T2** `transport/tcp.py` — `asyncio.StreamReader/Writer` 기반 구현, 4-byte BE 길이 프리픽스 프레이밍 포함.
- **M1-T3** 루프백 통합 테스트: 같은 프로세스 내 서버·클라이언트가 임의 크기 프레임을 교환하고 순서·무결성이 보존됨을 검증.
- **M1-T4** 레이어 위반 방지 테스트: `transport/` 밖의 모듈이 `transport.tcp`를 직접 import 하면 실패하는 `ast`-기반 lint 테스트.

### Milestone M2 — Protocol & Codec (Priority: High, parallel with M1-T3/T4)

- **M2-T1** `protocol/messages.py`의 dataclass/TypedDict 정의 (HELLO, MOUSE_MOVE, OWNERSHIP_REQUEST/GRANT, SESSION_END, HEARTBEAT).
- **M2-T2** `protocol/codec.py`: msgpack encode/decode + unknown-type/oversize 거부.
- **M2-T3** `hypothesis` 기반 왕복 속성 테스트 (임의 MouseMove · 랜덤 바이트 리젝션).

### Milestone M3 — Ownership FSM (Priority: High)

- **M3-T1** `ownership/state.py`: IDLE / CONTROLLING / CONTROLLED FSM, 이벤트 enum과 전이 매트릭스.
- **M3-T2** 전이 단위 테스트: 본 SPEC의 REQ-MOUSE-OWNERSHIP-001..006에 1:1 대응하는 테스트.
- **M3-T3** `ownership/edge_detector.py`: 엣지 근접 + dwell 카운터 로직 (프로토콜에 독립적, 콜백 방식).
- **M3-T4** 엣지 감지 테스트: REQ-MOUSE-EDGE-001..005 대응.

### Milestone M4 — Input Capture & Injection (Priority: Medium)

- **M4-T1** `input/capture.py`: pynput listener → `asyncio.Queue` 브리지. 주입 ID 태깅 루틴 포함.
- **M4-T2** `input/inject.py`: `pynput.mouse.Controller` 래핑, 주입 윈도우 기록.
- **M4-T3** takeback 감지 로직: REQ-MOUSE-TAKEBACK-001..004 대응 테스트 (fake listener로 검증).

### Milestone M4.5 — Cursor Visibility 구현 (Priority: High — blocks CONTROLLING mode end-to-end)

본 마일스톤은 REQ-MOUSE-VISIBILITY-001..005 를 구현한다. 상태 머신(M3)과 입력 계층(M4)이 모두 설 때 즉시 붙일 수 있도록 인터페이스는 M3-T1 직후 확정하고(= 착수 가능), OS-dependent 구현은 M4 완료 직후 통합한다. 이 마일스톤이 녹색이 되기 전까지 M5 orchestration 은 HOST 커서를 숨기지 못하므로 E2E PASS 가 불가능하다.

- **M4.5-T1** `src/eou/input/visibility.py` 내부에 `CursorVisibility` 프로토콜 (ABC) 정의. 인터페이스는 `hide(ownership_state) -> None` / `show() -> None` / `is_hidden() -> bool` / `pre_hide_position() -> tuple[int, int] | None` 등 가시성 상태의 **관측 가능한** 계약만 노출한다. OS API는 타입으로 노출하지 않는다 (macOS/Linux swap seam).
- **M4.5-T2** Windows 구현 (`WindowsCursorVisibility`): `ctypes` 기반 `user32.SetCursorPos` 호출로 커서 파킹 + `SetWindowsHookExW(WH_MOUSE_LL, ...)` 설치. 훅 콜백은 전달받은 이벤트 구조를 **소비**(return 1)한다. 언인스톨은 `UnhookWindowsHookEx`.
- **M4.5-T3** 훅 스레드 모델: `WH_MOUSE_LL` 콜백은 훅을 설치한 **바로 그 스레드의 메시지 루프**에서 디스패치된다. 따라서 전용 스레드에서 `GetMessage(&msg, ...)` 루프를 돌린다. asyncio 이벤트 루프와는 `asyncio.Queue` + `call_soon_threadsafe` 로만 통신. `hide()` / `show()` 호출은 멱등(idempotent)이어야 하며, 중복 호출 시 추가 훅을 설치하지 않고 current state 를 보존한다.
- **M4.5-T4** `OwnershipState` 전이 이벤트 구독: FSM 이 `IDLE → CONTROLLING` / `CONTROLLING → IDLE` 이벤트를 방출하면 `CursorVisibility.hide()` / `show()` 가 호출되도록 orchestration (M5-T1) 에서 wire-up 한다. 본 마일스톤 단계에서는 fake FSM 으로 단위 레벨 검증까지만 수행.
- **M4.5-T5** 테스트 하니스: `FakeCursorVisibility` (in-memory, 호출 시퀀스 기록) 를 제공하여 M3 의 `OwnershipState` 단위 테스트가 OS API 를 모킹 없이 사용할 수 있게 한다. Windows 실제 구현에 대한 테스트는 `ctypes` 호출을 `unittest.mock.patch` 로 래핑하여 `user32` 함수가 기대한 인자로 호출되었는지만 검증 (실제 훅 설치는 E2E M6 에서만).

### Milestone M5 — HOST / REMOTE Orchestration (Priority: Medium)

- **M5-T1** `host.py` — transport·codec·FSM·capture·inject의 조립, 시그널/종료 핸들링.
- **M5-T2** `remote.py` — 미러 구조, REMOTE 측 edge 감지 및 takeback 반영.
- **M5-T3** `cli.py`: `eou host` / `eou remote` 하위 명령 + `configs/eou.example.yaml` 로딩.

### Milestone M6 — End-to-End Validation (Priority: Medium)

- **M6-T1** 로컬 루프백 E2E: 동일 머신 두 인스턴스로 엣지 전환 시나리오 통과.
- **M6-T2** 2-호스트 LAN 테스트 (수동 스크립트 + 기록된 수치 덤프): 엣지 250 ms / takeback 100 ms 타깃 검증.

### Milestone M7 — Polishing (Priority: Low)

- **M7-T1** 로그/지표 출력(Hz, 지연, 드롭)만 추가하는 경량 observability 모듈.
- **M7-T2** 문서화 sync: README 사용법, 기본 config.
- **M7-T3** 알려진 제약 문서화 (pynput 권한, UAC, 안티치트 충돌).

---

## 3. 리스크 분석 (Risks)

| ID   | 리스크                                              | 영향                                 | 완화 방안 |
|------|-----------------------------------------------------|--------------------------------------|-----------|
| R-01 | **pynput 주입 지연** — Windows에서 SendInput 경로가 OS 부하에 따라 튈 수 있음 | 엣지 → REMOTE 커서 시작 시간이 250 ms 예산 초과 | (a) 주입 호출을 입력 스레드에서 직접 실행, (b) 내부 벤치마크로 p95 측정, (c) 초과 시 `pywin32` 직접 SendInput fallback 경로 TODO 로 기록 |
| R-02 | **Windows UAC / admin 요구** — 일부 상승된 창(관리자 앱) 위로 커서 주입이 무시됨 | REMOTE 쪽에서 특정 창에 대해 조작 불가 | MVP는 "비관리자 세션 한정" 제약으로 명문화, capture/inject 양측 모두 동일 권한 레벨로 실행하는 CLI 가이드 문서화 |
| R-03 | **트랜스포트 추상화 누출** — 상위 계층이 TCP 세부(streamWriter.drain 등)를 암묵 의존 | BLE 교체 시 상위 계층 수정 필요 | (a) `transport.base`는 bytes 인터페이스만 노출, (b) 외부 모듈의 직접 import 금지 lint (M1-T4), (c) BLE stub을 MVP 단계에서 `raise NotImplementedError`로 미리 두고 통합 테스트에서 DI 교체 가능성 검증 |
| R-04 | **takeback false-positive** — 광마우스 드리프트 · 바이브레이션으로 5 px 임계 오탐 | 세션이 의도치 않게 종료, UX 저해 | 임계(5 px / 2 events / 100 ms)를 config로 노출, 윈도우를 이동평균으로 운영, E2E 테스트에서 idle 30초 동안 오탐 0회를 검증 |
| R-05 | **MVP 인증·암호화 부재** — LAN 내 스푸핑으로 주입 가능 | 보안 취약. 공용 네트워크 사용 금지. | (a) 본 SPEC의 Known Limitation으로 명시, (b) 기본 바인드를 127.0.0.1 루프백으로 하고 LAN 모드는 명시적 CLI 플래그로만 허용, (c) BLE 페어링 단계 SPEC에서 암호화 재도입 |
| R-06 | **`WH_MOUSE_LL` 훅 스레드 메시지 루프 stall** — `SetWindowsHookExW` 로 설치된 저수준 마우스 훅은 설치 스레드의 메시지 루프에서만 콜백이 디스패치됨. 해당 스레드가 블로킹 호출(파일 I/O·GIL-heavy Python 로직·긴 락 대기)에 빠지면 시스템 전역 마우스 입력이 stall 되어 치명적 UX 저하 발생 | HOST 전체 마우스가 수 초간 먹히는 프리즈, OS 가 훅을 강제 해제 | (a) 훅은 **전용 스레드** 위에서만 `GetMessage` 루프와 함께 구동, (b) 콜백 내부에서는 `return 1` 외 어떤 Python 로직도 수행하지 않고, takeback/경로 판단에 필요한 메타는 `queue.Queue` 로 다른 스레드에 넘긴 뒤 즉시 반환, (c) Integration 테스트에서 훅 설치 상태로 500 ms sleep 후 시스템 마우스가 여전히 수 ms 응답임을 수동 기록 |
| R-07 | **가상 스크린 음수 좌표 multi-monitor 클리핑** — `(-32000, -32000)` 은 역사적으로 가상 스크린 바깥이지만, 다중 모니터 · 음수 가상 좌표를 갖는 세팅(왼쪽 외곽 모니터)에서는 실제 보이는 영역에 클리핑될 수 있음 | HOST 커서가 `CONTROLLING` 중에도 특정 모니터에 그려져 UX 저해 | 런타임에 `GetSystemMetrics(SM_XVIRTUALSCREEN)` / `GetSystemMetrics(SM_YVIRTUALSCREEN)` / `SM_CXVIRTUALSCREEN` / `SM_CYVIRTUALSCREEN` 를 조회하여 가상 스크린 box 의 **좌상단에서 1000 px 바깥**, 즉 `(sm_x_virtual - 1000, sm_y_virtual - 1000)` 을 park 좌표로 계산. `(-32000, -32000)` 은 fallback. |
| R-08 | **Anti-cheat / Secure Desktop 이 `WH_MOUSE_LL` 설치 거부** — 일부 안티치트·UAC 상승 창·보안 데스크탑(e.g. Ctrl+Alt+Del 화면)은 저수준 훅 설치를 거부하거나 즉시 unhook | `SetWindowsHookExW` 가 NULL 반환. 커서 파킹만으로는 HOST 로컬 마우스 움직임이 여전히 HOST 데스크탑에 반영됨 | (a) Known Limitation 으로 문서화 (`plan.md` M7-T3), (b) `SetWindowsHookExW` NULL 반환 시 `GetLastError` 를 로그에 남기고 `warnings.warn` 으로 사용자에게 고지한 뒤, `SetCursorPos` 파킹 + 폴링 기반 원복 루프로 degraded fallback 모드 진입 — takeback 정확도가 저하되므로 로그 WARN 레벨로 명시 |

---

## 4. 테스트 전략 요약

- 단위 테스트 우선: FSM, codec, edge detector, takeback detector는 OS 의존성 없이 100% 커버리지 목표.
- `hypothesis`: 프로토콜 왕복 및 edge detector의 임계 조건 exploration.
- `pytest-asyncio`: transport 루프백과 orchestration.
- 통합 테스트는 GitHub Actions에서 pynput/screen 의존성이 없는 플로우만 실행하고, E2E는 로컬 수동 러너로 분리.
- 커버리지 타깃 85%+ (TRUST 5 준수).

---

## 5. mx_plan — MX Tag 배치 계획

@MX:ANCHOR 후보 (high fan_in · 불변 계약):

- `src/eou/transport/base.py :: Transport` — 모든 상위 계층이 의존하는 seam. ABC 시그니처는 계약.
- `src/eou/ownership/state.py :: OwnershipState` — FSM 전이 매트릭스. 상태/전이 변경은 contract 변경.
- `src/eou/protocol/codec.py :: decode_frame` — 모든 수신 경로가 통과하는 단일 진입점.
- `src/eou/protocol/codec.py :: encode_frame` — 모든 송신 경로가 통과하는 단일 진입점.
- `src/eou/input/visibility.py :: CursorVisibility` — HOST 측 모든 가시성 조작의 유일한 seam. macOS / Linux 교체를 위한 불변 인터페이스 (v0.2.0 신규).

@MX:WARN 후보 (위험 패턴):

- `src/eou/input/capture.py` 전체 모듈 — **별도 스레드에서 asyncio 이벤트 루프로 크로스 포스팅**. `call_soon_threadsafe` 누락 시 즉시 레이스.
- `src/eou/input/inject.py` — 주입 이벤트 태깅 윈도우. 윈도우 크기 오설정 시 takeback false-negative.
- `src/eou/ownership/edge_detector.py` — dwell 카운터가 스레드 컨텍스트에 따라 갱신되므로 원자성 주의.
- `src/eou/transport/tcp.py` — `StreamWriter.drain()` 백프레셔 경로. 취소 처리 누락 시 hang 가능.
- `src/eou/input/visibility.py :: _ll_mouse_hook_callback` (Windows 구현 내부) — **커널이 스폰한 메시지 루프 스레드**에서 호출됨. 블로킹 I/O · GIL-heavy 로직 · 긴 락 대기 금지. R-06 참조. `@MX:REASON` 은 "훅 스레드 stall 시 시스템 전역 마우스 입력이 프리즈됨" 을 명시.

@MX:TODO 후보:

- `src/eou/transport/ble.py` — stub 파일. MVP에서는 `raise NotImplementedError` + `@MX:TODO` 태그로 후속 SPEC 지시.
- 관리자 권한 창에 대한 주입 실패 로깅 경로 — MVP에서는 로그만 남기고 향후 `pywin32` fallback과 연결.

@MX:NOTE 후보:

- `host.py`, `remote.py`의 조립 지점 — DI 순서와 라이프사이클의 의도 설명.
- `edge_detector`의 dwell 기본값(2 tick) 선택 이유.

---

## 6. 완료 정의 (Definition of Done — 요약)

- 본 문서 M1~M6 항목이 전부 녹색 (M4.5 포함).
- `acceptance.md`의 8개 G/W/T 시나리오 전부 통과 (기존 5개 + visibility 3개).
- 커버리지 85%+, `transport/` 패키지가 상위 계층 없이 단독 테스트·모킹 가능. `src/eou/input/visibility.py` 도 모킹된 Windows API 로 단독 85%+ 커버 가능.
- 엣지 전환 ≤ 250 ms, takeback ≤ 100 ms, **커서 복원 ≤ 50 ms** (LAN, 개발자 워크스테이션 측정).
