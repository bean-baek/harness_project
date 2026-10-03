---
id: TS-001
title: night_shift.py가 features.json을 찾지 못하고 조용히 "완료" 출력
date: 2026-04-14
category: config
severity: high
status: resolved
component: night_shift.py
tags: [cwd, path-resolution, silent-failure]
guard: `features_path()` 가 cwd 가 아니라 프로젝트 루트에서 해소한다
exposure: spec-path
---

## Symptoms
- `python night_shift.py` 실행 시 즉시 `"[✅ Success] 모든 기능 구현 완료!"` 출력 후 종료
- 실제로는 `main.py`가 단 한 번도 호출되지 않음 (harness_runtime.log 미생성)
- features.json의 `passes` 값도 그대로

## Root cause
- `night_shift.py:8` 의 `open('features.json', ...)` 이 cwd 기준 상대 경로로 열림
- features.json의 실제 위치는 `web_target/features.json` → `FileNotFoundError`
- `get_next_task` 가 FileNotFoundError를 받으면 `None` 을 반환했고
- `main()` 루프는 `next_feature is None` 을 "모든 기능 완료" 로 해석 → 거짓 성공 메시지
- 누락 파일과 전체 완료를 구별하지 못한 것이 본질

## Fix
- `night_shift.py` 상단에 `PROJECT_DIR = Path(__file__).parent`, `TARGET_DIR = PROJECT_DIR / "web_target"`, `FEATURES_PATH = TARGET_DIR / "features.json"` 도입
- `get_next_task()` 는 항상 절대 경로로 파일 접근
- 파일이 없을 때 `FeaturesFileMissing` 예외를 raise → `main()` 에서 exit code 2로 종료
- `subprocess.Popen` 에 `cwd=str(PROJECT_DIR)` 를 명시해 cwd 의존성 제거

## Verification
1. `web_target/features.json` 를 임시로 이름 변경 → `python night_shift.py` 가 명시적 에러 메시지와 exit 2로 종료 (이전처럼 거짓 성공 안 남)
2. 파일 복원 → 정상 동작
3. 어느 디렉토리에서 실행해도 동일 결과

## Prevention
- 스크립트의 모든 파일 접근은 `Path(__file__).parent` 기준 절대 경로로 고정
- 누락/빈 상태/완료 상태는 **별개 exit 경로**로 분리 (하나의 `None` 으로 뭉뚱그리지 않기)
