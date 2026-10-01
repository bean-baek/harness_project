# Troubleshooting Index

_자동 생성 — `list_troubles` 호출 시 갱신됨._

| ID | Status | Severity | Title | Component |
|---|---|---|---|---|
| [TS-001](TS-001-features-json-path.md) | resolved | high | night_shift.py가 features.json을 찾지 못하고 조용히 "완료" 출력 | `night_shift.py` |
| [TS-002](TS-002-windows-cp949-subprocess-emoji.md) | resolved | high | Windows cp949 콘솔에서 main.py의 이모지 출력이 UnicodeEncodeError로 중단 | `night_shift.py` |
| [TS-003](TS-003-subprocess-utf8-decode-cp949-output.md) | resolved | high | tools.py subprocess가 npm/jest/git의 cp949 출력을 UTF-8로 디코딩하다 _readerthread 크래시 | `harness/tools.py` |
| [TS-004](TS-004-graph-silent-abort-no-tool-calls.md) | resolved | high | Coder가 도구 없이 텍스트만 응답하면 그래프가 조용히 종료되어 returncode=0으로 위장 성공 | `harness/router.py` |
| [TS-005](TS-005-llm-quota-exhausted-crash.md) | resolved | high | LLM 쿼터 초과(429)가 트레이스백으로 터지며 night_shift가 멀쩡한 기능들을 stuck으로 마킹 | `harness/llm_errors.py` |
| [TS-006](TS-006-ungated-self-grading-features.md) | resolved | high | 에이전트가 테스트 증거 없이 features.json을 자가 채점 — run_tests는 Windows에서 한 번도 동작하지 않았다 | `harness/tools.py` |
| [TS-007](TS-007-dead-checkpointer-config.md) | resolved | medium | 체크포인터 영속 설정이 죽은 설정 — main.py가 플래그를 전달하지 않아 항상 InMemorySaver | `main.py` |
| [TS-008](TS-008-suite-green-is-not-feature-evidence.md) | resolved | high | "스위트 녹색"을 "이 기능이 검증됨"으로 오인 — 증거 게이트가 기능과 테스트를 연결하지 않았다 | `harness/verify.py` |
| [TS-009](TS-009-unrecorded-run-outcomes.md) | resolved | medium | 실행 15회 중 9회가 종료 상태를 남기지 않아 하네스 사후 측정의 60%가 맹점 | `night_shift.py` |
| [TS-010](TS-010-tokenless-mode.md) | resolved | high | 하네스의 가치는 이미 토큰을 쓰지 않았다 — 유료 API를 추론 엔진에서 제거 | `harness/cli.py` |
