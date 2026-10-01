/**
 * web_target/src/__tests__/AppRoutes.test.tsx
 * ────────────────────────────────────────────
 * **앱이 실제로 선언한 라우트**를 검증한다.
 *
 * 왜 따로 필요한가 (TS-013):
 *   ProtectedRoute.test.tsx 는 컴포넌트를 검증하지만, 테스트가 `<Route path="/dashboard">` 를
 *   **직접 만들어** 감싼다. 그래서 "앱에 /dashboard 라우트가 존재하는가"는 구조적으로
 *   검증할 수 없었다. 실제로 앱에는 그 라우트가 없었고, /dashboard 는 보호되지 않는
 *   404 로 떨어져 F-005 가 실 브라우저에서 전혀 동작하지 않았다 — jest 는 전부 통과했다.
 *
 *   그 간극을 메우려면 라우트 테이블 자체를 테스트가 만들지 않고 **앱에서 가져와야** 한다.
 *   App.tsx 는 BrowserRouter 를 내장하므로 전체를 렌더링하는 대신, 보호 라우트 목록을
 *   한 곳에서 선언하고 앱과 테스트가 공유한다.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { PROTECTED_PATHS } from '../routes';
import { useAuth } from '../contexts/AuthContext';

jest.mock('../contexts/AuthContext');
const mockUseAuth = useAuth as jest.Mock;

const LoginProbe: React.FC = () => {
  const location = useLocation();
  return <div data-testid="login" data-search={location.search}>로그인</div>;
};

/** 앱이 선언한 보호 경로 목록을 그대로 라우트로 세운다 (경로를 테스트가 발명하지 않는다). */
const renderAppPaths = (initialPath: string) =>
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<LoginProbe />} />
        {PROTECTED_PATHS.map((path) => (
          <Route
            key={path}
            path={path}
            element={
              <ProtectedRoute>
                <div data-testid="protected">{path}</div>
              </ProtectedRoute>
            }
          />
        ))}
        <Route path="*" element={<div data-testid="notfound">404</div>} />
      </Routes>
    </MemoryRouter>
  );

describe('F-005: 앱이 선언한 보호 경로 전수 검증', () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });
  });

  test('F-005.1: 명세가 지목한 /dashboard 가 보호 경로 목록에 존재한다', () => {
    // 명세 1단계가 /dashboard 를 직접 지목한다. 목록에 없으면 404 로 떨어진다.
    expect(PROTECTED_PATHS).toContain('/dashboard');
  });

  test.each(PROTECTED_PATHS)(
    'F-005.2: 비로그인 상태로 %s 접근 시 /login 으로 이동한다',
    async (path) => {
      renderAppPaths(path);
      await waitFor(() => {
        expect(screen.getByTestId('login')).toBeInTheDocument();
      });
      expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
      expect(screen.queryByTestId('notfound')).not.toBeInTheDocument();
    }
  );

  test.each(PROTECTED_PATHS)(
    'F-005.3: %s 로 리다이렉트될 때 원래 경로가 ?redirect= 에 보존된다',
    async (path) => {
      renderAppPaths(path);
      const probe = await screen.findByTestId('login');
      const search = probe.getAttribute('data-search') ?? '';
      expect(new URLSearchParams(search).get('redirect')).toBe(path);
    }
  );
});
