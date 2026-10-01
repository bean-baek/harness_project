import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { ProtectedRoute } from './ProtectedRoute';
import { useAuth } from '../contexts/AuthContext';
import { safeRedirectTarget } from './LoginForm';

jest.mock('../contexts/AuthContext');
const mockUseAuth = useAuth as jest.Mock;

const mockUser = {
  id: 'user-123',
  email: 'test@example.com',
  name: 'Test User',
  isAdmin: false,
  avatarUrl: 'https://i.pravatar.cc/40',
};

/** /login 라우트에 세워 두는 관측용 컴포넌트 — 쿼리스트링을 노출한다. */
const LoginProbe: React.FC = () => {
  const location = useLocation();
  return <div data-testid="login-page" data-search={location.search}>로그인 페이지</div>;
};

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginProbe />} />
        <Route path="/" element={<div data-testid="home">홈</div>} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <div data-testid="protected">보호된 대시보드</div>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute requireAdmin>
              <div data-testid="admin">관리자 영역</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );

describe('F-005: 인증되지 않은 사용자가 보호된 페이지 접근 시 로그인으로 리다이렉트', () => {
  test('F-005.1 F-005.2: 비로그인 상태로 /dashboard 에 접속하면 /login 으로 이동한다', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/dashboard');

    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  test('F-005.3: 리다이렉트 후 원래 URL 이 ?redirect= 로 보존된다', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/dashboard?tab=week');

    const search = screen.getByTestId('login-page').getAttribute('data-search') ?? '';
    const redirect = new URLSearchParams(search).get('redirect');
    // 경로와 쿼리스트링이 함께 보존되어야 한다 (window.location 을 쓰면 쿼리가 유실된다)
    expect(redirect).toBe('/dashboard?tab=week');
  });

  test('인증된 사용자는 보호된 내용을 그대로 본다', () => {
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/dashboard');

    expect(screen.getByTestId('protected')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  test('토큰 검증 중(isLoading)에는 리다이렉트하지 않는다 — 새로고침 로그아웃 방어', () => {
    // AuthContext 는 isLoading=true 로 시작한다. 이때 리다이렉트하면
    // 로그인한 사용자가 새로고침마다 로그아웃된다.
    mockUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: true,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/dashboard');

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  test('requireAdmin 라우트에 비관리자가 접근하면 홈으로 되돌린다', () => {
    mockUseAuth.mockReturnValue({
      user: { ...mockUser, isAdmin: false },
      isAuthenticated: true,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/admin');

    expect(screen.getByTestId('home')).toBeInTheDocument();
    expect(screen.queryByTestId('admin')).not.toBeInTheDocument();
  });

  test('requireAdmin 라우트에 관리자는 접근할 수 있다', () => {
    mockUseAuth.mockReturnValue({
      user: { ...mockUser, isAdmin: true },
      isAuthenticated: true,
      isLoading: false,
      login: jest.fn(),
      logout: jest.fn(),
    });

    renderAt('/admin');

    expect(screen.getByTestId('admin')).toBeInTheDocument();
  });
});

describe('F-005: 리다이렉트 대상 검증 (오픈 리다이렉트 방어)', () => {
  // ProtectedRoute 가 ?redirect= 에 쓴 값은 로그인 성공 후 이동 대상이 된다.
  // 검증 없이 쓰면 외부 사이트로 끌고 갈 수 있으므로 내부 경로만 허용한다.
  test.each([
    ['/dashboard', '/dashboard'],
    ['/dashboard?tab=week', '/dashboard?tab=week'],
    ['//evil.com', '/'],
    ['/\\evil.com', '/'],
    ['https://evil.com', '/'],
    ['javascript:alert(1)', '/'],
    ['', '/'],
    [null, '/'],
    [undefined, '/'],
  ])('F-005.3: safeRedirectTarget(%p) → %p', (input, expected) => {
    expect(safeRedirectTarget(input as string | null | undefined)).toBe(expected);
  });
});
