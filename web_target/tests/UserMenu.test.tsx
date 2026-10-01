
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import UserMenu from '../src/components/UserMenu';
import { AuthContext, User } from '../src/contexts/AuthContext';

// useNavigate 훅 모킹
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: jest.fn(),
}));

describe('UserMenu', () => {
  const mockNavigate = jest.fn();
  const mockLogout = jest.fn();

  const user: User = {
    id: 'user-123',
    name: 'Test User',
    email: 'test@example.com',
    isAdmin: false,
    avatarUrl: 'https://i.pravatar.cc/40',
  };

  const authContextValue = {
    user,
    isAuthenticated: true,
    isLoading: false,
    login: jest.fn(),
    logout: mockLogout,
  };

  beforeEach(() => {
    // 각 테스트 전에 모킹 초기화
    (useNavigate as jest.Mock).mockReturnValue(mockNavigate);
    mockLogout.mockClear();
    mockNavigate.mockClear();
    localStorage.clear();
  });

  const renderComponent = () => {
    return render(
      <AuthContext.Provider value={authContextValue}>
        <MemoryRouter>
          <UserMenu />
        </MemoryRouter>
      </AuthContext.Provider>
    );
  };

  test('사용자 정보가 올바르게 표시된다', () => {
    renderComponent();
    expect(screen.getByText('Test User')).toBeInTheDocument();
    expect(screen.getByAltText('User Avatar')).toHaveAttribute('src', user.avatarUrl);
  });

  test('메뉴를 열고 닫을 수 있다', () => {
    renderComponent();
    const triggerButton = screen.getByRole('button', { name: /Test User/ });

    // 메뉴 열기
    fireEvent.click(triggerButton);
    expect(screen.getByRole('menuitem', { name: '로그아웃' })).toBeVisible();

    // 메뉴 닫기
    fireEvent.click(triggerButton);
    expect(screen.queryByRole('menuitem', { name: '로그아웃' })).not.toBeInTheDocument();
  });

  test('F-004.3 F-004.4: 로그아웃 버튼을 클릭하면 logout 함수가 호출되고 /login으로 이동한다', async () => {
    // Given: 사용자가 로그인되어 있고, UserMenu가 렌더링됨
    renderComponent();
    const triggerButton = screen.getByRole('button', { name: /Test User/ });
    fireEvent.click(triggerButton); // 메뉴 열기
    
    const logoutButton = screen.getByRole('menuitem', { name: '로그아웃' });
    
    // 로컬 스토리지에 토큰 설정
    localStorage.setItem('auth_token', 'dummy-token');

    // When: 로그아웃 버튼 클릭
    fireEvent.click(logoutButton);

    // Then: AuthContext의 logout 함수가 호출됨
    expect(mockLogout).toHaveBeenCalledTimes(1);
    
    // Then: useNavigate가 /login 경로로 호출됨
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  test('프로필 버튼을 클릭하면 /profile로 이동한다', () => {
    renderComponent();
    const triggerButton = screen.getByRole('button', { name: /Test User/ });
    fireEvent.click(triggerButton);

    const profileButton = screen.getByRole('menuitem', { name: '프로필' });
    fireEvent.click(profileButton);

    expect(mockNavigate).toHaveBeenCalledWith('/profile');
  });
});
