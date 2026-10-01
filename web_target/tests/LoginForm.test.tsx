/**
 * tests/LoginForm.test.tsx
 * ─────────────────────────
 * F-001 ~ F-003 기능 검증 테스트
 *
 * 논문 근거 (P-03 Coder):
 *   "단위 테스트(Jest)를 실행한다."
 *   "기존 통과하던 테스트가 모두 여전히 통과한다."
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { LoginForm } from '../src/components/LoginForm';

// ── fetch Mock ───────────────────────────────────────────────────────────────

global.fetch = jest.fn();

const mockFetch = (status: number, body: object) => {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
};

// ── 테스트 픽스처 ──────────────────────────────────────────────────────────────

const VALID_EMAIL    = 'test@example.com';
const VALID_PASSWORD = 'SecurePass123!';

// ── F-001: 로그인 성공 ────────────────────────────────────────────────────────

describe('F-001: 이메일/비밀번호 로그인', () => {
  test('유효한 자격증명으로 로그인 성공 시 onSuccess 콜백 호출', async () => {
    const onSuccess = jest.fn();
    mockFetch(200, { token: 'test-jwt-token' });

    render(<LoginForm onSuccess={onSuccess} />);

    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith('test-jwt-token');
    });
  });

  test('로그인 성공 시 localStorage에 토큰 저장', async () => {
    mockFetch(200, { token: 'jwt-abc-123' });
    const localStorageSpy = jest.spyOn(Storage.prototype, 'setItem');

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      expect(localStorageSpy).toHaveBeenCalledWith('auth_token', 'jwt-abc-123');
    });
  });

  test('로그인 요청 중 버튼이 "로그인 중..."으로 변경되고 비활성화', async () => {
    let resolveFetch!: (value: object) => void;
    (global.fetch as jest.Mock).mockReturnValueOnce(
      new Promise(resolve => { resolveFetch = resolve; })
    );

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /로그인/ }));
    });

    expect(screen.getByRole('button', { name: /로그인 중/ })).toBeDisabled();

    // fetch 완료
    act(() => {
      resolveFetch({ ok: true, status: 200, json: async () => ({ token: 'tok' }) });
    });
  });
});

// ── F-002: 잘못된 자격증명 ────────────────────────────────────────────────────

describe('F-002: 잘못된 자격증명 오류 처리', () => {
  test('401 응답 시 "이메일 또는 비밀번호" 오류 메시지 표시', async () => {
    mockFetch(401, { message: '인증 실패' });

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), 'WrongPassword1!');
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        '이메일 또는 비밀번호가 올바르지 않습니다.'
      );
    });
  });

  test('500 서버 오류 시 일반 오류 메시지 표시', async () => {
    mockFetch(500, { message: '서버 오류' });

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  test('네트워크 오류 시 연결 문제 메시지 표시', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('연결에 문제가 있습니다');
    });
  });
});

// ── F-003: 이메일 유효성 검사 ────────────────────────────────────────────────

describe('F-003: 이메일 형식 유효성 검사', () => {
  test('@가 없는 이메일 입력 후 포커스 이탈 시 오류 표시', async () => {
    render(<LoginForm />);
    const emailInput = screen.getByLabelText(/이메일/);

    await userEvent.type(emailInput, 'invalidemail');
    fireEvent.blur(emailInput);

    expect(screen.getByText('올바른 이메일 형식을 입력하세요.')).toBeInTheDocument();
  });

  test('유효하지 않은 이메일이면 로그인 버튼 비활성화', async () => {
    render(<LoginForm />);
    const emailInput = screen.getByLabelText(/이메일/);

    await userEvent.type(emailInput, 'notanemail');
    fireEvent.blur(emailInput);

    const submitBtn = screen.getByRole('button', { name: /로그인/ });
    expect(submitBtn).toBeDisabled();
  });

  test('유효한 이메일 + 유효한 비밀번호 입력 시 버튼 활성화', async () => {
    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    fireEvent.blur(screen.getByLabelText(/이메일/));

    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    fireEvent.blur(screen.getByLabelText(/비밀번호/));

    expect(screen.getByRole('button', { name: /로그인/ })).toBeEnabled();
  });

  test('빈 이메일 제출 시 오류 메시지 표시', async () => {
    render(<LoginForm />);
    const emailInput = screen.getByLabelText(/이메일/);
    
    // 포커스 후 이탈하여 유효성 검사 트리거
    fireEvent.blur(emailInput);

    await waitFor(() => {
      expect(screen.getByText('이메일을 입력하세요.')).toBeInTheDocument();
    });
  });

  test('8자 미만 비밀번호 오류 메시지 표시', async () => {
    render(<LoginForm />);
    const pwInput = screen.getByLabelText(/비밀번호/);

    await userEvent.type(pwInput, 'short');
    fireEvent.blur(pwInput);

    expect(screen.getByText('비밀번호는 8자 이상이어야 합니다.')).toBeInTheDocument();
  });
});

// ── 접근성 테스트 ─────────────────────────────────────────────────────────────

describe('접근성 (Accessibility)', () => {
  test('오류 메시지에 role="alert" 속성이 설정됨', async () => {
    mockFetch(401, {});

    render(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/이메일/), VALID_EMAIL);
    await userEvent.type(screen.getByLabelText(/비밀번호/), VALID_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: /로그인/ }));

    await waitFor(() => {
      const alerts = screen.getAllByRole('alert');
      expect(alerts.length).toBeGreaterThan(0);
    });
  });

  test('입력 필드에 aria-invalid 속성이 오류 시 true로 설정됨', async () => {
    render(<LoginForm />);
    const emailInput = screen.getByLabelText(/이메일/);

    await userEvent.type(emailInput, 'invalid');
    fireEvent.blur(emailInput);

    expect(emailInput).toHaveAttribute('aria-invalid', 'true');
  });
});
