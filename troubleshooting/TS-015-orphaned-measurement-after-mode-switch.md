---
id: TS-015
title: 토큰 없는 모드로 옮기며 측정 계층의 절반이 고아가 됐다 — 기록자가 사라진 것을 몰랐다
date: 2026-10-02
category: observability
severity: medium
status: resolved
component: harness/cli.py
tags: [measurement, tokenless, mode-switch, ci, gate-outcome]
guard: `cli deadcode` 가 참조 끊긴 함수·클래스를 CI 에서 차단한다
exposure: orphan-code
resolution: accept
---

## Symptoms
TS-010 에서 추론 엔진을 유료 API 에서 Claude Code 세션으로 옮긴 뒤, `cli report` 의
실행 로그 절반이 계속 같은 수치를 출력했다.

```
총 시도 15회 | 결과 분포: failed 6, unknown 9
```

**15건 전부 유료 `night_shift` 시대의 기록이다.** 토큰 없는 모드로 작업한 F-005 구현,
F-005 회수·재기록, 수십 번의 `verify`/`mark` 호출은 **단 한 줄도 남지 않았다.**

더 나쁜 것은 이 사실을 **발견 경로**다. "다음 발전 방향"을 묻는 질문에 나는
"기능당 토큰·비용을 기록하자"고 답했다 — 방금 토큰을 쓰지 않도록 바꿔놓은 시스템에.
사용자가 "비용 없는 하네스잖아"라고 지적해서야 드러났다.

## Root cause
- **기록자가 모드와 함께 사라졌다.** `[END]` 줄을 쓰는 코드는 `night_shift.py` 뿐이다
  (TS-009 에서 그렇게 만들었다). 토큰 없는 모드는 `night_shift` 를 쓰지 않으므로
  기록 주체가 없어졌다. `harness/cli.py` 는 `--log` 경로를 **받기만 하고 쓰지 않았다.**
- **측정 대상을 모드와 함께 갱신하지 않았다.** 유료 모드에서 측정할 것은
  "시도 횟수·소요 시간·종료 코드"였다. 토큰 없는 모드에서 측정할 것은 다르다 —
  세션이 추론을 맡으므로 **게이트가 무엇을 걸렀는가**가 유일하게 의미 있는 지표다.
  모드를 바꾸면서 지표를 재정의하지 않아, 옛 지표가 빈 값을 가리키는 상태로 남았다.
- 그 결과 **발전 방향 제안까지 틀렸다.** 측정 공백을 "비용 측정이 없다"로 오진했는데,
  실제 공백은 "판정 효과 측정이 없다"였다.

## Fix
- **[harness/cli.py](../harness/cli.py)** — `record_run()` 신설. `verify` / `mark` / `unmark`
  가 판정마다 기록을 남긴다. 블록 형식은 **TS-009 의 night_shift 기록과 동일하게 유지**해
  `run_log_stats` 가 두 시대의 기록을 같은 파서로 읽는다. 게이트 전용 차원은 새 줄로 분리:

  ```
  [GATE] feature=F-006 command=verify verdict=reject level=feature reason=기능 태그 없음
  [GATE-DETAIL] F-006 를 검증하는 테스트가 없습니다. 스위트는 녹색이지만...
  [END] exit=1 outcome=reject elapsed_sec=9.5
  ```

  `--log` 로 경로 지정, `--no-log` 로 비활성화. 기록 실패는 삼킨다 —
  **기록 실패가 판정을 가려선 안 된다**(TS-009 의 원칙).
