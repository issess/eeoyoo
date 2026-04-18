---
id: SPEC-MOUSE-001
version: 0.2.0
status: implemented
created: 2026-04-18
updated: 2026-04-19
author: senicy
priority: high
issue_number: 0
---

# SPEC-MOUSE-001: Edge-triggered mouse ownership transfer over pluggable transport

## HISTORY

| Version | Date       | Author | Change                                 |
|---------|------------|--------|----------------------------------------|
| 0.1.0   | 2026-04-18 | senicy | Initial draft. MVP 범위 정의. 5개 REQ 모듈 작성. |
| 0.2.0   | 2026-04-18 | senicy | REQ-MOUSE-VISIBILITY 모듈 추가 (5개 요구사항). HOST 측 커서 숨김 방식을 오프스크린 파킹 `(-32000, -32000)` + `WH_MOUSE_LL` 저수준 훅 소비로 확정. REMOTE 측 커서 가시성은 OS 기본값 유지(비간섭). `pre_hide_position` 복원 계약 및 `src/eou/input/visibility.py` 신설. Exclusions에 REMOTE 커서 조작·전역 ShowCursor·오버레이 인디케이터 명시. |
| 0.2.0-impl | 2026-04-19 | senicy | Implementation complete (v0.2.0). 289 tests, 85.34% coverage. Commits bd316fe..a8c6020. |

---

## 1. 개요 (Overview)

본 SPEC은 EOU 프로젝트의 MVP 핵심 기능인 **두 대의 Windows PC 간 마우스 소유권의 엣지 트리거 자동 전환**을 정의한다. HOST PC에서 REMOTE PC로 커서 제어권이 넘어가고, REMOTE PC에서 물리적 사용자 입력이 감지되면 즉시 HOST로 제어권이 반납되는 시나리오를 다룬다. 트랜스포트 계층은 TCP로 구현하되, 장래의 BLE 트랜스포트 교체를 가능하게 하기 위해 `Transport` ABC 뒤에서 주입된다.

### 1.1 관련 컴포넌트

- `src/eou/transport/base.py` — Transport ABC
- `src/eou/transport/tcp.py` — MVP TCP 구현
- `src/eou/protocol/messages.py` — 메시지 타입 정의
- `src/eou/protocol/codec.py` — 길이 프리픽스 + msgpack 코덱
- `src/eou/ownership/state.py` — 소유권 상태 머신
- `src/eou/ownership/edge_detector.py` — 스크린 엣지 감지기
- `src/eou/input/capture.py` — 로컬 마우스 캡처
- `src/eou/input/inject.py` — 원격 마우스 주입
- `src/eou/input/visibility.py` — HOST 커서 가시성/파킹/로컬 입력 소비 (신규, v0.2.0)
  - `CursorVisibility` 추상화를 통해 OS API (Windows `user32.SetCursorPos`, `SetWindowsHookExW(WH_MOUSE_LL)`)만 얇게 래핑. macOS / Linux 교체를 위한 seam.

### 1.2 용어 정의

- **HOST**: 로컬 마우스/키보드가 직접 연결된 PC
- **REMOTE**: HOST의 입력을 주입받아 커서가 움직이는 PC
- **OWNERSHIP**: 어느 PC의 커서가 로컬 하드웨어 입력에 반응할지를 결정하는 제어권
- **TAKEBACK**: REMOTE의 로컬 사용자가 물리 입력을 발생시켰을 때 소유권이 HOST로 즉시 반환되는 동작
- **EDGE TRIGGER**: HOST 또는 REMOTE 커서가 설정된 화면 경계에 일정 조건으로 근접한 시점

---

## 2. EARS 요구사항 (Requirements)

### REQ-MOUSE-OWNERSHIP — 소유권 상태 머신 (State-driven + Event-driven)

**REQ-MOUSE-OWNERSHIP-001 (Ubiquitous):**
The ownership state machine **shall** maintain exactly one of three mutually exclusive states per node: `IDLE`, `CONTROLLING`, `CONTROLLED`.

