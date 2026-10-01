import React from 'react';

/**
 * 로딩 표시.
 *
 * `fullPage` 는 받기만 하고 본문에서 쓰이지 않아 `<LoadingSpinner fullPage />` 가
 * 일반 호출과 완전히 동일하게 동작했다 (lint 가 미사용 인자로 적발).
 * 호출자(App.tsx 의 Suspense fallback, ProtectedRoute 의 인증 확인 중)는 전체 화면
 * 로딩을 의도하므로, 선언을 지우는 대신 의도대로 동작하게 만든다.
 */
export const LoadingSpinner: React.FC<{ fullPage?: boolean }> = ({ fullPage }) => (
  <div
    role="status"
    aria-live="polite"
    style={
      fullPage
        ? {
            minHeight: '60vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }
        : { padding: '20px', textAlign: 'center' }
    }
  >
    Loading...
  </div>
);
