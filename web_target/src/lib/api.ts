/**
 * web_target/src/lib/api.ts
 * ─────────────────────────
 * Axios 기반 API 클라이언트
 *
 * 기능:
 *   - JWT 토큰 자동 주입
 *   - 401 자동 로그아웃
 *   - F-020: 네트워크 오류 처리
 *   - 요청/응답 타임아웃 (10초)
 */

import axios, {
  type AxiosError,
  type InternalAxiosRequestConfig,
} from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';
const TIMEOUT  = 10_000; // 10초

// ── Axios 인스턴스 ────────────────────────────────────────────────────────────

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: TIMEOUT,
  headers: { 'Content-Type': 'application/json' },
});

// ── 요청 인터셉터: JWT 주입 ──────────────────────────────────────────────────

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('auth_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// ── 응답 인터셉터: 오류 처리 ─────────────────────────────────────────────────

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // 401: 토큰 만료 → 로그아웃
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
    }

    // 네트워크 오류 (F-020)
    if (!error.response) {
      return Promise.reject(
        new Error('연결에 문제가 있습니다. 잠시 후 다시 시도해주세요.')
      );
    }

    // 서버 오류 메시지 추출
    const serverMsg = (error.response.data as { message?: string })?.message;
    return Promise.reject(new Error(serverMsg ?? '요청을 처리할 수 없습니다.'));
  },
);

// ── API 함수 모음 ─────────────────────────────────────────────────────────────

/** 인증 */
export const authApi = {
  login:  (email: string, password: string) =>
    api.post<{ token: string; user: object }>('/auth/login', { email, password }),
  logout: () => api.post('/auth/logout'),
  me:     () => api.get('/auth/me'),
  changePassword: (current: string, next: string) =>
    api.patch('/auth/password', { currentPassword: current, newPassword: next }),
};

/** 사용자 관리 (F-008, F-009, F-010) */
export const usersApi = {
  list:   (page = 1, search = '') =>
    api.get('/admin/users', { params: { page, limit: 20, search } }),
  toggle: (userId: string, active: boolean) =>
    api.patch(`/admin/users/${userId}/status`, { active }),
};

/** 대시보드 (F-006, F-007) */
export const dashboardApi = {
  metrics: () => api.get('/dashboard/metrics'),
  visits:  (days = 7) => api.get('/dashboard/visits', { params: { days } }),
};

/** 프로필 (F-011, F-012) */
export const profileApi = {
  get:    () => api.get('/profile'),
  update: (data: { name?: string; phone?: string }) => api.patch('/profile', data),
};

/** 알림 (F-013, F-014) */
export const notificationsApi = {
  list:     () => api.get('/notifications'),
  markRead: (id: string) => api.patch(`/notifications/${id}/read`),
  markAll:  () => api.patch('/notifications/read-all'),
};
