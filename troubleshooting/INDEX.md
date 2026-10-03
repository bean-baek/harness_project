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
| [TS-011](TS-011-auth-guard-race-and-open-redirect.md) | resolved | high | 라우트 가드가 isLoading을 무시해 새로고침마다 로그아웃 + ?redirect= 오픈 리다이렉트 | `web_target/src/components/ProtectedRoute.tsx` |
| [TS-012](TS-012-declared-but-dead-commands.md) | resolved | high | package.json이 광고하는 명령 3개(lint/build/test:e2e)가 전부 동작하지 않았다 | `web_target/package.json` |
| [TS-013](TS-013-unit-tests-cannot-verify-route-table.md) | resolved | high | 단위 테스트가 자기가 만든 라우트를 검증해 F-005가 실 브라우저에서 전혀 동작하지 않았다 | `web_target/src/routes.ts` |
| [TS-014](TS-014-tag-points-at-wrong-feature.md) | resolved | high | 태그가 엉뚱한 기능을 가리켜도 게이트가 보지 못한다 — 피험체 결함은 어디까지 고치는가 | `harness/tags.py` |
| [TS-015](TS-015-orphaned-measurement-after-mode-switch.md) | resolved | medium | 토큰 없는 모드로 옮기며 측정 계층의 절반이 고아가 됐다 — 기록자가 사라진 것을 몰랐다 | `harness/cli.py` |
| [TS-016](TS-016-vacuous-evidence-passes-the-gate.md) | resolved | high | 아무것도 실행하지 않는 테스트가 완벽한 증거로 계수됐다 — 커버리지 게이트와 돌연변이 측정 | `harness/verify.py` |
| [TS-017](TS-017-harness-bound-to-one-repo.md) | resolved | high | 하네스가 레포 한 곳에만 붙어 있었다 — 설정 외부화·런너 추상화·프로젝트 검수 | `harness/project.py`, `harness/runner.py`, `harness/inspect.py` |
| [TS-018](TS-018-paid-path-unverified-for-six-months.md) | resolved | high | 유료 경로가 6개월간 검증 없이 방치됐다 — 스모크 테스트가 즉시 버그 2건을 찾아냈다 | `harness/router.py`, `harness/nodes/agents.py` |
| [TS-019](TS-019-dead-config-and-orphan-code.md) | resolved | medium | 문서가 광고하는 설정 3개가 아무 일도 하지 않았다 — 죽은 설정의 두 번째 재발 + 고아 코드 21건 | `harness/deadcode.py`, `harness/router.py` |
| [TS-020](TS-020-evidence-independence.md) | resolved | high | 증거 사다리의 빈 칸은 깊이가 아니라 독립성이었다 — TS-013 을 정책으로 일반화 | `harness/independence.py` |
| [TS-021](TS-021-mutation-operators-tested-the-compiler.md) | resolved | high | 변이 연산자가 테스트를 시험하지 않고 컴파일러를 시험했다 — 190곳 중 3곳만 진짜 비교 | `harness/mutate.py` |
| [TS-022](TS-022-detection-reach.md) | resolved | high | 탐지가 닿지 않는 두 구멍 — 표본은 파일 앞머리만, 연산자는 배열을 못 건드렸다 | `harness/mutate.py` |
| [TS-023](TS-023-survivor-means-two-things.md) | resolved | high | 생존한 변이를 '테스트가 약하다'로 읽고 고치려 했다 — 명세가 요구하지 않는 것이었다 | `harness/mutate.py` |
| [TS-024](TS-024-published-numbers-go-stale.md) | resolved | high | 같은 측정값을 네 번 다르게 발표했다 — 산문의 수치는 측정 코드가 바뀌면 조용히 거짓이 된다 | `harness/status.py` |
| [TS-025](TS-025-single-subject-verification.md) | resolved | high | 모든 검증이 피험체 한 명을 봤다 — 두 번째 프로젝트에 닿자 결함 5개가 동시에 드러났다 | `harness/project.py`, `harness/independence.py`, `harness/inspect.py`, `harness/runner.py` |
| [TS-026](TS-026-mutating-unexecuted-lines.md) | resolved | high | 증거가 지나가지 않는 줄에 결함을 심고 그 생존을 증거의 구멍으로 셌다 — 발표된 점수 네 개가 전부 틀렸다 | `harness/runner.py`, `harness/mutate.py`, `harness/verify.py` |
| [TS-027](TS-027-failure-modes-recorded-after-the-fact.md) | resolved | medium | 실패 모드 기록이 전부 터진 뒤에 쓰였다 — 붙이기 전에 노출을 묻는 장치가 없었다 | `harness/exposure.py`, `config.py` |
| [TS-028](TS-028-draft-was-not-a-spec.md) | resolved | medium | '명세 초안'이 검수 발견 사항을 기능처럼 포장한 것이었다 — 넷 중 둘은 기능이 아니고 둘은 내용이 없었다 | `harness/draft.py`, `harness/inspect.py` |
| [TS-029](TS-029-blind-check-disabled-a-real-gate.md) | resolved | medium | 오탐이 있는 판정으로 차단하려다 `|| true` 가 붙어 정확한 판정의 차단력까지 잃었다 | `harness/inspect.py`, `.github/workflows/ci.yml` |
