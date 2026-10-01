/**
 * web_target/src/contexts/ThemeContext.tsx  — F-015
 */
import React, {
  createContext, useContext, useState,
  useEffect, useCallback, type ReactNode,
} from 'react';

type Theme = 'light' | 'dark' | 'system';

interface ThemeContextValue {
  theme:     Theme;
  resolved:  'light' | 'dark';
  setTheme:  (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme은 ThemeProvider 안에서만 사용하세요.');
  return ctx;
};

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem('theme') as Theme) ?? 'system'
  );

  const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const resolved: 'light' | 'dark' =
    theme === 'system' ? (systemDark ? 'dark' : 'light') : theme;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolved);
  }, [resolved]);

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem('theme', t);
    setThemeState(t);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

// ─────────────────────────────────────────────────────────────────────────────

/**
 * web_target/src/contexts/NotificationContext.tsx  — F-013, F-014
 */

interface Notification {
  id:        string;
  title:     string;
  message:   string;
  read:      boolean;
  createdAt: string;
}

interface NotificationContextValue {
  notifications: Notification[];
  unreadCount:   number;
  markAsRead:    (id: string) => void;
  markAllRead:   () => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

export const useNotifications = () => {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error('useNotifications는 NotificationProvider 안에서 사용하세요.');
  return ctx;
};

export const NotificationProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  // 실시간 알림 폴링 (SSE 또는 WebSocket으로 교체 가능)
  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    if (!token) return;

    const poll = async () => {
      try {
        const res = await fetch('/api/notifications', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) setNotifications(await res.json());
      } catch { /* 무시 */ }
    };

    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  const unreadCount = notifications.filter(n => !n.read).length;

  const markAsRead = useCallback((id: string) => {
    setNotifications(prev =>
      prev.map(n => n.id === id ? { ...n, read: true } : n)
    );
    fetch(`/api/notifications/${id}/read`, { method: 'PATCH' }).catch(() => {});
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    fetch('/api/notifications/read-all', { method: 'PATCH' }).catch(() => {});
  }, []);

  return (
    <NotificationContext.Provider value={{
      notifications, unreadCount, markAsRead, markAllRead,
    }}>
      {children}
    </NotificationContext.Provider>
  );
};
