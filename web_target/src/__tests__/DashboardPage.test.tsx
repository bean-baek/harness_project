import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '../pages/DashboardPage';

// recharts는 내부적으로 ResizeObserver를 사용하므로 mock 처리 필요
const mockResizeObserver = jest.fn(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}));
window.ResizeObserver = mockResizeObserver;

describe('DashboardPage', () => {
  it('renders the main dashboard heading', () => {
    render(<DashboardPage />);
    expect(screen.getByRole('heading', { name: /dashboard/i })).toBeInTheDocument();
  });

  it('renders the welcome message', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/welcome back/i)).toBeInTheDocument();
  });

  it('renders the weekly completion chart section', () => {
    render(<DashboardPage />);
    expect(screen.getByRole('heading', { name: /weekly task completions/i })).toBeInTheDocument();
  });

  it('renders the chart summary with the most productive day', () => {
    render(<DashboardPage />);
    // Chart 컴포넌트 내부의 텍스트가 렌더링 되는지 확인
    expect(screen.getByText(/your most productive day was/i)).toBeInTheDocument();
    expect(screen.getByText('Sun')).toBeInTheDocument(); // Mock 데이터에서 가장 생산적인 요일
    expect(screen.getByText('9')).toBeInTheDocument(); // Mock 데이터에서 가장 높은 완료 수
  });
});
