// web_target/eslint.config.js
//
// ESLint 9 플랫 설정. 이전에는 설정 파일이 아예 없어서 `npm run lint` 가
// "couldn't find an eslint.config file" 로 실패했다 — 즉 린트가 한 번도 돌지 않았다.
//
// 설치된 것만 사용한다 (@typescript-eslint). eslint-plugin-react / react-hooks 는
// 설치되어 있지 않으므로 규칙을 끌어오지 않는다 — 없는 의존성을 전제하면
// 또 "선언만 있고 동작하지 않는 명령"이 된다.

import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';

export default [
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**', '**/*.d.ts'],
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        // 브라우저
        window: 'readonly',
        document: 'readonly',
        localStorage: 'readonly',
        fetch: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        atob: 'readonly',
        btoa: 'readonly',
        HTMLElement: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLImageElement: 'readonly',
        HTMLDivElement: 'readonly',
        MouseEvent: 'readonly',
        Node: 'readonly',
        URLSearchParams: 'readonly',
        // 테스트 (jest)
        describe: 'readonly',
        it: 'readonly',
        test: 'readonly',
        expect: 'readonly',
        jest: 'readonly',
        beforeEach: 'readonly',
        afterEach: 'readonly',
        beforeAll: 'readonly',
        afterAll: 'readonly',
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      // 실제 결함으로 이어지는 것만 error — 스타일 취향은 규칙으로 강제하지 않는다.
      'no-undef': 'error',
      'no-unused-vars': 'off',                       // TS 버전으로 대체
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-debugger': 'error',
      'no-dupe-keys': 'error',
      'no-unreachable': 'error',
      'no-constant-condition': 'error',
      // 남겨둔 console.error 가 많아 경고로만 (--max-warnings 0 이므로 실제로는 막힌다)
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
];
