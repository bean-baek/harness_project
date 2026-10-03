---
id: TS-002
title: Windows cp949 콘솔에서 main.py의 이모지 출력이 UnicodeEncodeError로 중단
date: 2026-04-14
category: encoding
severity: high
status: resolved
component: night_shift.py
tags: [windows, cp949, pythonioencoding, subprocess]
guard: PYTHONIOENCODING=utf-8 + 하네스 출력에 이모지를 쓰지 않는다
exposure: console-encoding
resolution: accept
---

## Symptoms
- `night_shift.py` → `main.py` 자식 프로세스 실행 직후 다음 에러로 중단

```
UnicodeEncodeError: 'cp949' codec can't encode character '\U0001f680' in position 0: illegal multibyte sequence
```

- `\U0001f680` = 🚀 (night_shift.py:21, main.py의 상태 이모지들)
- 한국어 Windows 기본 콘솔 코드페이지 cp949가 BMP 밖 이모지를 인코딩 못 함

## Root cause
- 두 겹의 인코딩 문제가 겹침
  1. **자식(main.py)** 의 `sys.stdout` — `subprocess.PIPE` 로 리디렉션되면 Python은 로케일 인코딩(cp949)을 사용. `print("🚀 ...")` 가 자식 내부에서 이미 터지면서 pipe로 바이트가 흐르기 전에 실패
  2. **부모(night_shift.py)** 도 `print(line)` 시 동일한 문제 가능
- 초기 수정으로 `sys.stdout.reconfigure(encoding='utf-8', ...)` 를 시도했으나 일부 환경(IDE 통합 터미널, 랩핑된 stdout)에서 무시됨

## Fix
`night_shift.py` 두 군데 수정:

1. 부모 stdout/stderr를 명시적으로 새 `TextIOWrapper` 로 교체 (reconfigure보다 견고)
   ```python
   sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                 errors='replace', line_buffering=True)
   sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8',
                                 errors='replace', line_buffering=True)
   ```
2. 자식 환경에 UTF-8 강제
   ```python
   child_env = os.environ.copy()
   child_env["PYTHONIOENCODING"] = "utf-8"
   child_env["PYTHONUTF8"] = "1"
   subprocess.Popen(..., env=child_env, errors='replace')
   ```
- `errors='replace'` 는 최후의 안전망: 디코드/인코드 실패 시 `?` 로 대체하고 크래시는 막음

## Verification
- Windows 10 Korean / cp949 기본 콘솔에서 `python night_shift.py` 실행
- `main.py` 의 `🚀 🤔 ⚡ 💭 🔍 ✅` 이모지 스트리밍 출력이 `UnicodeEncodeError` 없이 흘러나옴
- `harness_runtime.log` 내부에도 이모지가 UTF-8로 정상 저장됨

## Prevention
- 한국/중국/일본 Windows 환경에서 Python CLI 작성 시 기본 체크리스트
  - 부모: `io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')`
  - 자식 Popen: `encoding='utf-8', errors='replace', env={..., 'PYTHONIOENCODING': 'utf-8'}`
- 이모지/한글을 로깅할 모든 라인은 파일 핸들(utf-8 지정)로도 중복 기록해두면 콘솔 실패와 무관하게 증거가 남는다
