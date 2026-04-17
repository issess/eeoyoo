# Acceptance — SPEC-MOUSE-001

본 문서는 SPEC-MOUSE-001의 **관찰 가능한 완료 기준**을 정의한다. 모든 시나리오는 구현 독립적이며, 구체 함수명·클래스명은 포함하지 않는다.

공통 전제:
- HOST / REMOTE 두 Windows 10/11 x64 PC, 동일 LAN.
- 양측 `eou` 프로세스가 기동되어 TCP 세션 HELLO 교환을 마친 상태 (state = `IDLE`).
- 설정: 엣지 임계 2 px, dwell 2 tick (기본값).

---

## 1. Given / When / Then 시나리오

### Scenario 1 — Happy-path edge transfer HOST → REMOTE (REQ-MOUSE-EDGE, REQ-MOUSE-OWNERSHIP)

- **Given** HOST 상태가 `IDLE`, REMOTE 상태가 `IDLE`, 두 노드가 LAN으로 HELLO 교환을 마친 세션 위에 있다.
- **When** HOST 사용자가 REMOTE가 배치된 방향(예: 우측) 화면 엣지로 커서를 밀어, 커서 X 좌표가 엣지 경계로부터 2 px 이내에 **연속 2 tick** 머문다.
- **Then**
  1. HOST가 REMOTE로 `OWNERSHIP_REQUEST` 메시지를 발신한다.
  2. REMOTE가 `OWNERSHIP_GRANT`로 응답한다.
  3. HOST 상태가 `CONTROLLING`, REMOTE 상태가 `CONTROLLED`로 전이된다.
  4. 이후 HOST의 마우스 물리 이동은 `MOUSE_MOVE` 프레임으로 REMOTE에 전달되어 REMOTE 커서가 이동한다.
  5. HOST 커서는 로컬 화면에서 잠기고 숨김 처리된다.
  6. 엣지 dwell 충족 시점부터 REMOTE 커서의 **첫 이동 이벤트** 발생까지 경과 시간 ≤ 250 ms.

### Scenario 2 — Return transfer REMOTE → HOST (REQ-MOUSE-EDGE, REQ-MOUSE-OWNERSHIP)

- **Given** Scenario 1이 성공적으로 끝나 HOST=`CONTROLLING`, REMOTE=`CONTROLLED` 상태이다.
- **When** HOST 사용자가 마우스를 계속 이동하여 REMOTE 측 화면의 **대칭 반환 엣지**(예: REMOTE의 좌측 엣지)로 커서를 몰아, 해당 엣지에서 2 px 이내 연속 2 tick 체류를 충족한다.
- **Then**
  1. REMOTE 측 edge detector가 반환 `OWNERSHIP_REQUEST`를 HOST로 발신한다.
  2. HOST가 `OWNERSHIP_GRANT`로 응답한다.
  3. HOST 상태가 `IDLE`, REMOTE 상태가 `IDLE`로 복귀한다.
  4. HOST 커서가 잠금 해제되고 잠기기 직전의 좌표 근방에 복원된다.
  5. 이후 HOST의 물리 이동은 더 이상 REMOTE로 전달되지 않는다 (MOUSE_MOVE 프레임 송신 중단).

### Scenario 3 — Takeback on REMOTE local input (REQ-MOUSE-TAKEBACK, REQ-MOUSE-TRANSPORT)

- **Given** Scenario 1 이후 HOST=`CONTROLLING`, REMOTE=`CONTROLLED` 상태이며 세션이 활성이다.
- **When** REMOTE PC 앞의 로컬 사용자가 물리 마우스를 움직여 **100 ms 내에 누적 ≥ 5 px 또는 비주입 이벤트 ≥ 2건**이 발생한다.
- **Then**
  1. REMOTE는 즉시 이후 도착하는 `MOUSE_MOVE` 프레임 주입을 중단한다.
  2. REMOTE가 HOST로 `SESSION_END {reason: "takeback"}`을 발신한다.
  3. REMOTE 상태가 `IDLE`로 전이한다.
  4. HOST가 `SESSION_END`를 수신하면 상태가 `IDLE`로 전이되고, HOST 커서가 잠금 해제되어 잠기기 직전의 좌표 근방에 복원된다.
  5. 최초 REMOTE 물리 입력 발생 시점부터 HOST 커서 잠금 해제까지 ≤ 100 ms.