- **[harness/metrics.py](../harness/metrics.py)** — `gate_stats()` / `format_gate_stats()` 신설.
  집계 지표:

  | 지표 | 의미 |
  |---|---|
  | 판정 분포 (accept/reject/revoke) | 게이트가 얼마나 거부하는가 |
  | 거부 사유 분포 | **세션이 주로 무엇을 빠뜨리는가** |
  | 기능별 거부 횟수 | 하나를 입증하는 데 몇 번 막혔는가 |
  | **revoke 횟수** | **게이트가 틀렸던 횟수** — 통과시킨 뒤 회수한 사건 |

  마지막 지표가 핵심이다. 현재 이 값의 유일한 데이터 포인트는 부끄러운 것이다 —
  F-005 에서 게이트는 **통과시켰고**, 실제로 잡은 것은 E2E 였다(TS-013).
  그 사건이 이제 수치로 남는다.
- **[.github/workflows/ci.yml](../.github/workflows/ci.yml) (신설)** — 1순위로 CI 를 넣었다.
  이 프로젝트가 네 번 반복한 실패는 "선언했는데 아무도 돌려보지 않아 불일치가 유지된다"였고
  (TS-001 / `init.sh` / TS-006 / TS-012), CI 는 그에 대한 기계적 처방이다.
  토큰 없는 모드이므로 **API 키 없이 전부 돈다** — 검증 205건 + lint + build + tsc + E2E,
  비용 0. 세 잡으로 분리(하네스 / 대상 앱 / E2E)해 빠른 신호를 먼저 받는다.

## Verification
`repro_ts015.py` — **29/29 PASS**. LLM·jest 호출 없음.

- **기록 형식 6건**: `TASK START` / `SESSION: cli-<명령>/<기능>` / `TIME` /
  `[GATE]` / `[GATE-DETAIL]` / `[END]`
- **사유 분류 6건**: 회귀 · 기능 태그 없음 · 단계 미검증 · 테스트 없음 · 실행 불가 · 빈 사유
- **기록 끄기·내성 2건**: `log_path=None` 이면 파일을 만들지 않고,
  쓸 수 없는 경로에서도 예외를 올리지 않는다
- **집계 6건**: 판정 분포 `{reject 2, accept 2, revoke 1}`, 거부 사유 분포,
  거부율 0.4, 기능별 집계, 회수 1건
- **두 시대 호환 5건**: night_shift 블록과 CLI 블록이 섞인 로그에서
  `run_log_stats` 가 2건을 인식하고 `unknown` 0건, `gate_stats` 는 CLI 기록만 센다
- **출력 4건**: 거부 사유 노출, 회수 경고, 기록 없음 안내, 로그 없음 처리

실제 동작: `cli verify F-006`(미구현) → `verdict=reject reason=기능 태그 없음`,
`cli verify F-005`(구현됨) → `verdict=accept`. 집계가 거부율 50% 로 보고.

CI: YAML 파싱 OK (3 잡 / 단계 14·8·6), `audit` 과 `report` 의 실제 플래그를 확인해
처음 작성한 `--no-log` 오용을 고쳤다(그 플래그는 `verify`/`mark`/`unmark` 전용이다).
`report` 는 로그 파일이 없어도 exit 0 임을 확인했다(CI 에는 로그가 없다).

## Prevention
- **모드를 바꾸면 지표를 재정의할 것.** 실행 방식을 교체하면 "무엇을 측정해야 하는가"도
  바뀐다. 옛 지표가 빈 값을 가리키는 것은 조용한 고장이다.
- 측정 계층을 만들 때 **기록자와 집계자를 쌍으로 확인할 것.** 집계자만 남으면
  숫자는 계속 나오지만 아무것도 측정하지 않는다.
- **기록 포맷은 모드 교체를 견디게 설계할 것.** `[END]` 형식을 유지한 덕에 파서를
  고치지 않고 두 시대를 함께 읽는다.
- "다음에 무엇을 할까"를 답할 때 **현재 아키텍처를 먼저 확인할 것.**
  이번에는 직전에 내가 바꾼 구조를 잊고 사라진 비용을 측정하자고 제안했다.
- CI 가 없으면 "선언했는데 실행되지 않는" 결함이 계속 쌓인다 — 이 프로젝트에서 네 번 반복됐다.
