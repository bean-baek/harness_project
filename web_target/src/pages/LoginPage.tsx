/**
 * web_target/src/pages/LoginPage.tsx
 * ────────────────────────────────────
 * 로그인 페이지 — LoginForm 컴포넌트 래퍼
 */
import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { LoginForm } from '../components/LoginForm';

const LoginPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const redirectTo = searchParams.get('redirect') ?? '/';

  return (
    <div className="page-login">
      <LoginForm redirectTo={redirectTo} />
    </div>
  );
};
export default LoginPage;

// ─────────────────────────────────────────────────────────────────────────────

/**
 * web_target/src/pages/DashboardPage.tsx  — F-006, F-007
 * 하네스 에이전트가 구현 예정
 */
// @ts-nocheck
export {};