### Scenario 4 — Transport disconnect mid-session (REQ-MOUSE-TRANSPORT, REQ-MOUSE-PROTOCOL)

- **Given** HOST=`CONTROLLING`, REMOTE=`CONTROLLED` 상태의 활성 세션이다.
- **When** 네트워크 경로가 돌연 차단되어 TCP 소켓이 peer-reset되거나, 1초 주기 `HEARTBEAT` 3회 연속 미수신 조건이 충족된다.
- **Then**
  1. HOST와 REMOTE 각각의 transport 계층이 상위에 장애를 통지한다.
  2. 양측 FSM이 50 ms 이내 `IDLE`로 강제 전이된다.
  3. HOST 커서는 잠금 해제되고 화면에 복원된다.
  4. REMOTE는 이후 도착할 수 있는 스트레이 프레임을 디코딩하지 않는다.
  5. 사용자에게는 "연결 해제" 상태만 노출되며, 프로세스 크래시는 발생하지 않는다.

### Scenario 5 — Edge touch without dwell satisfaction (negative, REQ-MOUSE-EDGE)

- **Given** HOST=`IDLE`, REMOTE=`IDLE`.
- **When** HOST 사용자가 엣지에 **단일 tick** 동안만 2 px 이내로 접근한 뒤 즉시 이탈하거나, tick 사이에 2 px 경계를 벗어났다가 재진입한다 (연속성 파괴).
- **Then**
  1. HOST는 `OWNERSHIP_REQUEST`를 발신하지 않는다.
  2. 양측 FSM은 `IDLE`을 유지한다.
  3. `MOUSE_MOVE` 프레임은 전혀 송신되지 않는다.

### Scenario 6 — HOST 커서 파킹 · 로컬 입력 소비 (REQ-MOUSE-VISIBILITY-001, REQ-MOUSE-VISIBILITY-002)

- **Given** HOST=`IDLE`, REMOTE=`IDLE`. 세션 HELLO 교환 완료. 테스트 훅 (`CursorVisibility` 의 관측 가능한 상태 및 가상 스크린 좌표 조회 API) 이 활성화되어 있다.
- **When** Scenario 1 의 엣지 조건이 충족되어 HOST FSM 이 `IDLE → CONTROLLING` 으로 전이된다. 전이 후 1초 이내에 HOST 로컬 사용자가 물리 마우스를 임의 방향으로 움직인다.
- **Then**
  1. 전이 직후 `CursorVisibility.pre_hide_position()` 이 전이 직전 좌표를 반환한다 (non-null tuple).
  2. 전이 직후 OS 커서 좌표가 가상 스크린 bounding box 바깥 (`x ≤ SM_XVIRTUALSCREEN - 1000` 또는 `(-32000, -32000)` fallback) 에 위치한다.
  3. HOST 로컬 물리 마우스 입력이 발생하더라도 HOST OS 커서 좌표는 위 park 좌표에서 움직이지 않는다 (테스트 훅이 이벤트 소비를 기록, `WH_MOUSE_LL` 콜백 호출 카운트 ≥ 1).
  4. 동일 시간대에 REMOTE 측 커서는 주입된 `MOUSE_MOVE` 에 반응하여 정상 이동하며, REMOTE OS 커서 이미지·가시성은 변경되지 않는다 (REQ-MOUSE-VISIBILITY-004 확인).

### Scenario 7 — Normal return edge 시 커서 복원 (REQ-MOUSE-VISIBILITY-003 / 정상 경로)

