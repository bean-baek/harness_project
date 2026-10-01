/**
 * web_target/src/components/ProtectedRoute.tsx
 * ─────────────────────────────────────────────
 * F-005 — 인증되지 않은 사용자가 보호된 페이지에 접근하면 로그인으로 리다이렉트한다.
 *         원래 URL 은 `?redirect=` 로 보존되어 로그인 후 복귀에 쓰인다 (LoginPage 가 읽는다).
 *
 * App.tsx 안에 인라인으로 있던 구현을 분리했다. 분리 이유는 두 가지다.
 *   1. App.tsx 는 페이지를 lazy() 로 불러오므로 통째로 렌더링해야 테스트할 수 있었다.
 *      이 컴포넌트만 떼어내면 라우터와 인증 상태만 주입해 직접 검증할 수 있다.
 *   2. 같은 가드가 중첩 라우트에서 재사용된다 (`requireAdmin`).
 */

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from './ui/LoadingSpinner';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** 관리자 전용 라우트 여부. 비관리자는 홈으로 되돌린다. */
  requireAdmin?: boolean;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requireAdmin = false,
}) => {
  const { isAuthenticated, isLoading, user } = useAuth();
  const location = useLocation();

  // 토큰 검증이 끝나기 전에 판단하면 로그인한 사용자까지 내쫓는다.
  // AuthContext 는 isLoading=true 로 시작해 useEffect 에서 저장된 토큰을 확인하므로,
  // 첫 렌더에서 isAuthenticated 는 아직 false 다. 이 분기가 없으면
  // **새로고침마다 로그아웃되는** 버그가 된다.
  if (isLoading) {
    return <LoadingSpinner fullPage />;
  }

  if (!isAuthenticated) {
    // window.location 이 아니라 라우터의 location 을 쓴다 —
    // 쿼리스트링이 보존되고, MemoryRouter 환경에서도 올바르게 동작한다.
    const from = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?redirect=${encodeURIComponent(from)}`} replace />;
  }

  if (requireAdmin && !user?.isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export default ProtectedRoute;
