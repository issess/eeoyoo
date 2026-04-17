# Product — EOU (Edge-of-screen Unified input)

## Vision

Synergy와 같이 여러 PC 간 마우스/키보드/클립보드를 공유하는 크로스-PC 입력 공유 애플리케이션. 장기적으로는 PC-to-PC 통신을 **휴대폰의 BLE 게이트웨이**를 경유하도록 만들어, 동일 네트워크/방화벽 제약 없이 두 PC를 연결한다.

## Core Value

- 한 세트의 마우스/키보드로 여러 PC를 자연스럽게 제어
- 화면 엣지 근처 마우스 이동만으로 소유권 자동 전환 (KVM hotkey 불필요)
- 모바일(BLE)을 페어링/연결 설정의 UX 허브로 사용 — Wi-Fi·방화벽 구성 부담 제거
- 클립보드 공유로 텍스트/파일 이동 단순화

## Target Users

- 듀얼 PC 워크스테이션 사용자 (개인 PC + 회사 PC 나란히 배치)
- 데스크탑 + 노트북 동시 사용 개발자
- 사내 네트워크가 격리되어 기존 Synergy/Barrier가 동작하지 않는 사용자

## MVP Scope (Phase 1)

**In scope:**
- 2대 PC 간 마우스 커서 이동 공유 (HOST ↔ REMOTE)
- 화면 엣지 기반 자동 소유권 전환
- REMOTE 측 로컬 입력 감지 시 즉시 제어권 반납 (NACK)
- TCP/IP 트랜스포트 (BLE 교체 가능한 추상화 인터페이스)
- Windows 전용 (pynput/pywin32)

**Out of scope (later phases):**
- 키보드 이벤트 공유
- 클립보드 공유
- BLE 트랜스포트 실장
- 모바일 앱을 통한 페어링
- macOS / Linux 지원
- 3대 이상 PC 멀티-노드

## Success Criteria

- HOST 화면 우측 엣지에 커서를 밀면 250ms 이내 REMOTE 커서로 이동 제어가 시작된다
- REMOTE 측에서 물리 마우스를 움직이면 100ms 이내 HOST로 소유권이 반납된다
- 트랜스포트 계층을 BLE로 교체할 때 상위 계층(ownership, capture, injection) 수정이 불필요하다
- 1시간 연속 사용 시 크래시/고착 없음

## Non-Goals

- 고성능 게이밍 시나리오 (저지연 60Hz+ 동기화는 V2)
- 보안 암호화 (BLE 단계에서 재평가, MVP는 LAN trust)
- GUI 설정 앱 (MVP는 CLI + config 파일)