- **Given** Scenario 6 완료 상태 (HOST=`CONTROLLING`, REMOTE=`CONTROLLED`). `pre_hide_position = (px, py)` 가 기록되어 있다.
- **When** Scenario 2 의 반환 엣지 조건이 충족되어 HOST FSM 이 `CONTROLLING → IDLE` 로 전이된다.
- **Then**
  1. `WH_MOUSE_LL` 훅이 해제되었다 (테스트 훅으로 `UnhookWindowsHookEx` 호출 관측, 훅 설치 카운트 감소를 확인).
  2. HOST OS 커서가 `(px, py)` 좌표로 복원된다 (정확히 동일 좌표, ±0 px).
  3. FSM 전이 타임스탬프와 커서 복원 완료 타임스탬프의 차이 ≤ **50 ms** (p95, 20회 반복).
  4. 이후 HOST 로컬 물리 입력이 다시 HOST 데스크탑에 정상 반영된다 (훅 소비 해제).

### Scenario 8 — Takeback 경로에서도 동일한 복원 (REQ-MOUSE-VISIBILITY-003 / takeback 경로)

- **Given** Scenario 6 완료 상태 (HOST=`CONTROLLING`, REMOTE=`CONTROLLED`). `pre_hide_position = (px, py)`.
- **When** Scenario 3 의 REMOTE 로컬 입력이 발생하여 REMOTE 가 HOST 로 `SESSION_END {reason: "takeback"}` 를 송신하고, HOST FSM 이 `CONTROLLING → IDLE` 로 전이된다.
- **Then**
  1. HOST OS 커서가 동일한 `(px, py)` 좌표로 복원된다 (takeback 경로와 정상 경로가 동일한 복원 계약을 사용).
  2. `WH_MOUSE_LL` 훅이 해제된다.
  3. 최초 REMOTE 물리 입력 시점부터 HOST 커서 복원 완료까지 전체 경로 ≤ 150 ms (= takeback 100 ms + restore 50 ms, p95).
  4. Transport disconnect 경로(Scenario 4) 로 트리거된 `CONTROLLING → IDLE` 전이에서도 동일 복원이 수행된다 — 테스트에서 연결 차단 주입으로 별도 검증.

---

## 2. 성능 수용 기준 (Performance Acceptance)

| 측정 항목                                        | 타깃              | 측정 방법 |
|--------------------------------------------------|-------------------|-----------|
| 엣지 dwell 충족 → REMOTE 커서 첫 이동             | ≤ 250 ms (p95)    | 같은 LAN에서 20회 반복, HOST dwell 만족 타임스탬프와 REMOTE inject 타임스탬프의 차이 |
| REMOTE 로컬 입력 → HOST 커서 잠금 해제            | ≤ 100 ms (p95)    | REMOTE 물리 이벤트 발생 시간과 HOST unlock 이벤트 시간 차이, 20회 반복 |
| Cursor restore latency (CONTROLLING → IDLE 전환 후) | ≤ 50 ms (p95)   | FSM `CONTROLLING → IDLE` 전이 타임스탬프와 OS 커서가 `pre_hide_position` 으로 복원된 타임스탬프의 차이, 20회 반복 (Scenario 7·8 공통) |
| `MOUSE_MOVE` 송출 빈도 (CONTROLLING 중 활발 이동) | ≥ 120 Hz 지속     | HOST 송신 프레임 수 / 초 샘플링 |
| 1시간 연속 가동                                   | 크래시·hang 0회   | 60분 load 테스트 후 양측 프로세스 정상 |

---

## 3. 품질 게이트 (Quality Gates — TRUST 5)

