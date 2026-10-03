---
id: TS-007
title: 체크포인터 영속 설정이 죽은 설정 — main.py가 플래그를 전달하지 않아 항상 InMemorySaver
date: 2026-10-01
category: config
severity: medium
status: resolved
component: main.py
tags: [langgraph, checkpointer, persistence, human-in-the-loop, resume]
guard: `cli deadcode` 가 참조 0건 설정을 CI 에서 차단한다
exposure: dead-config
---

## Symptoms
- `config.py` 에 `USE_PERSISTENT_MEMORY`(`HARNESS_PERSISTENT`) 와 `DATABASE_URL` 이 있고
  `requirements.txt` 에도 Postgres 체크포인터가 주석으로 준비되어 있다.
- 그러나 `HARNESS_PERSISTENT=true` 를 설정해도 아무 변화가 없다. 로그에 경고도, 확인도 없다.
- 증상의 결과:
  - 기능 중간에 프로세스가 죽으면 **재개 불가** — 매번 처음부터 다시 시작.
  - `human_check` 의 `interrupt()` 가 만든 대기 상태가 프로세스와 함께 소멸 →
    "비가역적 작업 전 인간 승인"이 프로세스 경계를 넘어 유지되지 않는다.
  - `night_shift.py` 가 30분 타임아웃으로 자식을 kill 하면 그 기능의 진행 상태는 전부 유실.

## Root cause
- **D1 (플래그 미전달)**: `main.py` 가 `build_harness_graph(max_retry=max_retry)` 만 호출했다.
  `build_harness_graph` 의 `use_persistent_memory` / `db_uri` 파라미터는 기본값
  `False` / `None` 으로 남아 영속 분기가 **한 번도 평가되지 않았다.** 설정값이 코드에 연결되지 않은
  순수한 죽은 설정.
- **D2 (섀도잉 지뢰)**: `run_harness()` 안에서 `config = {"configurable": {...}}` 로
  지역 변수를 만들고 있었다. Python 은 함수 내 할당이 있으면 그 이름을 **함수 전체에서** 지역으로
  보므로, 같은 함수에서 모듈 `config` 를 참조하는 순간 `UnboundLocalError` 가 난다.
  즉 D1 을 고치려면 먼저 이 섀도잉을 풀어야 했다 — 설정을 연결하기 어렵게 만든 구조적 원인.
- **D3 (컨텍스트 매니저 오용)**: `PostgresSaver.from_conn_string(db_uri)` 는 `@contextmanager` 다.
  그대로 대입하면 체크포인터가 아니라 `_GeneratorContextManager` 가 들어가므로, 설정을
  연결하자마자 런타임에 깨졌을 것이다. 또한 `except ImportError` 폴백이 한 줄 경고로
  **조용히** InMemorySaver 로 떨어져, 운영자가 "영속이 켜졌다"고 오해할 수 있었다.

## Fix
- [main.py](../main.py)
  - `run_harness()` 의 지역 변수 `config` → `graph_config` 로 개명 (5개 사용처 전부).
  - `build_harness_graph(max_retry=..., use_persistent_memory=config.USE_PERSISTENT_MEMORY,
    db_uri=config.DATABASE_URL or None)` — 설정이 실제로 그래프에 도달한다.
- [harness/graph.py](../harness/graph.py) — `_build_checkpointer(use_persistent_memory, db_uri)` 신설
  (`build_harness_graph` 본문에서 분리해 단위 검증 가능하게).
  - `from_conn_string()` 을 명시적으로 `__enter__()` 하고 `setup()` 으로 테이블을 만든 뒤,
    매니저를 모듈 레벨 `_PERSISTENT_MANAGERS` 에 보관한다 — 그래프가 블록보다 오래 살아야 하고,
    GC 가 매니저를 닫아버리면 안 된다.
  - **모든 폴백을 소리내어** 보고한다: URL 없음 / 패키지 미설치 / 초기화 실패 각각에 대해
    사유와 결과("프로세스 간 재개 불가")를 출력하고, 성공 시에는 활성 메시지를 출력한다.
  - 영속 백엔드 활성화 방법도 경고에 포함:
    `pip install langgraph-checkpoint-postgres psycopg[binary]`.

## Verification
- `_build_checkpointer(False, None)` → `InMemorySaver` (기존 동작 유지, 경고 없음).
- `_build_checkpointer(True, "")` → 경고 + `InMemorySaver`.
- `_build_checkpointer(True, "postgresql://...")` → 패키지 미설치 경고(설치 명령 포함) + `InMemorySaver`.
- `build_harness_graph(max_retry=2)` → `CompiledStateGraph` 정상 컴파일.
- `main.py` 임포트 + `repro_ts005.py` 37/37 PASS — `graph_config` 개명이 TS-005 경로를
  깨뜨리지 않음을 확인.

**현재 환경 주의**: `langgraph.checkpoint.postgres` 와 `langgraph.checkpoint.sqlite` 모두 미설치다.
따라서 지금은 `HARNESS_PERSISTENT=true` 로 두어도 경고와 함께 InMemorySaver 로 동작한다 —
차이는 **그 사실이 이제 로그에 드러난다**는 점이다.

## Prevention
- 설정 키를 추가할 때는 "읽는 쪽"까지 연결됐는지 확인할 것. 읽히지 않는 설정은 기능이 아니라 거짓말이다.
- 함수 안에서 모듈과 같은 이름(`config`)을 지역 변수로 쓰지 말 것 — 나중에 그 모듈을 쓰려는
  모든 변경이 `UnboundLocalError` 로 막힌다.
- 인프라 폴백은 절대 조용히 하지 말 것. 기능이 꺼진 채로 돌아가는 것보다,
  꺼졌다는 사실을 모르는 것이 더 위험하다.
- `from_conn_string` 류의 팩토리는 반환형이 컨텍스트 매니저인지 확인할 것.
