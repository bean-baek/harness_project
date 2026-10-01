/**
 * src/components/LoginForm.tsx
 * ─────────────────────────────
 * 하네스 에이전트가 구현하는 첫 번째 기능: 로그인 폼 (F-001 ~ F-003)
 *
 * 구현 요구사항:
 *   - 이메일 / 비밀번호 입력 필드
 *   - 실시간 유효성 검사
 *   - 로그인 API 연동
 *   - 오류 메시지 표시
 *   - 접근성 (aria-label, 키보드 탐색)
 */

import React, { useState, useId } from 'react';

// ── 타입 정의 ─────────────────────────────────────────────────────────────────

interface LoginFormProps {
  onSuccess?: (token: string) => void;
  redirectTo?: string;
}

interface FormErrors {
  email?: string;
  password?: string;
  general?: string;
}

// ── 유효성 검사 함수 ──────────────────────────────────────────────────────────

const validateEmail = (email: string): string | undefined => {
  if (!email) return '이메일을 입력하세요.';
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) return '올바른 이메일 형식을 입력하세요.';
  return undefined;
};

const validatePassword = (password: string): string | undefined => {
  if (!password) return '비밀번호를 입력하세요.';
  if (password.length < 8) return '비밀번호는 8자 이상이어야 합니다.';
  return undefined;
};

// ── 메인 컴포넌트 ─────────────────────────────────────────────────────────────

/**
 * 오픈 리다이렉트 방어 — 내부 경로만 허용한다.
 *
 * `?redirect=` 값은 URL 쿼리에서 그대로 들어온다(F-005 의 ProtectedRoute 가 쓴다).
 * 검증 없이 `window.location.href` 에 넣으면 `?redirect=https://evil.com` 으로
 * 로그인 직후 외부 사이트로 끌고 갈 수 있다.
 * 프로토콜 상대 URL(`//host`)과 역슬래시 변형(`/\host`)도 외부로 나가므로 함께 막는다.
 */
export const safeRedirectTarget = (target: string | null | undefined): string => {
  if (!target || !target.startsWith('/')) return '/';
  if (target.startsWith('//') || target.startsWith('/\\')) return '/';
  return target;
};

export const LoginForm: React.FC<LoginFormProps> = ({
  onSuccess,
  redirectTo = '/',
}) => {
  const emailId   = useId();
  const passwordId = useId();

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [errors,   setErrors]   = useState<FormErrors>({});
  const [loading,  setLoading]  = useState(false);
  const [touched,  setTouched]  = useState({ email: false, password: false });

  // 실시간 유효성 검사
  const emailError    = touched.email    ? validateEmail(email)       : undefined;
  const passwordError = touched.password ? validatePassword(password) : undefined;
  const isValid       = !validateEmail(email) && !validatePassword(password);

  const handleBlur = (field: 'email' | 'password') => {
    setTouched(prev => ({ ...prev, [field]: true }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // 제출 시 모든 필드 검증
    setTouched({ email: true, password: true });
    const emailErr    = validateEmail(email);
    const passwordErr = validatePassword(password);
    if (emailErr || passwordErr) {
      setErrors({ email: emailErr, password: passwordErr });
      return;
    }

    setLoading(true);
    setErrors({});

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        if (response.status === 401) {
          setErrors({ general: '이메일 또는 비밀번호가 올바르지 않습니다.' });
        } else {
          setErrors({ general: data.message || '로그인에 실패했습니다. 다시 시도해주세요.' });
        }
        return;
      }

      const { token } = await response.json();
      localStorage.setItem('auth_token', token);
      onSuccess?.(token);

      // 리다이렉트
      window.location.href = safeRedirectTarget(redirectTo);

    } catch {
      setErrors({ general: '연결에 문제가 있습니다. 잠시 후 다시 시도해주세요.' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container" role="main">
      <div className="login-card">
        <h1 className="login-title">로그인</h1>

        {/* 전체 오류 메시지 */}
        {errors.general && (
          <div
            role="alert"
            aria-live="polite"
            className="error-banner"
          >
            {errors.general}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* 이메일 필드 */}
          <div className="field-group">
            <label htmlFor={emailId} className="field-label">
              이메일 <span aria-hidden="true">*</span>
            </label>
            <input
              id={emailId}
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onBlur={() => handleBlur('email')}
              aria-describedby={emailError ? `${emailId}-error` : undefined}
              aria-invalid={!!emailError}
              placeholder="example@email.com"
              autoComplete="email"
              className={`field-input ${emailError ? 'field-input--error' : ''}`}
              disabled={loading}
            />
            {emailError && (
              <p id={`${emailId}-error`} role="alert" className="field-error">
                {emailError}
              </p>
            )}
          </div>

          {/* 비밀번호 필드 */}
          <div className="field-group">
            <label htmlFor={passwordId} className="field-label">
              비밀번호 <span aria-hidden="true">*</span>
            </label>
            <input
              id={passwordId}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onBlur={() => handleBlur('password')}
              aria-describedby={passwordError ? `${passwordId}-error` : undefined}
              aria-invalid={!!passwordError}
              placeholder="8자 이상 입력"
              autoComplete="current-password"
              className={`field-input ${passwordError ? 'field-input--error' : ''}`}
              disabled={loading}
            />
            {passwordError && (
              <p id={`${passwordId}-error`} role="alert" className="field-error">
                {passwordError}
              </p>
            )}
          </div>

          {/* 제출 버튼 */}
          <button
            type="submit"
            disabled={!isValid || loading}
            aria-busy={loading}
            className="submit-button"
          >
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginForm;
