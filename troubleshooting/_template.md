---
id: TS-NNN
title: 한 줄 제목
date: YYYY-MM-DD
category: runtime
severity: medium
status: open
component: path/to/file.py
tags: []
---

## Symptoms
- 관측된 현상 (스택트레이스/에러 메시지는 백틱 블록에 원문 그대로)
- 재현 조건: 어떤 OS/Python/의존성 버전/명령어에서 발생했는가

```
(에러 원문 붙여넣기)
```

## Root cause
- 왜 발생했는가. 문제 코드 경로 (`file.py:line`) 명시
- 숨어있던 가정/계약 위반은 한 문장으로 요약

## Fix
- 변경한 파일과 핵심 변경점 (bullet)
- 우회책이 아닌 **근본 수정**이면 그 이유를 짧게

## Verification
- 수정 적용 후 실행한 재현 절차
- 기대 결과 vs 실제 결과

## Prevention
- 동일 부류 재발 방지 체크리스트 (선택)
