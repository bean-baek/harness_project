import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import UserMenu from './UserMenu';
import { useAuth } from '../contexts/AuthContext';

// --- Mocks ---

// 1. react-router-dom의 useNavigate mock
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'), // 다른 기능들은 그대로 사용
  useNavigate: () => mockNavigate,
}));

// 2. AuthContext의 useAuth hook mock
jest.mock('../contexts/AuthContext');
const mockUseAuth = useAuth as jest.Mock;

const mockUser = {
  id: 'user-123',
  email: 'test@example.com',
  name: 'Test User',
  isAdmin: false,
  avatarUrl: 'https://i.pravatar.cc/40',
};

// --- Helper Function ---

const renderComponent = () => {
  return render(
    <BrowserRouter>
      <UserMenu />
    </BrowserRouter>
  );
};


// --- Tests ---

describe('UserMenu', () => {
  // 각 테스트 실행 전 mock 함수들 초기화
  beforeEach(() => {
    mockNavigate.mockClear();
    // useAuth의 logout mock은 useAuth가 리턴하는 객체 안에 있으므로 여기서 초기화
  });

  it('로그인하지 않은 상태(user가 null)에서는 아무것도 렌더링되지 않아야 합니다', () => {
    // Arrange: useAuth가 user: null을 반환하도록 설정
    mockUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      logout: jest.fn(),
    });
    
    const { container } = renderComponent();
    
    // Assert: 컴포넌트가 빈 DOM을 반환하는지 확인
    expect(container.firstChild).toBeNull();
  });

  it('로그인한 사용자 정보(아바타, 이름)가 올바르게 표시되어야 합니다', () => {
    // Arrange: useAuth가 mockUser를 반환하도록 설정
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      logout: jest.fn(),
    });

    renderComponent();
    
    // Assert
    expect(screen.getByText('Test User')).toBeInTheDocument();
    const avatar = screen.getByAltText('User Avatar') as HTMLImageElement;
    expect(avatar.src).toBe(mockUser.avatarUrl);
  });

  it('F-004.2: 메뉴 버튼 클릭 시 드롭다운 메뉴가 열리고 닫혀야 합니다', () => {
    // Arrange
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      logout: jest.fn(),
    });
    renderComponent();

    const triggerButton = screen.getByRole('button', { name: /Test User/i });
    
    // Act & Assert: 첫 번째 클릭 (메뉴 열기)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    fireEvent.click(triggerButton);
    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /프로필/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /로그아웃/ })).toBeInTheDocument();
    
    // Act & Assert: 두 번째 클릭 (메뉴 닫기)
    fireEvent.click(triggerButton);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('F-004.3 F-004.4: Logout 버튼 클릭 시 useAuth의 logout 함수가 호출되고 /login 페이지로 이동해야 합니다', async () => {
    // Arrange
    const mockLogout = jest.fn();
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      logout: mockLogout, // 테스트할 mock 함수 주입
    });
    renderComponent();

    // Act: 메뉴 열고 로그아웃 버튼 클릭
    fireEvent.click(screen.getByRole('button', { name: /Test User/i }));
    const logoutButton = screen.getByRole('menuitem', { name: /로그아웃/ });
    fireEvent.click(logoutButton);

    // Assert
    await waitFor(() => {
        expect(mockLogout).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('메뉴가 열린 상태에서 컴포넌트 외부를 클릭하면 메뉴가 닫혀야 합니다', () => {
    // Arrange
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      logout: jest.fn(),
    });
    render(
      <BrowserRouter>
        <div data-testid="outside">Outside Area</div>
        <UserMenu />
      </BrowserRouter>
    );

    // Act: 메뉴 열기
    const triggerButton = screen.getByRole('button', { name: /Test User/i });
    fireEvent.click(triggerButton);
    expect(screen.getByRole('menu')).toBeInTheDocument();

    // Act: 외부 클릭
    fireEvent.mouseDown(screen.getByTestId('outside'));

    // Assert
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
