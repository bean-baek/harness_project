---
id: TS-006
title: 에이전트가 테스트 증거 없이 features.json을 자가 채점 — run_tests는 Windows에서 한 번도 동작하지 않았다
date: 2026-10-01
category: runtime
severity: high
status: resolved
component: harness/tools.py
tags: [self-grading, test-evidence, windows, npx, jest, drift, duplication]
guard: `mark` 가 도구로 스위트를 직접 실행하고 통과 테스트를 요구한다
exposure: test-evidence-gate
resolution: accept
---

## Symptoms
- `features.json` 에 4개 기능이 `passes: true` 로 기록되어 있으나, 어떤 항목에도
  테스트 실행 증거가 없다. 플래그는 전부 LLM 의 자기 보고.
- 동시에 `npm test` 는 **7개 테스트 / 2개 스위트 실패** 상태였다 — 아무도 몰랐다.
  features.json 은 "4개 완료"라고 말하고, 실제 스위트는 빨간불.
- F-004(로그아웃)는 3회 시도 후 stuck. 그런데 로그아웃 코드는 **두 번** 구현되어 있었다:
  - `src/components/UserMenu.tsx` — 테스트 2개 스위트가 가리키는 쪽. 커버리지 88%.
    그러나 **앱이 렌더링하지 않는 고아 컴포넌트.**
  - `src/components/layout/UserMenu.tsx` — `Layout.tsx` 가 실제로 렌더링하는 쪽.
    **커버리지 0%.**
  → Evaluator 는 앱에 존재하지 않는 컴포넌트의 테스트를 채점하고 있었다.

## Root cause
네 개의 결함이 한 증상으로 합쳐짐:

- **D1 (증거 게이트 부재)**: `update_features(passes=True)` 가 아무 검증 없이 플래그를 썼다.
  "테스트를 먼저 실행하십시오"는 **docstring 안의 권고**일 뿐 강제력이 없었다.
  LLM 이 자기 성적표를 직접 쓰는 구조 → 모든 진척 지표가 반증 불가능.
- **D2 (run_tests 가 Windows 에서 전면 불능)**: `subprocess.run(["npx", ...])` 는
  `shell=False` 에서 `npx.cmd` 를 해석하지 못해 **항상** `FileNotFoundError` →
  `"[오류] Jest를 찾을 수 없습니다"`. 즉 에이전트는 **단 한 번도 테스트를 돌린 적이 없다.**
  D1 과 결합해 "증거를 만들 수단이 없고, 증거를 요구하지도 않는" 완전한 공백이 생겼다.
- **D3 (jest 설정 오타가 조용히 무시됨)**: `jest.config.ts` 의 `setupFilesAfterFramework` 는
  Jest 옵션이 아니다(올바른 키: `setupFilesAfterEnv`). Validation Warning 한 줄만 남기고
  무시되어 `@testing-library/jest-dom` 매처가 로드되지 않았다 →
  `toBeInTheDocument is not a function` 으로 3개 테스트 실패.
- **D4 (테스트 자체의 결함)**: 나머지 4개 실패는
  ① `AuthContext` 가 export 되지 않아 `AuthContext.Provider` 가 undefined,
  ② 항목이 `role="menuitem"` 인데 테스트는 `role: 'button'` 으로 질의(menuitem 이 암묵 role 을 덮어씀),
  ③ `handleLogout` 이 `await logout()` 후 navigate 하는데 단정이 동기 — 항상 0 call.

인과: **D2 가 증거 생산을 막고 → D1 이 증거를 요구하지 않고 → 빨간 스위트와 중복
컴포넌트가 누적되어도 features.json 은 계속 "통과"라고 보고했다.**

## Fix
### 하네스 (증거 게이트)
- [harness/tools.py](../harness/tools.py)
  - `_jest_launcher(project_root)` 신설 — `node_modules/.bin/jest.cmd` 우선, 없으면
    `shutil.which("npx")`(PATHEXT 처리). **절대 경로 필수**: `cwd=project_root` 로
    전환되므로 상대 경로 런처는 "지정된 경로를 찾을 수 없습니다" 로 실패한다.
    `test_path` 가 에이전트 입력이므로 `shell=True` 문자열 보간은 쓰지 않는다(명령 주입 방지).
  - `_run_jest()` / `_summarize_jest()` / `_failing_tests()` 를 `@tool` 밖 평범한 함수로 분리 —
    `run_tests` 도구와 증거 게이트가 같은 실행 경로를 공유한다.
  - `update_features(passes=True)` → **도구가 직접 전체 스위트를 실행**하고 통과해야만 플래그를 쓴다.
    실패 시 `[거부]` + 실패 테스트 목록 반환, 플래그 무변경.
    통과 시 `verification {verified_at, verified_by, summary}` 를 해당 feature 항목에 기록 → 감사 가능.
  - 테스트 경로는 **도구가 `"."` 로 고정** — 에이전트가 쉬운 테스트만 골라 돌려 통과를
    조작할 수 없다. `passes=False` 는 증거 없이 허용하고 과거 증거를 제거한다.
