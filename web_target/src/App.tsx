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

// ── 지연 로딩 (번들 크기 최적화) ──────────────────────────────────────────────
const LoginPage     = lazy(() => import('./pages/LoginPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const UsersPage     = lazy(() => import('./pages/admin/UsersPage'));
const ProfilePage   = lazy(() => import('./pages/ProfilePage'));
const SettingsPage  = lazy(() => import('./pages/SettingsPage'));
const NotFoundPage  = lazy(() => import('./pages/NotFoundPage'));

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
        <Route index element={<DashboardPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="settings" element={<SettingsPage />} />

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