**REQ-MOUSE-OWNERSHIP-002 (Event-driven):**
**When** a node receives an `OWNERSHIP_GRANT` message and the local state is `IDLE`, the state machine **shall** transition to `CONTROLLED`.

**REQ-MOUSE-OWNERSHIP-003 (Event-driven):**
**When** a node sends an `OWNERSHIP_REQUEST` and receives the corresponding `OWNERSHIP_GRANT`, the state machine **shall** transition from `IDLE` to `CONTROLLING`.

**REQ-MOUSE-OWNERSHIP-004 (Event-driven):**
**When** a node in `CONTROLLING` or `CONTROLLED` state receives or sends a `SESSION_END` message, the state machine **shall** transition to `IDLE` within 50 ms.

**REQ-MOUSE-OWNERSHIP-005 (State-driven):**
**While** a node is in state `CONTROLLED`, the local OS cursor **shall** be locked (position-frozen) and hidden; upon transition to `IDLE`, the cursor **shall** be unlocked and restored to its last pre-`CONTROLLED` screen coordinates.

**REQ-MOUSE-OWNERSHIP-006 (Unwanted-behaviour):**
**If** a node receives an `OWNERSHIP_GRANT` while already in `CONTROLLING` state, **then** the state machine **shall** discard the grant and emit a `SESSION_END {reason: "conflict"}` to the peer.

---

### REQ-MOUSE-EDGE — 엣지 감지 및 전환 트리거 (Event-driven)

**REQ-MOUSE-EDGE-001 (Ubiquitous):**
The edge detector **shall** sample the local cursor position at no less than 120 Hz while the node is in `IDLE` or `CONTROLLING` state.

**REQ-MOUSE-EDGE-002 (Event-driven):**
**When** the HOST cursor remains within the configured edge proximity threshold (default: 2 px) of a configured transfer edge for at least the configured dwell count (default: 2 consecutive poll ticks), the edge detector **shall** emit an `OWNERSHIP_REQUEST` toward the peer on that edge.

**REQ-MOUSE-EDGE-003 (State-driven):**
**While** the node is in `CONTROLLED` state, the edge detector on the controlled side **shall** monitor the symmetric return edge using the same threshold and dwell rules, and **shall** emit a return `OWNERSHIP_REQUEST` toward HOST when the threshold is satisfied.

**REQ-MOUSE-EDGE-004 (Optional-feature):**
**Where** a configuration profile supplies per-edge overrides (pixel threshold and dwell count), the edge detector **shall** apply those overrides in place of the defaults for the specified edges only.

**REQ-MOUSE-EDGE-005 (Unwanted-behaviour):**
**If** the cursor touches an edge but the dwell condition is not satisfied (fewer consecutive ticks than the threshold, or a gap between ticks), **then** the edge detector **shall not** emit an `OWNERSHIP_REQUEST`.

---

### REQ-MOUSE-TAKEBACK — 로컬 입력 감지에 의한 제어권 반납 (Event-driven + Unwanted-behaviour)

**REQ-MOUSE-TAKEBACK-001 (Event-driven):**
**When** a node in `CONTROLLED` state observes local physical mouse input producing either (a) cumulative movement of at least 5 pixels or (b) at least 2 discrete non-injected input events within a 100 ms window, the takeback detector **shall** trigger a takeback action.

**REQ-MOUSE-TAKEBACK-002 (Event-driven):**
**When** a takeback is triggered, the node **shall** stop accepting further injected input events, send a `SESSION_END {reason: "takeback"}` message to the peer, and transition the local state machine to `IDLE` within 100 ms of the originating local input event.

**REQ-MOUSE-TAKEBACK-003 (Ubiquitous):**
The takeback detector **shall** distinguish injected events (originated from `MOUSE_MOVE` messages) from physical events such that injected events do not themselves trigger a takeback.