- [config.py](../config.py) — `REQUIRE_TEST_EVIDENCE`(기본 true, `HARNESS_REQUIRE_TEST_EVIDENCE`).
  **운영자만** 끌 수 있고 에이전트에게는 우회 수단이 없다. 우회 시 결과 메시지에 경고가 붙는다.
- 커버리지 임계값(80%)은 게이트에서 **의도적으로 제외**했다. 현재 실측 37% 이므로
  커버리지로 게이팅하면 모든 기능이 영구 미완성으로 묶인다. 게이트의 판정 대상은 '테스트 통과'.

### 대상 앱 (중복 제거 + 빨간 스위트 복구)
- `src/components/UserMenu.tsx` 를 단일 정본으로 확정. 선택 근거: 테스트가 가리키는 쪽이고,
  ARIA 역할(`menu`/`menuitem`, `aria-expanded`)을 갖추고(F-026 대비),
  `navigate()` 로 SPA 라우팅을 유지한다(고아 쪽은 `<a href>` 라 전체 리로드 → 인증 상태 소실).
- 사용자에게 보이던 것을 잃지 않도록 고아 쪽의 드롭다운 헤더(이름/이메일)와 '설정' 항목을 이관.
  이관 시 하드코딩 색상(#111/#666/#f0f0f0)은 테마 토글(F-019)에서 깨지므로 CSS 변수로 재작성.
- `Layout.tsx` 임포트를 정본으로 변경, `src/components/layout/UserMenu.{tsx,css}` 삭제.
- `jest.config.ts`: `setupFilesAfterFramework` → `setupFilesAfterEnv`.
- `AuthContext.tsx`: `AuthContext` export (테스트가 Provider 를 직접 주입할 수 있어야 한다).
- `tests/UserMenu.test.tsx`: 항목 질의를 `role: 'button'` → `'menuitem'` 으로 정정(컴포넌트의
  ARIA 가 옳고 테스트가 틀렸다), 로그아웃 단정을 `await waitFor(...)` 로 전환.
  **행위 단정(logout 호출·navigate('/login')·개폐·외부 클릭·비로그인 시 렌더 없음)은 그대로 유지** —
  변경한 것은 라벨/역할 질의와 비동기 대기뿐이다.

## Verification
`repro_ts006.py` — jest 를 스텁으로 교체, **31/31 PASS**.

- 테스트 실패 → `[거부]`, 플래그 무변경, 증거 미기록, 실패 테스트 이름 노출
- 테스트 통과 → 플래그 반영 + `verification` 기록(출처 `update_features/jest`, 타임스탬프, 요약)
- 실행 불가(타임아웃/jest 없음) → `[거부]` + 원인 전달
- `passes=False` → 증거 없이 허용, 과거 증거 제거, jest 재실행 없음
- 운영자 우회(`REQUIRE_TEST_EVIDENCE=false`) → 허용되지만 결과에 비활성 경고
- 게이트가 `test_path="."` 와 `coverage=False` 를 강제함을 호출 인자로 확인
- 회귀: 인덱스 범위 초과 / features.json 없음 → 기존 `[오류]` 경로 유지

**실 환경 E2E**
- `_jest_launcher('web_target')` → `.../node_modules/.bin/jest.cmd` (절대 경로),
  `_run_jest()` → **returncode 0** — 이 환경에서 run_tests 가 처음으로 실제 동작.
- 대상 앱 스위트: 7 failed/20 passed → **27 passed / 27 total, 5 suites passed**.
  (`npm test` 는 커버리지 임계값 때문에 여전히 exit 1 — 테스트 실패는 0건.)
- 변경한 파일(UserMenu/Layout/AuthContext/tests)에 대한 `tsc --noEmit` 오류 0건.
  남은 5건은 기존 문제(`api.ts` 의 `import.meta.env` 타입, `handlers.ts` 의 msw 미설치).
- 게이트를 통한 F-004 승격: `update_features(feature_index=3, passes=True)` →
  `[완료] ... (증거: Test Suites: 5 passed, 5 total | Tests: 27 passed, 27 total)`.
  **이 프로젝트 최초의 '입증된' 통과** — 플래그와 증거가 함께 기록됨.

## Prevention
- 에이전트가 자기 성적표를 쓰게 하지 말 것. 완료 플래그는 **도구가 검증하고 증거를 함께 기록**한다.
- 검증 범위(테스트 경로)는 도구가 고정할 것 — 범위를 에이전트가 정하면 통과는 조작 가능해진다.
- Windows 에서 `subprocess` + node 툴체인은 `shutil.which` 또는 `node_modules/.bin/*.cmd`
  **절대 경로**로 호출할 것. `["npx", ...]` + `shell=False` 는 조용히 전멸한다.
- 도구가 "실행 실패"를 반환할 때 그것을 "테스트 실패"와 같은 등급으로 처리하지 말 것
  (게이트는 둘을 구분해 거부 사유를 다르게 보고한다).
- 설정 파일의 오타는 조용히 무시된다. Validation Warning 을 로그 노이즈로 넘기지 말 것.
- 같은 기능이 두 곳에 구현되면 테스트는 둘 중 하나만 본다. 커버리지 0% 파일이
  실제 렌더링 경로에 있으면 즉시 의심할 것.
