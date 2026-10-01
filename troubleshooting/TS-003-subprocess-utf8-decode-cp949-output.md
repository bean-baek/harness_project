---
id: TS-003
title: tools.py subprocess가 npm/jest/git의 cp949 출력을 UTF-8로 디코딩하다 _readerthread 크래시
date: 2026-04-14
category: encoding
severity: high
status: resolved
component: harness/tools.py
tags: [windows, cp949, subprocess, readerthread, utf-8, jest, npm]
---

## Symptoms
- `jest_run` / `bash_command` 도구 실행 중 백그라운드 리더 스레드에서 다음 예외

```
Exception in thread Thread-2 (_readerthread):
  ...
  File ".../subprocess.py", line 1515, in _readerthread
    buffer.append(fh.read())
  File ".../codecs.py", line 322, in decode
    (result, consumed) = self._buffer_decode(data, self.errors, final)
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0 in position 5: invalid start byte
```

- 자식(npm/jest/git/npx)의 stdout/stderr는 정상적으로 흘러나오다가 특정 바이트에서 터짐
- `subprocess.run(..., capture_output=True, text=True)` 호출이 내부적으로 `communicate()` → `_readerthread` 를 띄우는 Windows 경로에서 발생

## Root cause
- TS-002와 반대 방향의 인코딩 불일치: **부모가 자식 출력을 UTF-8로 디코딩**하려 함
- 한국어 Windows에서 npm/jest/git은 기본 콘솔 코드페이지 **cp949**로 출력
- 바이트 `0xC0`은 cp949에서는 정상 선두 바이트지만 UTF-8 스펙상 금지된 값 (오버롱 시퀀스)
- 문제 코드
  - `harness/tools.py:163` (`jest_run`) — `text=True` 만 지정, `encoding` 미지정
  - `harness/tools.py:200` (`bash_command`) — 동일
- `text=True` + `encoding` 누락 시 Python은 `locale.getencoding()` 또는 UTF-8(PYTHONUTF8=1) 으로 디코딩 → 자식이 cp949로 뱉으면 실패

## Fix
`harness/tools.py` 두 군데 모두 `encoding="utf-8", errors="replace"` 추가

```python
result = subprocess.run(
    cmd,
    cwd=project_root,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",   # 디코딩 실패 시 � 로 대체, 크래시 방지
    timeout=120,
)
```

- `errors="replace"` 가 핵심: 자식이 무엇을 뱉든 `_readerthread` 가 살아남음
- TS-002에서 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` 을 child_env로 주입했지만, 이는 **자식이 파이썬일 때만** 효과가 있음. npm/jest/git 같은 비파이썬 프로세스엔 적용 안 됨

## Verification
- 수정 후 `night_shift.py` → `main.py` → `jest_run("web_target")` 흐름 실행
- 이전에 `0xc0` 에서 터지던 지점이 `�` 로 치환되며 테스트 출력이 끝까지 스트리밍됨
- `_readerthread` 예외 스택트레이스가 `harness_runtime.log`에 더 이상 기록되지 않음

## Prevention
- Windows에서 `subprocess.run/Popen` + `text=True` 조합은 **항상** `encoding` 과 `errors` 를 명시한다
- 비파이썬 자식(npm/node/git/gcc 등) 출력을 캡처할 때 기본값
  ```python
  text=True, encoding="utf-8", errors="replace"
  ```
- 로케일에 민감한 자식이면 `encoding="cp949"` 로 맞추는 게 더 정확하지만, 다국어 혼재 환경에선 `utf-8 + replace` 가 실용적
- 체크리스트: `subprocess\.(run|Popen)` 을 grep해 `encoding=` 과 `errors=` 가 둘 다 있는지 확인
