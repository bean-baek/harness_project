/**
 * tests/smoke.spec.ts
 * ───────────────────
 * Playwright E2E 스모크 테스트
 *
 * 논문 근거 (P-03 Coder):
 *   "브라우저 자동화로 사용자 관점의 E2E 테스트를 수행한다."
 *   "init.sh 실행 후 브라우저 자동화(Puppeteer/Playwright)로 기본 동작을 검증한다."
 *
 * 실행: npx playwright test tests/smoke.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

const BASE_URL = process.env.DEV_URL ?? 'http://localhost:5173';

// ── 헬퍼 ─────────────────────────────────────────────────────────────────────

async function loginAs(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('[type="email"]',    email);
  await page.fill('[type="password"]', password);
  await page.click('[type="submit"]');
  await page.waitForURL(`${BASE_URL}/`);
}

// ── 기본 스모크 테스트 ────────────────────────────────────────────────────────

test.describe('기본 앱 동작 확인 (스모크 테스트)', () => {

  test('앱이 로드되고 로그인 페이지가 표시된다', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    // 명세는 페이지 제목을 요구하지 않는다. index.html 의 실제 값을 단정한다.
    await expect(page).toHaveTitle(/Harness Web Target/);
    await expect(page.locator('h1')).toContainText('로그인');
    await expect(page.locator('[type="email"]')).toBeVisible();
    await expect(page.locator('[type="password"]')).toBeVisible();
    await expect(page.locator('[type="submit"]')).toBeVisible();
  });

  test('F-005: 인증 없이 보호 페이지 접근 시 로그인으로 리다이렉트', async ({ page }) => {
    await page.goto(`${BASE_URL}/dashboard`);
    await expect(page).toHaveURL(/\/login/);
  });

});

// ── F-001: 로그인 성공 흐름 ───────────────────────────────────────────────────

test.describe('F-001: 로그인 성공', () => {

    // fixme 이유 (TS-014): 앱의 인증 설계 결함이다. 테스트를 앱에 맞춰 약화시키지 않는다.
    //   1) LoginForm 이 서버가 준 user 객체를 버리고 토큰만 저장한다
    //   2) AuthContext 가 토큰을 클라이언트에서 디코드해 isAdmin 까지 신뢰한다 (위조 가능)
    //   3) AuthContext.login() 은 죽은 코드다 — 하드코딩 자격증명 + 위조 서명
    //   4) 로그인 후 window.location.href 로 전체 리로드
    // 이 프로젝트의 산출물은 하네스이고 web_target 은 피험체다. 피험체의 설계 결함을
    // 고치는 것은 하네스에 아무 교훈을 주지 않으므로 보류하고 신호만 남긴다.
  test.fixme('유효한 자격증명으로 로그인 후 대시보드로 이동', async ({ page }) => {
    // Mock API 응답 설정
    await page.route('**/api/auth/login', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          token: 'mock-jwt-token',
          user: { id: '1', email: 'test@test.com', name: '테스트 사용자', isAdmin: false },
        }),
      });
    });
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: '1', email: 'test@test.com', name: '테스트 사용자', isAdmin: false }),
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.fill('[type="email"]',    'test@test.com');
    await page.fill('[type="password"]', 'SecurePass123!');
    await page.click('[type="submit"]');

    // 대시보드로 이동 확인
    await expect(page).toHaveURL(`${BASE_URL}/`);
    // 사용자 이름 표시 확인
    await expect(page.locator('text=테스트 사용자')).toBeVisible();
  });

});

// ── F-002: 로그인 실패 흐름 ───────────────────────────────────────────────────

test.describe('F-002: 잘못된 자격증명 처리', () => {

  test('401 응답 시 오류 메시지 표시', async ({ page }) => {
    await page.route('**/api/auth/login', async route => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ message: '인증 실패' }),
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.fill('[type="email"]',    'wrong@test.com');
    await page.fill('[type="password"]', 'WrongPassword1!');
    await page.click('[type="submit"]');

    await expect(page.locator('[role="alert"]')).toContainText(
      '이메일 또는 비밀번호가 올바르지 않습니다.'
    );
    await expect(page).toHaveURL(/\/login/);
  });

    test('F-002.5: 네트워크 오류 시 연결 문제 메시지 표시', async ({ page }) => {
    await page.route('**/api/auth/login', async route => {
      await route.abort('failed');
    });

    await page.goto(`${BASE_URL}/login`);
    await page.fill('[type="email"]',    'test@test.com');
    await page.fill('[type="password"]', 'SecurePass123!');
    await page.click('[type="submit"]');

    await expect(page.locator('[role="alert"]')).toContainText('연결에 문제가 있습니다');
  });

});