**REQ-MOUSE-TAKEBACK-004 (Unwanted-behaviour):**
**If** the node is in `IDLE` or `CONTROLLING` state, **then** the takeback detector **shall not** emit any takeback signal regardless of local input activity.

---

### REQ-MOUSE-TRANSPORT — 트랜스포트 추상화 및 DI (Ubiquitous + Unwanted-behaviour)

**REQ-MOUSE-TRANSPORT-001 (Ubiquitous):**
The system **shall** expose a `Transport` abstract base class in `src/eou/transport/base.py` providing asynchronous `connect(endpoint)`, `send(frame: bytes)`, `recv() -> bytes`, and `close()` operations.

**REQ-MOUSE-TRANSPORT-002 (Ubiquitous):**
All components outside the `src/eou/transport/` package **shall** depend only on the `Transport` ABC and **shall** receive concrete transport instances via dependency injection (constructor parameter or factory).

**REQ-MOUSE-TRANSPORT-003 (Unwanted-behaviour):**
**If** any module located outside `src/eou/transport/` imports `src.eou.transport.tcp` or `src.eou.transport.ble` directly, **then** the build-time layer check **shall** fail the corresponding test.

**REQ-MOUSE-TRANSPORT-004 (Event-driven):**
**When** the transport layer detects an unrecoverable I/O failure (peer closed, connection reset, write timeout exceeding 500 ms) during an active session, the transport **shall** surface the failure to its owner, which **shall** force the ownership state machine to `IDLE` and restore local cursor control.

**REQ-MOUSE-TRANSPORT-005 (Optional-feature):**
**Where** a future BLE transport is supplied, only the contents of `src/eou/transport/` **shall** be modified; the ownership, protocol, and input layers **shall** remain unchanged.

---

### REQ-MOUSE-PROTOCOL — 와이어 프로토콜 및 프레이밍 (Ubiquitous + Event-driven)

**REQ-MOUSE-PROTOCOL-001 (Ubiquitous):**
Every protocol frame on the wire **shall** use a 4-byte big-endian unsigned length prefix followed by a msgpack-encoded payload. The length prefix **shall** indicate payload byte count exclusive of the prefix itself.

**REQ-MOUSE-PROTOCOL-002 (Ubiquitous):**
The protocol **shall** support at minimum the following message types, each encoded as a msgpack map with a `type` field: `HELLO`, `MOUSE_MOVE`, `OWNERSHIP_REQUEST`, `OWNERSHIP_GRANT`, `SESSION_END`, `HEARTBEAT`.

**REQ-MOUSE-PROTOCOL-003 (Ubiquitous):**
A `MOUSE_MOVE` message **shall** carry the fields `dx: int`, `dy: int`, optional `abs_x: int`, optional `abs_y: int`, and `ts: float` (sender-side monotonic seconds).

**REQ-MOUSE-PROTOCOL-004 (Event-driven):**
**When** a node is in `CONTROLLING` state and captures local cursor movement, the node **shall** emit a `MOUSE_MOVE` message to the peer within 10 ms of the OS input event timestamp.

**REQ-MOUSE-PROTOCOL-005 (Event-driven):**
**When** no frames are exchanged over an active session for 1 second, both nodes **shall** exchange `HEARTBEAT` messages; **if** three consecutive heartbeats are missed, the session **shall** be torn down per REQ-MOUSE-TRANSPORT-004.

**REQ-MOUSE-PROTOCOL-006 (Unwanted-behaviour):**
**If** the decoder receives a frame whose declared length exceeds 64 KiB, or whose payload fails msgpack validation, or whose `type` field is unknown, **then** the decoder **shall** discard the frame, log the violation, and **shall not** mutate the ownership state.

---

### REQ-MOUSE-VISIBILITY — HOST 커서 가시성 및 로컬 입력 소비 (Event-driven + Unwanted-behaviour + State-driven)

