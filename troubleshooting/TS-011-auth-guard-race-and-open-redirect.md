---
id: TS-011
title: 라우트 가드가 isLoading을 무시해 새로고침마다 로그아웃 + ?redirect= 오픈 리다이렉트
date: 2026-10-01
category: runtime
severity: high
status: resolved
component: web_target/src/components/ProtectedRoute.tsx
tags: [auth, race-condition, open-redirect, security, f-005]
guard: 피험체 결함 — E2E 가 잡았다. 하네스의 가드 대상이 아니다
exposure: target-app-defect
resolution: accept
---

## Symptoms
F-005(미인증 사용자 리다이렉트)를 구현하려 보니 `App.tsx` 안에 `ProtectedRoute` 가
이미 인라인으로 있었다. 그런데 테스트가 0건이었고, 결함이 세 개 있었다.

- **로그인한 사용자가 새로고침하면 로그인 페이지로 튕긴다.**
- 리다이렉트 URL 에서 쿼리스트링이 유실된다 (`/dashboard?tab=week` → `/dashboard`).
- 로그인 직후 **외부 사이트로 끌려갈 수 있다** (`?redirect=https://evil.com`).

## Root cause
- **D1 (인증 경쟁 조건)**: `AuthContext` 는 `isLoading=true` 로 시작해 `useEffect` 에서
  저장된 토큰을 확인한다. 가드는 첫 렌더에서 `isAuthenticated` 만 읽으므로
  **토큰 검증이 끝나기 전에** 판단하고, 그 시점의 값은 항상 `false` 다.
  `isLoading` 분기가 없는 가드는 구조적으로 이 버그를 갖는다.
- **D2 (라우터 밖 상태 참조)**: `window.location.pathname` 을 썼다. 쿼리스트링이 빠지고,
  `MemoryRouter` 환경(테스트)에서는 라우터 상태를 전혀 반영하지 못한다.
- **D3 (검증 없는 리다이렉트 싱크)**: `LoginForm` 이 `?redirect=` 값을 그대로
  `window.location.href` 에 넣었다. 입력은 URL 쿼리이고 싱크는 네비게이션이므로
  전형적인 오픈 리다이렉트다. F-005 가 그 입력을 만들어 넣는 쪽이었다.

D1·D2 는 테스트가 0건이어서 드러나지 않았다. D3 는 **증거 게이트가 잡지 못한다** —
테스트는 통과하는데 취약한 경우이기 때문이다. 스킬에 추가한 보안 체크리스트
(`사용자 입력을 그대로 넣지 않는가`)와 자기평가 Q2(`검증하지 않은 가정`)를 수행하다 발견했다.

## Fix
- **[web_target/src/components/ProtectedRoute.tsx](../web_target/src/components/ProtectedRoute.tsx) (신설)**
  — `App.tsx` 의 인라인 구현을 분리하고 세 결함을 고쳤다.
  분리 이유: `App.tsx` 는 페이지를 `lazy()` 로 불러오므로 통째로 렌더링해야 테스트할 수 있었다.
  - `isLoading` 이면 `<LoadingSpinner />` 를 렌더하고 **판단을 보류**한다.
  - `useLocation()` 으로 `pathname + search` 를 함께 보존한다.
- **[web_target/src/components/LoginForm.tsx](../web_target/src/components/LoginForm.tsx)**
  — `safeRedirectTarget()` 추가. 내부 경로(`/`로 시작)만 허용하고
  프로토콜 상대 URL(`//host`)·역슬래시 변형(`/\host`)·절대 URL·`javascript:` 를 `/` 로 떨군다.
  순수 함수로 export 해 직접 단위 검증한다.
- `App.tsx` 는 분리된 컴포넌트를 임포트하고, 쓰이지 않게 된 `useAuth` / `Navigate` 임포트를 제거했다.

## Verification
`web_target/src/components/ProtectedRoute.test.tsx` — **15건 통과**.

- `F-005.1 F-005.2`: 비로그인 `/dashboard` 접근 → `/login` 이동, 보호된 내용 미렌더
- `F-005.3`: `?redirect=` 에 `/dashboard?tab=week` 가 **쿼리까지** 보존
- 인증된 사용자는 보호된 내용을 본다
- **`isLoading=true` 에서는 리다이렉트하지 않는다** (D1 회귀 방어)
- `requireAdmin`: 비관리자 → `/`, 관리자 → 통과
- `safeRedirectTarget` 9건 표 검증 (`//evil.com` / `/\evil.com` / `https://evil.com` /
  `javascript:alert(1)` / 빈 문자열 / null / undefined → 전부 `/`)

게이트 판정: `suite 42/42 passed | tagged 15 passed | steps 3/3 covered` →
F-005 는 `step` 수준에서도 통과한다. 전체 스위트 42/42, 변경 파일 타입 오류 0건.

부수 발견: `repro_ts010.py` 가 "거부되는 예시"로 F-005 를 하드코딩해 두어
F-005 구현과 동시에 4건이 깨졌다. 검증 대상을 `features.json` 에서 **동적으로**
고르도록 고쳤다 (22/22 복구).

## Prevention
- **비동기 인증 상태를 읽는 가드는 `isLoading` 을 반드시 분기할 것.**
  "인증되지 않았다"와 "아직 모른다"는 다른 상태다. 둘을 합치면 로그인 사용자를 내쫓는다.
- 라우팅 판단에 `window.location` 을 쓰지 말 것. 라우터의 `useLocation()` 을 쓴다 —
  쿼리 보존과 테스트 가능성이 함께 따라온다.
- **URL 에서 온 값을 네비게이션 싱크에 넣기 전에 내부 경로인지 검증할 것.**
  `//` 와 `/\` 는 `/` 로 시작하므로 단순 `startsWith('/')` 검사를 통과한다.
- 증거 게이트는 "테스트가 통과하는가"만 본다. **보안·UI·접근성은 게이트 밖**이므로
  완료 선언 전에 체크리스트로 직접 본다 (`.claude/skills/harness/SKILL.md` §6).
- 검증 스크립트를 특정 기능 ID 에 묶지 말 것. 프로젝트가 진행되면 그 기능이 구현되어
  테스트가 깨진다 — 상태에서 동적으로 고른다.
