---
id: TS-013
title: 단위 테스트가 자기가 만든 라우트를 검증해 F-005가 실 브라우저에서 전혀 동작하지 않았다
date: 2026-10-02
category: testing
severity: high
status: resolved
component: web_target/src/routes.ts
tags: [circularity, integration, e2e, route-table, false-evidence, f-005]
guard: `cli independence` 가 테스트의 자급을 사실로 보고한다
exposure: evidence-independence
---

## Symptoms
F-005(미인증 사용자 리다이렉트)는 jest 게이트를 통과해 `passes: true` 로 기록되어 있었다.
증거도 충실했다 — 태그 테스트 15건, 명세 단계 3/3 커버, `step` 수준에서도 통과.

그런데 E2E 를 처음 실행하자 정면으로 모순됐다.

```
Error: expect(page).toHaveURL(expected) failed
  Expected pattern: /\/login/
  Received string:  "http://localhost:5173/dashboard"
```

비로그인 상태로 `/dashboard` 에 접속해도 **리다이렉트가 전혀 일어나지 않았다.**
즉 F-005 는 실 브라우저에서 동작하지 않는데 모든 단위 테스트가 통과하고 있었다.

## Root cause
**앱에 `/dashboard` 라우트가 존재하지 않았다.** 대시보드는 `/`(index)에 있었고,
`/dashboard` 는 `<Route path="*">` 의 404 로 떨어졌다. 404 는 보호 라우트가 아니므로
가드가 아예 실행되지 않는다.

그런데 왜 jest 가 통과했는가 — **테스트가 라우트를 직접 만들었기 때문이다.**

```tsx
// ProtectedRoute.test.tsx — 테스트가 스스로 선언한 라우트
<Route path="/dashboard" element={<ProtectedRoute>…</ProtectedRoute>} />
```

컴포넌트는 정확히 동작했다. 테스트도 정직했다. 다만 **"앱에 그 라우트가 있는가"는
어느 테스트도 묻지 않았다.** 검증 대상(컴포넌트)과 명세가 지목한 대상(URL)이 달랐고,
그 간극을 테스트 자신이 메워버렸다.

보강 증거: `Layout.tsx` 의 네비게이션은 이미 `<NavLink to="/dashboard">대시보드</NavLink>`
였다. 즉 **실제 사용자가 "대시보드" 메뉴를 클릭하면 404 가 떴다.** 앱 자신이 없는 주소를
가리키고 있었는데도 51건의 단위 테스트 중 아무것도 걸리지 않았다.

이것은 "증거 게이트가 통과시킨 것이 틀릴 수 있다"는 구체적 사례다 —
TS-008 이 남긴 주관성("태그된 테스트가 제대로 검증하는지는 보지 않는다")이 실현된 형태이고,
단위 테스트만으로는 **구조적으로** 닫을 수 없는 종류의 간극이다.

## Fix
- **[web_target/src/routes.ts](../web_target/src/routes.ts) (신설)** — 보호 경로 목록의 단일 출처.
  `PROTECTED_PATHS = ['/', '/dashboard', '/profile', '/settings']`
- **[web_target/src/App.tsx](../web_target/src/App.tsx)** — 라우트를 그 목록에서 **생성**한다.
  목록을 읽기만 하는 테스트는 또 하나의 가짜 앵커이므로, 앱이 실제로 그것을 소비해야 한다.
  페이지 연결은 `PAGE_BY_PATH: Record<ProtectedPath, React.ReactNode>` 로 두어
  **타입 검사가 양방향 완전성을 강제**한다 — 목록에 경로를 추가하고 페이지를 연결하지 않거나,
  매핑에만 적고 목록에 없으면 컴파일이 실패한다.
- **[web_target/src/__tests__/AppRoutes.test.tsx](../web_target/src/__tests__/AppRoutes.test.tsx) (신설)** —
  경로를 발명하지 않고 `PROTECTED_PATHS` 를 순회한다. 보호 경로가 늘어나면
  "미인증 시 리다이렉트 + 원래 경로 보존" 검증이 자동으로 따라붙는다.

## Verification
- 새 테스트 **9건 통과** (경로 4개 × 리다이렉트/보존 + 목록 포함 검사 1건).
- **돌연변이 검사** — `PROTECTED_PATHS` 에서 `/dashboard` 를 제거해 원래 버그를 재현하자
  **두 겹에서 잡혔다**:
  1. 타입 검사: `TS2353: ''/dashboard'' does not exist in type 'Record<"/profile" | "/settings" | "/", ReactNode>'`
  2. 테스트: `F-005.1: 명세가 지목한 /dashboard 가 보호 경로 목록에 존재한다` 실패
  복원 후 9/9 통과. 이번 테스트는 장식이 아니다.
- **실 브라우저**: `npx playwright test -g "F-005"` → **2 passed** (chromium + mobile).
  수정 전에는 같은 테스트가 실패했다.
- 전체: jest **51/51** (7 suites), E2E **10/18 통과**(수정 전 8/18 — F-005 2건이 전환),
  `tsc --noEmit` 오류 0, lint exit 0, build exit 0.
- F-005 플래그는 발견 직후 `unmark` 로 회수했고, 실 브라우저 통과를 확인한 뒤
  `mark` 로 복구했다 — `suite 51/51 passed | tagged 24 passed | steps 3/3 covered`.

## Prevention
- **테스트가 검증 대상의 구조를 공급하면 그 구조는 검증되지 않는다.**
  라우트·설정·스키마처럼 "앱이 선언하는 것"은 테스트가 만들지 말고 **앱에서 가져와야** 한다.
- 명세가 구체적인 URL·경로·키를 지목하면, **그것이 앱에 실재하는지** 먼저 확인할 것.
  F-005 의 명세는 `/dashboard` 를 세 번 적었고 앱에는 없었다.
- 단일 출처를 만들었다면 **앱이 실제로 그것을 소비하는지** 확인할 것.
  목록을 테스트만 읽으면 드리프트가 그대로 남는다 (처음 `routes.ts` 를 만들었을 때가 그랬다).
- 가능하면 타입으로 묶을 것. `Record<Union, T>` 는 목록과 구현의 완전성을 컴파일 시점에 강제한다.
- **E2E 는 단위 테스트가 구조적으로 볼 수 없는 것을 본다.** 한 번도 돌리지 않은 E2E 는
  그 능력이 0이다 (TS-012 에서 이 스위트는 설정 오류로 실행조차 되지 않았다).
- 증거 게이트의 통과는 "회귀가 없다"는 뜻이고 "명세를 충족한다"는 뜻이 아니다.
  통합 경로의 확인은 별도로 필요하다.