본 모듈은 HOST가 `CONTROLLING` 상태일 때 로컬 커서가 화면에 보이거나 물리 마우스 입력이 호스트 데스크탑에 영향을 주는 현상을 방지한다. 구현 전략은 다음 두 가지의 **결합**이다: (a) 가상 스크린 바깥 좌표 `(-32000, -32000)` 으로 커서를 파킹, (b) `WH_MOUSE_LL` 저수준 마우스 훅을 설치하여 훅 콜백이 `1` 을 반환하도록 하여 HOST 데스크탑으로의 이벤트 전달을 소비(억제)한다. 전역 `ShowCursor(FALSE)`·`SetSystemCursor`·오버레이 윈도우는 사용하지 않는다. REMOTE 측 커서 가시성은 본 모듈의 책임이 아니며, REMOTE OS 기본 커서가 그대로 유지된다 — 주입된 `MOUSE_MOVE` 이벤트에 따라 자연스럽게 이동할 뿐이다.

**REQ-MOUSE-VISIBILITY-001 (Ubiquitous):**
The HOST **shall** maintain a cursor visibility state that is bound to the `OwnershipState` FSM, exposing at minimum a `pre_hide_position: tuple[int, int]` field captured at the moment of the last `IDLE → CONTROLLING` transition.

**REQ-MOUSE-VISIBILITY-002 (Event-driven):**
**When** the HOST ownership state transitions from `IDLE` to `CONTROLLING`, the HOST **shall** (a) capture the current OS cursor coordinates into `pre_hide_position`, (b) reposition the cursor to the virtual-screen coordinate `(-32000, -32000)` via a single `SetCursorPos` call, and (c) install a `WH_MOUSE_LL` low-level mouse hook whose callback consumes all subsequent local mouse events by returning `1` (non-zero) without forwarding them to the next hook.

**REQ-MOUSE-VISIBILITY-003 (Event-driven):**
**When** the HOST ownership state transitions from `CONTROLLING` to `IDLE` — regardless of the transition cause (normal return edge per REQ-MOUSE-EDGE-003, remote `SESSION_END` per REQ-MOUSE-TAKEBACK-002 or with `reason: "takeback"`, HEARTBEAT-miss or peer-reset per REQ-MOUSE-TRANSPORT-004, or a conflict-driven `SESSION_END` per REQ-MOUSE-OWNERSHIP-006) — the HOST **shall** (a) uninstall the `WH_MOUSE_LL` hook installed per REQ-MOUSE-VISIBILITY-002, and (b) reposition the cursor back to the exact coordinates recorded in `pre_hide_position`, within 50 ms of the FSM transition.

**REQ-MOUSE-VISIBILITY-004 (Unwanted-behaviour):**
**If** the HOST needs to hide its cursor during `CONTROLLING` state, **then** the HOST **shall not** call `ShowCursor(FALSE)` at any scope, **shall not** replace the system cursor image via `SetSystemCursor` or equivalent APIs, **shall not** create overlay / topmost / tray-indicator windows for visibility purposes, and **shall not** apply any cursor visibility manipulation on the REMOTE node.

**REQ-MOUSE-VISIBILITY-005 (State-driven):**
**While** the HOST is in `CONTROLLED` state, no cursor hiding, parking, or hook installation **shall** be applied on the HOST node. (Reserved for Phase 2 symmetry; no-op in the 2-node MVP because the HOST node cannot enter `CONTROLLED` in the current topology.)

---

## 3. Exclusions (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목이다. 향후 별도 SPEC으로 다룬다.

