// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // 이 설정은 web_target/ 안에 있어야 한다 — @playwright/test 와 test:e2e 스크립트가
  // 여기에 있기 때문이다. 루트에 두었을 때는 의존성 해석에 실패했다 (MODULE_NOT_FOUND).
  testDir:   './tests',
  // *.spec.ts 만 E2E 로 수집한다 — 같은 디렉터리에 jest 테스트(*.test.tsx)가 있어
  // 이 제한이 없으면 CSS 를 모듈로 파싱하려다 죽는다.
  testMatch: '**/*.spec.ts',
  timeout:  30_000,
  retries:  process.env.CI ? 2 : 0,
  workers:  process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['line'],
  ],
  use: {
    baseURL:     process.env.DEV_URL ?? 'http://localhost:5173',
    trace:       'on-first-retry',
    screenshot:  'only-on-failure',
    video:       'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile',   use: { ...devices['iPhone 13'] } },
  ],
  webServer: {
    command:            'npm run dev',
    url:                'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    cwd:                '.',
  },
});