- **Tested**
  - 단위 테스트 커버리지 ≥ **85%** (pytest + coverage).
  - `src/eou/input/visibility.py` 는 Windows API 를 `unittest.mock.patch` 로 모킹한 상태에서 단위 테스트 커버리지 ≥ **85%** 를 달성한다 (실제 훅 설치는 E2E 단계에서만 실행).
  - `protocol/codec` 모듈은 `hypothesis` 왕복 속성을 포함한다.
  - `ownership/state`의 REQ-MOUSE-OWNERSHIP-001..006 각 요구사항에 1:1 대응하는 단위 테스트가 존재한다.
  - REQ-MOUSE-VISIBILITY-001..005 각 요구사항에 1:1 대응하는 단위 테스트가 존재한다 (FakeCursorVisibility 기반 · 실 ctypes mocking 기반 각 1개 이상).
  - `acceptance.md`의 8개 시나리오(기존 5 + visibility 3)는 E2E 테스트 또는 수동 검증 절차로 실행되고, 결과(로그/스크린캡처)가 기록된다.
- **Readable**
  - 모든 공개 API에 타입 힌트와 독스트링이 존재한다 (`from __future__ import annotations`).
  - `ruff` 경고 0건.
- **Unified**
  - 포맷터 (`black` 또는 ruff-format) 위반 0건.
- **Secured**
  - 기본 바인드 주소는 `127.0.0.1`. LAN 바인드는 명시적 CLI 플래그가 있을 때만.
  - 외부 입력 경로(디코더)가 ≤ 64 KiB 프레임 상한을 강제한다.
  - 암호화 부재는 README / `plan.md` Known Limitation으로 문서화된다.
- **Trackable**
  - 커밋 메시지에 `SPEC-MOUSE-001` 또는 관련 REQ-ID를 참조한다.

---

## 4. 레이어링 수용 기준 (Architectural Acceptance)

- **Transport 고립**
  - `src/eou/transport/`는 `protocol`, `ownership`, `input` 중 어느 것도 import 하지 않는다.
  - `src/eou/transport/` 외부 모듈이 `transport.tcp` 또는 `transport.ble`를 **직접** import 하면 레이어 검사 테스트가 실패한다.
  - `transport/` 패키지는 상위 레이어 없이 단독 import/실행이 가능하며, 루프백 통합 테스트만으로 완전히 검증된다.
- **DI 검증**
  - `host.py` / `remote.py` 단위 테스트에서 `Transport` mock을 주입하여 FSM·코덱 경로를 OS 의존성 없이 검증할 수 있다.

---

## 5. 제외 확인 (Exclusions Re-confirmation)

아래 시나리오는 **본 SPEC의 수용 기준에 포함되지 않는다** (spec.md §3 동일 목록 요약):

- 키보드 이벤트 공유 동작
- 클립보드 공유 동작
- BLE 트랜스포트 실제 전송
- macOS / Linux 실행
- 3대 이상 노드 라우팅
- 인증/암호화 관련 수용 기준
- GUI 설정 앱 동작
- REMOTE 측 커서 이미지/가시성 변경 동작 (REQ-MOUSE-VISIBILITY-004)
- 시스템 전역 `ShowCursor(FALSE)` / `SetSystemCursor` 동작
- 오버레이/트레이 가시성 인디케이터 동작

이 항목들에 대한 테스트 또는 수용 기준은 작성하지 않으며, 향후 별도 SPEC에서 다룬다.

---

## 6. Definition of Done (최종)

- [ ] Scenario 1 ~ 8 전부 PASS (Scenario 1·3·7·8 은 p95 성능 타깃 포함).
- [ ] 모든 요구사항 ID (REQ-MOUSE-OWNERSHIP-00x, REQ-MOUSE-EDGE-00x, REQ-MOUSE-TAKEBACK-00x, REQ-MOUSE-TRANSPORT-00x, REQ-MOUSE-PROTOCOL-00x, REQ-MOUSE-VISIBILITY-00x)에 대응하는 테스트가 존재한다.
- [ ] TRUST 5 게이트 통과.
- [ ] `plan.md`의 M1~M6 마일스톤 완료 (M4.5 Cursor Visibility 포함).
- [ ] 1시간 연속 가동 테스트 통과 (CONTROLLING ↔ IDLE 반복 전이 중 커서 복원 누락 0회).
- [ ] README / `configs/eou.example.yaml` 갱신 (Known Limitations 포함 — Anti-cheat `WH_MOUSE_LL` 거부 케이스 명시).