| 제외 항목                                  | 이유                                 | 향후 대응                         |
|--------------------------------------------|--------------------------------------|-----------------------------------|
| 키보드 이벤트 공유                         | MVP는 마우스 단일 채널 검증에 집중     | 후속 SPEC-KEYBOARD-xxx            |
| 클립보드 공유 (텍스트/파일)                | 트랜스포트·소유권 검증 후 확장       | 후속 SPEC-CLIPBOARD-xxx           |
| BLE 트랜스포트 실제 구현                   | TCP로 추상화 검증 선행               | 후속 SPEC-TRANSPORT-BLE-xxx       |
| 모바일 페어링 앱 (BLE 게이트웨이)          | 트랜스포트 완성 후 UX 허브 설계      | 후속 SPEC-PAIRING-xxx             |
| macOS / Linux 지원                         | 입력 권한 모델이 OS별로 상이         | 후속 SPEC-OS-MACOS / SPEC-OS-LINUX |
| 3대 이상 PC 멀티-노드 토폴로지             | 2-노드 상태 머신 안정화 선행         | 후속 SPEC-TOPOLOGY-NODES-xxx      |
| 암호화·인증 (LAN trust 전제)               | BLE 페어링 단계에서 재평가           | 후속 SPEC-SECURITY-xxx            |
| GUI 설정 앱                                | MVP는 CLI + YAML config              | 후속 SPEC-GUI-CONFIG-xxx          |
| 고주사율 게이밍 (≥ 240 Hz 동기화)          | MVP는 120 Hz 지속 타깃               | V2에서 별도 성능 SPEC             |
| 가상 데스크탑/다중 논리 화면 구분          | `screeninfo` 한계, 단일 논리 화면 가정 | 후속 SPEC-EDGE-VIRTUAL-xxx        |
| REMOTE 측 커서 이미지 / 가시성 변경         | REMOTE OS 기본 커서 유지 (REQ-MOUSE-VISIBILITY-004) | 범위 외 — 도입 계획 없음 |
| 시스템 전역 `ShowCursor(FALSE)` / `SetSystemCursor` | 타 프로세스 영향 · 복원 부작용 위험 (REQ-MOUSE-VISIBILITY-004) | 범위 외 — 도입 계획 없음 |
| 오버레이 · 트레이 가시성 인디케이터          | MVP는 CLI 로그만 제공 (REQ-MOUSE-VISIBILITY-004) | 후속 SPEC-GUI-CONFIG-xxx 에서 재평가 |

---

## 4. 의존성 (Dependencies)

- `.moai/project/product.md` — MVP 범위 및 성공 기준
- `.moai/project/structure.md` — 디렉토리 레이아웃, 레이어 경계 규칙
- `.moai/project/tech.md` — 언어/라이브러리/성능 타깃
- 선행 SPEC: 없음 (본 SPEC이 MVP 최초 SPEC)
- 후속 SPEC 후보: SPEC-KEYBOARD, SPEC-TRANSPORT-BLE, SPEC-CLIPBOARD

---

## 5. 변경 통제 (Change Control)

- 본 SPEC은 `status: draft`이며, 승인 이후 `active`로 전환된다.
- REQ-XXX ID는 안정 식별자이므로 재부여·재정렬하지 않는다. 요구사항 삭제 시 ID는 `DEPRECATED` 표기하고 재사용하지 않는다.
- Exclusions 목록 축소(범위 확대)는 별도 SPEC으로 분리하고 본 SPEC은 수정하지 않는다.

---

## Implementation Notes (2026-04-19)

### 실제 구현 범위

**4개 수직 슬라이스, 36개 태스크 완료:**
- Slice 1 (T-001..T-009): `transport/` ABC + TCP + `protocol/` 메시지·코덱
- Slice 2 (T-010..T-019): `ownership/` FSM (3-state) + edge detector (2px/2tick) + takeback detector (5px/2events/100ms)
- Slice 3 (T-020..T-029): `input/` capture (pynput thread) + inject (SyntheticEvent) + visibility (WH_MOUSE_LL hook + park @ -32000,-32000)
- Slice 4 (T-030..T-036): `host.py` / `remote.py` 오케스트레이션 + `cli.py` typer CLI + E2E 통합 테스트

### 계획 대비 주요 편차

