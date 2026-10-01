// src/mocks/handlers.ts
import { rest } from 'msw';

export const handlers = [
  // 다른 핸들러들...
  rest.post('/api/auth/logout', (req, res, ctx) => {
    // 실제 서버에서는 여기서 세션을 무효화합니다.
    // 클라이언트에서는 이 응답을 받으면 로컬 토큰을 삭제합니다.
    return res(
      ctx.status(200),
      ctx.json({ message: 'Logged out successfully' })
    );
  }),
];