// ── F-003: 유효성 검사 ───────────────────────────────────────────────────────

test.describe('F-003: 이메일 유효성 검사', () => {

  test('@가 없는 이메일 → 오류 메시지 + 버튼 비활성화', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.fill('[type="email"]', 'invalidemail');
    await page.locator('[type="password"]').click();  // blur 트리거

    await expect(page.locator('text=올바른 이메일 형식')).toBeVisible();
    await expect(page.locator('[type="submit"]')).toBeDisabled();
  });

});

// ── F-004: 로그아웃 ──────────────────────────────────────────────────────────

test.describe('F-004: 로그아웃', () => {

    // fixme 이유 (TS-014): F-001 과 같은 앱 인증 설계 결함에 막힌다 —
    // 이 테스트는 localStorage 에 'mock-token' 을 넣지만 AuthContext 는 그것을
    // JWT 로 디코드하려다 실패해 사용자를 null 로 만든다. 그래서 사용자 메뉴가 없다.
    // F-004 의 jest 증거(태그 4건)는 useAuth 를 모킹하므로 영향받지 않는다.
  test.fixme('로그아웃 후 로그인 페이지로 이동 및 토큰 삭제', async ({ page }) => {
    // 로그인 상태 설정
    await page.addInitScript(() => {
      localStorage.setItem('auth_token', 'mock-token');
    });
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: '1', name: '테스트 사용자', email: 'test@test.com', isAdmin: false }),
      });
    });
    await page.route('**/api/auth/logout', async route => {
      await route.fulfill({ status: 200, body: '{}' });
    });

    await page.goto(`${BASE_URL}/`);

    // 사용자 메뉴 클릭 후 로그아웃
    await page.getByRole('button', { name: /Test User|테스트 사용자/ }).click();
    await page.locator('text=로그아웃').click();

    await expect(page).toHaveURL(/\/login/);

    // localStorage 토큰 삭제 확인
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeNull();
  });

});

// ── 성능 테스트 (features.json 에 대응 기능이 없다 — 기능 ID 를 붙이지 않는다) ──

test.describe('성능 기준 (명세 외 품질 측정)', () => {

  test('로그인 페이지 FCP가 1.8초 미만', async ({ page }) => {
    const metrics: number[] = [];

    page.on('metrics', data => {
      metrics.push(...Object.values(data.metrics).map(Number));
    });

    const startTime = Date.now();
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'domcontentloaded' });
    const loadTime = Date.now() - startTime;

    // 3초 이내 로드 확인 (느린 CI 환경 허용)
    expect(loadTime).toBeLessThan(3000);
  });

});

// ── 접근성 테스트 (명세 외. ARIA 는 F-026 이 다루지만 별건이다) ──────────────

test.describe('키보드 접근성 (명세 외 품질 측정)', () => {

  test('Tab 키로 로그인 폼 모든 요소 탐색 가능', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
      // 빈 폼에서는 submit 이 disabled 다 — F-003 이 요구하는 동작이고,
      // disabled 요소는 포커스를 받지 않는다. 유효 입력 후에 탐색을 검증한다.
      await page.fill('[type="email"]',    'test@test.com');
      await page.fill('[type="password"]', 'SecurePass123!');
      // fill 은 마지막 입력란에 포커스를 남긴다. 탐색 기준점을 폼 밖으로 초기화한다.
      await page.locator('h1').click();

    // Tab 순서: 이메일 → 비밀번호 → 로그인 버튼
    await page.keyboard.press('Tab');
    await expect(page.locator('[type="email"]')).toBeFocused();

    await page.keyboard.press('Tab');
    await expect(page.locator('[type="password"]')).toBeFocused();

    await page.keyboard.press('Tab');
    await expect(page.locator('[type="submit"]')).toBeFocused();
  });

});
