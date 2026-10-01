
import React from 'react';
import { render, act } from '@testing-library/react';
import { AuthProvider, useAuth, User } from '../src/contexts/AuthContext';

// localStorage 모킹
const localStorageMock = (() => {
  let store: { [key: string]: string } = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString();
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

const TestConsumer: React.FC<{ onLogout?: () => void }> = ({ onLogout }) => {
  const { logout, user } = useAuth();

  const handleLogout = () => {
    logout();
    if (onLogout) {
      onLogout();
    }
  };

  return (
    <div>
      {user && <span data-testid="user-name">{user.name}</span>}
      <button onClick={handleLogout}>Logout</button>
    </div>
  );
};

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear();
    // 로그인 상태 시뮬레이션을 위해 토큰을 미리 설정
    const dummyUser: User = {
        id: 'user-123',
        email: 'test@example.com',
        name: 'Test User',
        isAdmin: false,
      };
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
    const payload = btoa(JSON.stringify({ 
      id: dummyUser.id, 
      email: dummyUser.email, 
      name: dummyUser.name,
      isAdmin: dummyUser.isAdmin,
      exp: Math.floor(Date.now() / 1000) + 3600
    }));
    const token = `${header}.${payload}.signature`;
    localStorage.setItem('auth_token', token);
  });

  test('logout 함수는 localStorage에서 auth_token을 제거해야 한다', () => {
    const removeItemSpy = jest.spyOn(localStorage, 'removeItem');

    const { getByText } = render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );
    
    // AuthProvider의 useEffect가 실행되어 사용자가 설정될 때까지 기다립니다.
    act(() => {
        jest.runAllTimers(); // 가정: useEffect 내 비동기 작업이 타이머를 사용할 경우
    });

    const logoutButton = getByText('Logout');
    
    act(() => {
      logoutButton.click();
    });

    expect(removeItemSpy).toHaveBeenCalledWith('auth_token');
    
    removeItemSpy.mockRestore();
  });
});
