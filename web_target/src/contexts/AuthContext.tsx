/**
 * web_target/src/contexts/AuthContext.tsx
 * ────────────────────────────────────────
 * 인증 컨텍스트 — F-001, F-004, F-005 기반
 */

import React, {
  createContext, useContext, useState,
  useCallback, useEffect, type ReactNode,
} from 'react';

// ── 타입 ─────────────────────────────────────────────────────────────────────

export interface User {
  id:        string;
  email:     string;
  name:      string;
  isAdmin:   boolean;
  avatarUrl?: string;
}

interface AuthContextValue {
  user:            User | null;
  isAuthenticated: boolean;
  isLoading:       boolean;
  login:  (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

// ── 컨텍스트 생성 ─────────────────────────────────────────────────────────────

// export: 테스트가 Provider 를 직접 주입할 수 있어야 한다 (tests/UserMenu.test.tsx).
export const AuthContext = createContext<AuthContextValue | null>(null);

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth는 AuthProvider 내부에서 사용해야 합니다.');
  return ctx;
};

// ── Provider ─────────────────────────────────────────────────────────────────

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user,      setUser]      = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // 앱 초기 로드 시 토큰 검증
  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    if (!token) {
      setIsLoading(false);
      return;
    }

    // 실제 API 호출 대신, 토큰 존재 시 임시 사용자 정보를 설정합니다.
    // 이는 백엔드 구현 없이 프론트엔드 로직을 테스트하기 위함입니다.
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp * 1000 > Date.now()) {
        setUser({
          id: payload.id,
          email: payload.email,
          name: payload.name || 'Test User',
          isAdmin: payload.isAdmin || false,
          avatarUrl: 'https://i.pravatar.cc/48',
        });
      } else {
        localStorage.removeItem('auth_token');
      }
    } catch (error) {
      console.error("Invalid token:", error);
      localStorage.removeItem('auth_token');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    // 실제 API 호출 대신, 로그인 성공을 시뮬레이션하고 JWT 형식의 토큰을 생성합니다.
    if (email === 'test@example.com' && password === 'password') {
      const dummyUser: User = {
        id: 'user-123',
        email: 'test@example.com',
        name: 'Test User',
        isAdmin: false,
        avatarUrl: 'https://i.pravatar.cc/48',
      };
      
      const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
      const payload = btoa(JSON.stringify({ 
        id: dummyUser.id, 
        email: dummyUser.email, 
        name: dummyUser.name,
        isAdmin: dummyUser.isAdmin,
        exp: Math.floor(Date.now() / 1000) + (60 * 60) // 1시간 만료
      }));
      const signature = 'dummy-signature';
      const token = `${header}.${payload}.${signature}`;

      localStorage.setItem('auth_token', token);
      setUser(dummyUser);
    } else {
      throw new Error('이메일 또는 비밀번호가 올바르지 않습니다.');
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      // 서버에 로그아웃 요청을 보냅니다.
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (error) {
      // 네트워크 오류 등이 발생해도 클라이언트 측에서는 로그아웃 처리를 계속 진행합니다.
      console.error('Logout API call failed:', error);
    } finally {
      // API 호출 성공 여부와 관계없이 로컬 상태 및 저장소를 정리합니다.
      localStorage.removeItem('auth_token');
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated: !!user,
      isLoading,
      login,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
};