| 항목 | 계획 | 실제 | 해석 |
|------|------|------|------|
| **typer 라이브러리** | 개발 전용 | 런타임 의존성으로 승격 | CLI가 Slice 4의 필수 부분이므로 정당화 |
| **Python 최소 버전** | 3.11+ | 3.10 (개발 최소) | 개발 환경의 실용적 양보; 타깃은 여전히 3.11+ |
| **추가 모듈** | 계획 없음 | `bridge.py`, `_factory.py`, `_visibility_windows.py` | 정당성: 비동기↔스레드 브리지 (pynput 필수), DI 팩토리 (계층 경계 유지), Windows 구체화 (테스트성) |
| **테스트 구조** | `tests/unit/`, `tests/integration/` | 추가: `tests/fakes/`, `tests/meta/` | 테스트 더블 격리, 아키텍처 강제 메타테스트 |

### 테스트 결과 스냅샷

```
Overall Coverage:          85.34% (목표: ≥85%) ✓
Total Tests:               289 passed (0 failed)

Per-module coverage:
  src/eou/protocol/codec.py:              87%
  src/eou/ownership/edge_detector.py:     97%
  src/eou/input/visibility.py:           100%
  src/eou/input/backend.py:              100%
  src/eou/input/capture.py:              100%
  src/eou/input/inject.py:               100%
  src/eou/transport/base.py:             100%
  src/eou/transport/tcp.py:               83%
  src/eou/ownership/state.py:             92%
  src/eou/config.py:                      86%
  src/eou/bridge.py:                      95%
  src/eou/host.py:                        81%
  src/eou/remote.py:                      82%
  src/eou/cli.py:                         52% (integration 테스트로 검증, E2E 경로는 smoke test 포함)

REQ-to-Test Mapping:       122개 docstring 참조 (모든 26개 REQ-* ID 포함)
TRUST 5 Audit:             PASS (Tested/Readable/Unified/Secured/Trackable 모두 통과)
```

### 인수 기준 커버리지

**8개 시나리오 (acceptance.md):**
- S1: Happy-path edge transfer HOST → REMOTE ✓
- S2: Return transfer REMOTE → HOST ✓
- S3: Takeback on REMOTE local input ✓
- S4: Transport disconnect mid-session ✓
- S5: Edge touch without dwell satisfaction (negative) ✓
- S6: HOST cursor parking + local input consumption (REQ-MOUSE-VISIBILITY-002) ✓
- S7: Normal return edge, cursor restoration (REQ-MOUSE-VISIBILITY-003) ✓
- S8: Takeback path, cursor restoration (REQ-MOUSE-VISIBILITY-003) ✓

모든 시나리오는 통합 테스트 또는 수동 절차로 검증됨.

### 알려진 제약 사항

1. **Windows 전용 (MVP)**: pynput, ctypes.windll 사용. macOS/Linux는 SPEC-OS-MACOS, SPEC-OS-LINUX로 미연기.
2. **인증/암호화 없음**: LAN trust 모델 가정. BLE 단계에서 재평가 예정 (SPEC-SECURITY).
3. **WH_MOUSE_LL 훅 거부**: 안티체트 소프트웨어나 보안 데스크탑이 훅 설치를 거부할 수 있음 (REQ-MOUSE-VISIBILITY-004, 문서화됨).
4. **단일 논리 화면**: 다중 모니터 가상 데스크탑은 단일 물리 스크린으로 취급. SM_XVIRTUALSCREEN 없을 경우 `(-32000, -32000)` fallback.

### 후속 작업 포인터

- **SPEC-KEYBOARD-001**: 키보드 이벤트 공유
- **SPEC-CLIPBOARD-001**: 클립보드 동기화
- **SPEC-BLE-001**: BLE 트랜스포트 실장 (transport/ 계층만 변경)
- **SPEC-OS-MACOS**, **SPEC-OS-LINUX**: macOS/Linux 지원

---
