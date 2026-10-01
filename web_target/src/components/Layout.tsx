/**
 * web_target/src/components/Layout.tsx
 * ────────────────────────────────────
 * 앱 공통 레이아웃 — 네비게이션 + 사이드바 + 컨텐츠 영역
 * 하네스 에이전트가 각 섹션을 기능별로 구현한다.
 */
import React from 'react';
import { Outlet, NavLink }   from 'react-router-dom';
import { useAuth }           from '../contexts/AuthContext';
// useNotifications는 아직 구현되지 않았습니다.
// import { useNotifications }  from '../contexts/NotificationContext'; 
import { useTheme }          from '../contexts/ThemeContext';
import UserMenu from './UserMenu';
import './Layout.css';

export const Layout: React.FC = () => {
  const { user }           = useAuth();
  // @ts-ignore — NotificationContext는 별도 파일에 있음
  const { unreadCount }            = { unreadCount: 0 };
  const { resolved, setTheme, theme } = useTheme();

  return (
    <div className="app-layout" data-theme={resolved}>
      {/* 상단 네비게이션 — F-016: 모바일에서 햄버거 메뉴로 변경 */}
      <header className="app-header">
        <nav className="nav-container">
          <div className="nav-brand">
            <NavLink to="/">Harness App</NavLink>
          </div>

          {/* 데스크톱 메뉴 */}
          <ul className="nav-links">
            <li><NavLink to="/dashboard">대시보드</NavLink></li>
            {user?.isAdmin && <li><NavLink to="/admin">관리자</NavLink></li>}
          </ul>

          {/* 우측 도구 모음 */}
          <div className="nav-actions">
            {/* 알림 벨 (F-020) */}
            <button
              aria-label={`알림 ${unreadCount}개`}
              className="notification-btn icon-button"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
              {unreadCount > 0 && (
                <span className="badge" aria-hidden="true">{unreadCount}</span>
              )}
            </button>

            {/* 테마 토글 (F-019) */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label="테마 전환"
              className="theme-toggle-btn icon-button"
            >
              {resolved === 'dark' ? 
                (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>) : 
                (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>)
              }
            </button>

            {/* 사용자 메뉴 (F-004) */}
            {user ? (
              <UserMenu />
            ) : (
              <NavLink to="/login" className="login-button">로그인</NavLink>
            )}
          </div>
        </nav>
      </header>

      {/* 메인 컨텐츠 */}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────

/**
 * web_target/src/components/ui/LoadingSpinner.tsx
 */
export const LoadingSpinner: React.FC<{
  fullPage?: boolean;
  size?: 'sm' | 'md' | 'lg';
}> = ({ fullPage = false, size = 'md' }) => {
  const sizeMap = { sm: 16, md: 32, lg: 48 };
  const px = sizeMap[size];

  const spinner = (
    <div
      role="status"
      aria-label="로딩 중"
      style={{
        width: px, height: px,
        border: `${px / 8}px solid #e5e7eb`,
        borderTopColor: '#3b82f6',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }}
    />
  );

  if (fullPage) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center',
        justifyContent: 'center', minHeight: '100vh',
      }}>
        {spinner}
      </div>
    );
  }
  return spinner;
};
