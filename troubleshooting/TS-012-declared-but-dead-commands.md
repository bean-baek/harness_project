---
id: TS-012
title: package.json이 광고하는 명령 3개(lint/build/test:e2e)가 전부 동작하지 않았다
date: 2026-10-01
category: config
severity: high
status: resolved
component: web_target/package.json
tags: [toolchain, dead-command, path-drift, eslint, vite, playwright]
---

## Symptoms
병합 전 "한 번도 돌려보지 않은 명령"을 전수 실행한 결과, **4개 중 3개가 실패**했다.

| 명령 | 실제 exit | 증상 |
|---|---|---|
| `npm run lint` | 실패 | `ESLint couldn't find an eslint.config file` |
| `npm run build` | **2** | TS 오류 5건 — **앱을 빌드할 수 없는 상태** |
| `npm run test:e2e` | 1 | CSS 파일을 모듈로 파싱하려다 죽음 |
| `npm test` | 1 | 테스트 42/42 통과, 커버리지 44% vs 임계 80% |

세 명령 모두 `package.json` 에 선언되어 있고 README·스킬에서 참조되는데,
**단 한 번도 성공한 적이 없다.** 아무도 돌려보지 않았기 때문에 드러나지 않았다.

## Root cause
각각 원인이 다르지만 **"선언과 실제의 불일치가 실행되지 않아 유지된다"** 는 공통점이 있다.
이 프로젝트에서 같은 부류가 이번이 네 번째다 — TS-001(루트 `features.json`),
`scripts/init.sh` 의 PROJECT_ROOT, TS-006 의 `run_tests`(npx 해석 실패), 그리고 이번 3건.

- **lint**: ESLint 9 가 설치됐는데 설정 파일이 없다. v9 는 플랫 설정(`eslint.config.js`)을
  요구하고 `.eslintrc.*` 도 없었다. 설정 없이 스크립트만 선언되어 있었다.
- **build**: `src/mocks/handlers.ts` 가 **설치되지 않은 `msw`** 를 임포트했다.
  그 파일은 **어디서도 임포트되지 않는 죽은 코드**였다(참조 0건). TS 오류 5건 중 4건이 여기서 나왔다.
  남은 1건은 `api.ts` 의 `import.meta.env` — `vite/client` 타입 참조가 없었다.
- **test:e2e**: `playwright.config.ts` 가 **루트에** 있고 `testDir: './tests'` 였다.
  루트에는 `tests/` 가 없고 스펙은 `web_target/tests/` 에 있다. `web_target` 에서 실행하면
  같은 디렉터리의 jest 테스트(`*.test.tsx`)까지 수집해 CSS 를 파싱하려다 죽었다.
  루트에서 실행하면 `@playwright/test` 를 해석하지 못했다(의존성은 `web_target/node_modules`).

## Fix
- **lint** — `web_target/eslint.config.js` 신설. **설치된 플러그인만** 사용한다
  (`@typescript-eslint`). `eslint-plugin-react` 는 설치되어 있지 않으므로 끌어오지 않았다 —
  없는 의존성을 전제하면 또 하나의 죽은 명령이 된다.
  규칙은 실제 결함으로 이어지는 것만 error (미사용 변수, no-undef, 도달 불가 코드 등).
  적발된 8건 중 **5건은 설정이 브라우저 전역(`atob`/`btoa`/`setInterval`/`clearInterval`)을
  빠뜨린 내 실수**, 3건은 실제 결함이었다:
  - `LoadingSpinner` 의 `fullPage` prop 이 **선언만 되고 본문에서 쓰이지 않았다** —
    `<LoadingSpinner fullPage />` 가 일반 호출과 완전히 동일하게 동작했다.
    호출자(Suspense fallback, ProtectedRoute)의 의도대로 실제 전체 화면 로딩으로 구현했다.
  - `NotificationContext` 의 미사용 setter, `UserMenu.test` 의 미사용 `container` 제거.
- **build** — `src/mocks/` 삭제(죽은 코드 + 미설치 패키지), `src/vite-env.d.ts` 에
  `/// <reference types="vite/client" />` 추가. tsconfig 의 `types` 배열을 건드리지 않는
  Vite 표준 방식이다 — `types` 를 지정하면 jest 전역이 깨진다.
- **test:e2e** — `playwright.config.ts` 를 `web_target/` 으로 이동(`git mv`).
  `testDir: './tests'`, `testMatch: '**/*.spec.ts'`(jest 파일 배제), `webServer.cwd: '.'`.

## Verification
- `npm run lint` → **exit 0**
- `npm run build` → **exit 0**, `dist/` 생성 (vendor 165KB, charts 382KB). 이 프로젝트 최초의 성공한 빌드.
- `npm test` → 42/42 통과 (커버리지 임계는 여전히 미달 — 별개 관심사)
- `npx playwright test --list` → **18개 정상 수집** (chromium + mobile × 9)
- 하네스 회귀: `repro_ts005/006/008/009/010` 전부 exit 0, 게이트 판정 불변

**미해결**: `npm run test:e2e` 실행 자체는 아직 실패한다. 원인은 코드가 아니라 환경 —
이 Playwright 버전이 요구하는 브라우저 바이너리(`chromium_headless_shell-1217`, `webkit-2272`)가
없다(설치된 것은 `chromium-1223/1234`). `npx playwright install` 이 필요하며 수백 MB
다운로드이므로 실행하지 않았다. 설정 결함은 해소되었고 남은 것은 설치 작업이다.

## Prevention
- **선언한 명령은 전부 한 번씩 돌려볼 것.** `package.json` 의 `scripts` 는 광고다.
  돌려보지 않은 스크립트는 동작한다는 증거가 없다.
- **설정 파일은 그 의존성이 있는 곳에 둘 것.** 루트 설정 + 하위 `node_modules` 조합은
  어느 디렉터리에서 실행해도 깨진다.
- 하위 디렉터리로 프로젝트를 옮겼다면 **루트에 남은 설정 파일을 전수 점검할 것**.
  이 프로젝트에서 같은 부류가 네 번 반복됐다.
- 린트 설정은 **설치된 플러그인만** 참조할 것.
- 쓰이지 않는 파일이 미설치 패키지를 임포트하면 빌드 전체가 멈춘다.
  참조 0건인 파일은 삭제가 정답이다.
- **E2E 증거는 게이트에 계수되지 않는다** — `smoke.spec.ts` 에 이미 F-005 테스트가
  있었지만 게이트는 jest 만 실행한다. E2E 로만 검증된 기능은 증거가 없는 것으로 취급된다.
