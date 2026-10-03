---
id: TS-009
title: 실행 15회 중 9회가 종료 상태를 남기지 않아 하네스 사후 측정의 60%가 맹점
date: 2026-10-01
category: observability
severity: medium
status: resolved
component: night_shift.py
tags: [observability, metrics, measurement, discrimination, ab-test]
guard: `verify`/`mark`/`unmark` 가 판정마다 harness_runtime.log 에 기록한다
exposure: run-logging
resolution: accept
---

## Symptoms
- `harness_runtime.log` 에 `TASK START` 블록이 15개 있는데, 종료 마커
  (`[SUCCESS]` / `[ERROR]` / `[INFRA]`)를 가진 블록은 **6개뿐**이다.
- 나머지 9개는 그 런이 성공했는지, 실패했는지, 강제 종료됐는지 **기록이 전혀 없다**.
  타임아웃 마커(`[⏱ Timeout]`)도 0건이다.
- 결과: 하네스가 실제로 어떻게 돌았는지 묻는 모든 질문에 답할 수 없다 —
  "기능당 평균 몇 번 시도했나", "실패 중 인프라 장애 비율은", "얼마나 걸렸나" 모두 불가.
- 이 결함은 `harness/metrics.py`(하네스 자체 측정 계층)를 만들면서 드러났다.
  첫 집계가 `unknown 60%` 로 나왔고, 파서 버그인지 기록 공백인지 확인한 결과 **기록 공백**이었다.

## Root cause
- `night_shift.run_harness()` 의 종료 기록은 `process.wait()` **이후**의 분기에서만 수행됐다.
  그 지점에 도달하지 못하면 아무것도 남지 않는다. 도달 실패 경로:
  - **D1 (부모 프로세스 사망)**: TS-003 시절 `_readerthread` 가 cp949 출력을 UTF-8 로
    디코딩하다 크래시하면 부모가 먼저 죽었다. 자식의 결과는 영구 소실.
  - **D2 (타임아웃 경로의 조기 return)**: 타임아웃 분기는 사람이 읽는 메시지만 쓰고
    `return -1` 로 빠져나간다. 기계가 파싱할 종료 줄이 없다.
  - **D3 (예외·인터럽트)**: `Popen` 실패나 `KeyboardInterrupt` 는 try 로 감싸여 있지 않아
    기록 없이 전파된다.
- 공통 원인은 **"기록이 정상 경로에만 있다"** 는 구조다. 관측은 실패 경로에서 더 중요한데,
  바로 그 경로에 기록이 없었다.

## 도입 근거 (외부 비교)
[revfactory/harness](https://github.com/revfactory/harness) 의 스킬 검증 가이드는
`total_tokens` 와 `duration_ms` 를 **완료 통지 직후 즉시** 저장하라고 명시한다 —
"나중에는 복구할 수 없다"는 이유다. 우리 로그는 정확히 그 복구 불가 상태였다.
비교 분석 전문: [docs/comparison-revfactory.md](../docs/comparison-revfactory.md)

## Fix
- **[night_shift.py](../night_shift.py)** — `run_harness()` 본문을 `try/except/finally` 로 감싸고,
  `finally` 에서 **항상** 기계가 파싱하는 종료 줄을 남긴다.

  ```
  [END] exit=<코드|None> outcome=<success|failed|infra|timeout|aborted(예외명)> elapsed_sec=<초>
  ```

  - 사람이 읽는 기존 마커(`[✅ Success]` 등)는 그대로 유지한다 — 역할이 다르다.
  - `except BaseException` 에서 `outcome` 에 예외 타입명을 기록하고 **재전파**한다
    (삼키지 않는다. TS-005 의 원칙과 같다).
  - `_write_end()` 내부의 쓰기 실패는 무시한다 — 기록 실패가 본래 오류를 가려선 안 된다.
- **[harness/metrics.py](../harness/metrics.py) (신설)** — 하네스 자체를 측정하는 계층.
  - `run_log_stats()` — `[END]` 를 사람용 마커보다 **우선** 신뢰한다(항상 기록되므로).
    `[END]` 가 없는 과거 블록은 `unknown` 으로 남기고, 소요 시간은 연속 시작 시각 차이로
    **추정**한다(추정임을 명시).
  - `discrimination_report()` — 증거 수준별 통과율을 세어 판별력을 수치화한다.
    자세한 근거와 결과는 비교 분석 문서 §3~4.
  - CLI: `python -m harness.metrics`
  - jest 실행 이음매를 `verify.run_jest_json` 하나로 통일해 스텁 가능하게 했다.

## Verification
`repro_ts009.py` — **36/36 PASS**. jest 는 가짜 JSON, 로그는 임시 파일. LLM·네트워크 없음.

- **판별력 측정 5건**: `suite` 가 전부 통과(판별력 0)하고 `feature`·`step` 이 태그 유무로
  갈라지는 것, 거부 사유 분류, A/B 수치(`1 - 3/4 = 0.25`)
- **플래그 감사 3건**: 증거 없는 통과(`A-003`)와 증거 있는데 미완성 표시(`A-004`) 양방향 적발
- **회귀 우선 3건**: 스위트 빨간불이면 모든 수준이 0건
- **jest 실행 불가 3건**: `error` 반환 및 포맷 함수의 오류 표시
- **로그 파싱 8건**: `success` / `infra` / `timeout` / `aborted(KeyboardInterrupt)` 네 상태 구분,
  `unknown` 0건, 세션별 시도 집계, `[END]` 가 사람용 마커를 덮어쓰는 우선순위
- **과거 블록 호환 3건**: 마커 없는 블록은 `unknown`, 사람용 마커는 계속 인식,
  소요 시간은 시작 시각 차이로 추정
- **포맷 5건**: 핵심 수치(판별력·A/B·증거 없는 통과·즉시 실패 경고)가 실제로 출력에 포함

**실 환경 E2E**: 자식 프로세스를 가짜로 바꿔 세 경로를 모두 실행한 결과
```
[END] exit=0    outcome=success                  elapsed_sec=1.0
[END] exit=3    outcome=infra                    elapsed_sec=1.0
[END] exit=None outcome=aborted(OSError)         elapsed_sec=0.0
```
파서 집계 `{'success': 1, 'infra': 1, 'aborted(OSError)': 1}`, `unknown` 0건.
예외는 기록 후 정상적으로 재전파됐다.

실제 로그 재측정: 15회 중 6회만 기록(40%) — 과거 블록은 복구 불가로 남는다.
이후 실행은 전부 기록된다.

## Prevention
- **관측 기록은 `finally` 에 둘 것.** 정상 경로에만 있는 로그는 가장 필요한 순간에 없다.
- 사람이 읽는 메시지와 기계가 파싱하는 줄을 **분리**할 것. 이모지·자유 문장은 포맷이 바뀌고,
  집계는 조용히 틀린다. `[END] key=value` 형태를 유지한다.
- 측정값은 발생 시점에 기록할 것 — 종료 코드·소요 시간은 사후 복구가 불가능하다.
- 집계가 이상할 때(`unknown 60%`) **파서 버그와 기록 공백을 먼저 구분**할 것.
  이번에는 기록 공백이었고, 파서를 고쳤다면 숫자만 좋아지고 문제는 남았을 것이다.
- 측정 계층에는 스텁 가능한 **단일 이음매**를 둘 것 (`verify.run_jest_json`).
  두 모듈이 같은 함수를 각자 임포트하면 한쪽만 패치되어 테스트가 조용히 실제 실행을 한다.
