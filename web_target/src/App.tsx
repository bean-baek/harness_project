/**
 * web_target/src/App.tsx
 * ──────────────────────
 * 앱 루트 컴포넌트 + 라우팅
 * 하네스 에이전트가 각 라우트 컴포넌트를 순차적으로 구현한다.
 */

import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider }          from './contexts/AuthContext';
import { ThemeProvider }         from './contexts/ThemeContext';
import { NotificationProvider }  from './contexts/NotificationContext';
import { Layout }                from './components/Layout';
import { LoadingSpinner }        from './components/ui/LoadingSpinner';
import { ProtectedRoute }       from './components/ProtectedRoute';
import { PROTECTED_PATHS, type ProtectedPath } from './routes';

// ── 지연 로딩 (번들 크기 최적화) ──────────────────────────────────────────────
const LoginPage     = lazy(() => import('./pages/LoginPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const UsersPage     = lazy(() => import('./pages/admin/UsersPage'));
const ProfilePage   = lazy(() => import('./pages/ProfilePage'));
const SettingsPage  = lazy(() => import('./pages/SettingsPage'));
const NotFoundPage  = lazy(() => import('./pages/NotFoundPage'));

// ── 보호 경로 → 페이지 매핑 ───────────────────────────────────────────────────
// Record<ProtectedPath, …> 이므로 routes.ts 의 목록과 **양방향으로** 묶인다.
// 경로를 목록에 추가하고 여기 연결하지 않으면, 또는 여기만 적고 목록에 없으면
// 타입 검사가 실패한다.
const PAGE_BY_PATH: Record<ProtectedPath, React.ReactNode> = {
  '/':          <DashboardPage />,
  '/dashboard': <DashboardPage />,
  '/profile':   <ProfilePage />,
  '/settings':  <SettingsPage />,
};

// ── 앱 라우터 ─────────────────────────────────────────────────────────────────

const AppRouter: React.FC = () => (
  <Suspense fallback={<LoadingSpinner fullPage />}>
    <Routes>
      {/* 공개 라우트 */}
      <Route path="/login" element={<LoginPage />} />

      {/* 보호된 라우트 */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        {/* 보호 경로는 routes.ts 의 PROTECTED_PATHS 에서 생성한다 — 목록이 단일 출처다.
            이전에는 여기에만 라우트를 적고 테스트는 테스트가 만든 경로를 검증해서,
            "앱에 /dashboard 가 있는가"를 아무도 확인하지 않았다. 실제로 없었고
            /dashboard 는 보호되지 않는 404 로 떨어졌다 (TS-013).
            PAGE_BY_PATH 가 Record<ProtectedPath, …> 이므로 목록에 경로를 추가하고
            페이지를 연결하지 않으면 타입 검사가 막는다. */}
        {PROTECTED_PATHS.map((path) =>
          path === '/' ? (
            <Route key={path} index element={PAGE_BY_PATH[path]} />
          ) : (
            <Route key={path} path={path.slice(1)} element={PAGE_BY_PATH[path]} />
          )
        )}

        {/* 관리자 전용 라우트 */}
        <Route
          path="admin/users"
          element={
            <ProtectedRoute requireAdmin>
              <UsersPage />
            </ProtectedRoute>
          }
        />
      </Route>

      {/* 404 */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  </Suspense>
);

// ── 루트 앱 컴포넌트 ──────────────────────────────────────────────────────────

const App: React.FC = () => (
  <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
    <ThemeProvider>
      <AuthProvider>
        <NotificationProvider>
          <AppRouter />
        </NotificationProvider>
      </AuthProvider>
    </ThemeProvider>
  </BrowserRouter>
);

export default App;
