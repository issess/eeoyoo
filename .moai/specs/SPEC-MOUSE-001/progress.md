# SPEC-MOUSE-001 Progress

- Started: 2026-04-18
- Development mode: TDD (RED-GREEN-REFACTOR)
- Harness level: standard
- Implementation strategy: vertical slices (sequential)
- Git strategy: main branch, commit-per-slice

## Slice Plan
- Slice 1: `transport/` (ABC + TCP) + `protocol/` (messages + codec)
- Slice 2: `ownership/` (FSM + edge detector) + takeback logic
- Slice 3: `input/` (capture + inject + visibility)
- Slice 4: `host.py` + `remote.py` + `cli.py` (orchestration + CLI)

## Phase Log
- 2026-04-18: Initial bootstrap commit (bd316fe) — .moai/, .claude/, project docs, SPEC-MOUSE-001 v0.2.0
- 2026-04-18: Slice 1 complete (T-001..T-009) — commits 603574a, 4fcfdc7, 64483ca

## Task Log

- T-001 complete: files=[pyproject.toml, src/eou/__init__.py, src/eou/py.typed, src/eou/transport/__init__.py, src/eou/protocol/__init__.py, src/eou/ownership/__init__.py, src/eou/input/__init__.py, README.md, tests/__init__.py, tests/conftest.py, tests/fakes/__init__.py, tests/integration/__init__.py, tests/meta/__init__.py, tests/unit/**/__init__.py], tests=0 (bootstrap), coverage=N/A
- T-002/T-003 complete: files=[src/eou/transport/base.py, src/eou/transport/__init__.py, tests/unit/transport/test_base.py, tests/fakes/transport.py], tests=11 passed, coverage=100%
- T-004/T-005 complete: files=[src/eou/transport/tcp.py, tests/unit/transport/test_tcp_framing.py], tests=18 passed (29 total), coverage=transport 83%+ (total 89%)
- T-006/T-007 complete: files=[src/eou/protocol/messages.py, src/eou/protocol/codec.py, src/eou/protocol/__init__.py, tests/unit/protocol/test_messages.py, tests/unit/protocol/test_codec.py], tests=48 passed (77 total), coverage=protocol 87%+
- T-008 complete: files=[tests/integration/test_tcp_loopback.py], tests=8 passed (85 total), coverage=89%
- T-009 complete: files=[tests/meta/test_import_boundaries.py], tests=4 passed (89 total), coverage=89%

## Slice 1 Exit

- All T-001..T-009 green ✓
- transport/ + protocol/ coverage ≥ 85% (actual: 89%) ✓
- meta-test passes (layer boundary enforcement) ✓
- ruff warnings = 0 ✓

## Slice 2 Task Log

- T-010/T-011 complete: files=[src/eou/ownership/state.py, tests/unit/ownership/test_state.py], tests=12 passed (101 total), commit=2cc7d53
- T-012/T-013 complete: files=[tests/unit/ownership/test_transitions.py], tests=22 passed (123 total), commit=2cc7d53
- T-014/T-015 complete: files=[src/eou/ownership/edge_detector.py, tests/unit/ownership/test_edge_detector.py], tests=15 passed (138 total), commit=99d513d
- T-016/T-017 complete: files=[src/eou/ownership/takeback_detector.py, tests/unit/ownership/test_takeback_detector.py], tests=15 passed (153 total), commit=99d513d
- T-018 complete: files=[src/eou/ownership/coordinator.py, tests/unit/ownership/test_coordinator.py], tests=6 passed (159 total)
- T-019 complete: files=[tests/unit/ownership/test_acceptance_paths.py], tests=6 passed (165 total), scenarios=1,2,3,5

## Slice 2 Exit

- All T-010..T-019 green ✓
- ownership/ coverage = 95.33% (target: ≥ 85%) ✓
- Full test suite: 165 passed (89 Slice1 + 76 Slice2) ✓
- ruff warnings = 0 ✓
- meta-test (layer boundary) still passes ✓
- No import of transport.tcp or input.* in ownership/ ✓

## Slice 3 Task Log

- T-020/T-021 complete: files=[src/eou/input/backend.py, tests/fakes/mouse.py, tests/unit/input/test_backend.py], tests=17 passed (182 total)
- T-022/T-023 complete: files=[src/eou/input/capture.py, tests/unit/input/test_capture.py], tests=6 passed (188 total)
- T-024/T-025 complete: files=[src/eou/input/inject.py, tests/unit/input/test_inject.py], tests=8 passed (196 total)
- T-026/T-027 complete: files=[src/eou/input/visibility.py, src/eou/input/_visibility_windows.py, tests/fakes/visibility.py, tests/unit/input/test_visibility_contract.py], tests=20 passed (216 total)
- T-028/T-029 complete: files=[tests/unit/input/test_visibility_windows.py], tests=16 passed (232 total), pyproject.toml addopts+deps updated

## Slice 3 Exit

- All T-020..T-029 green ✓
- input/ coverage: backend=100%, capture=100%, inject=100%, visibility=100%, _visibility_windows=84% (ctypes.windll not available on Linux — expected) ✓
- Overall coverage = 92.05% (target: ≥ 85%) ✓
- Full test suite: 232 passed (165 Slice1+2 + 67 Slice3) ✓
- ruff warnings = 0 ✓
- meta-test (layer boundary) still passes ✓
- addopts="-m 'not windows'" set in pyproject.toml ✓
- MX tags: @MX:ANCHOR on MouseBackend + CursorVisibility, @MX:WARN on WindowsCursorVisibility hook + failure path, @MX:NOTE on park_offset + FakeCursorVisibility, @MX:WARN on capture.py thread bridge ✓
