/**
 * web_target/src/routes.ts
 * ─────────────────────────
 * 보호 경로 목록의 **단일 출처**.
 *
 * App.tsx 가 라우트를 선언하고 테스트가 별도로 경로를 발명하면, "앱에 그 라우트가
 * 존재하는가"는 아무도 검증하지 않는다. 실제로 F-005 가 그렇게 통과했다 —
 * jest 는 테스트가 만든 /dashboard 를 검증했고, 앱에는 그 라우트가 없었다 (TS-013).
 *
 * 그래서 목록을 여기 한 곳에 두고 App.tsx 와 테스트가 함께 읽는다.
 * 보호 라우트를 추가할 때는 이 배열에 넣어야 하며, 그러면 테스트가 자동으로
 * "미인증 시 리다이렉트 + 원래 경로 보존"을 검증한다.
 */

/** 인증이 필요한 경로. 관리자 전용 경로는 requireAdmin 으로 따로 감싼다. */
export const PROTECTED_PATHS = [
  '/',
  '/dashboard',
  '/profile',
  '/settings',
] as const;

export type ProtectedPath = (typeof PROTECTED_PATHS)[number];
