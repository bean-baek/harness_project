import { PAGES } from './routes.js';

export function resolve(path) {
  if (PAGES.includes(path)) return path;
  return '/';
}

// 아래 함수는 테스트가 호출하지 않는다. 변이를 넣으면 **생존이 보장된다** —
// 커버리지 필터가 없으면 그 생존이 '증거의 구멍'으로 오계수된다 (TS-025).
export function neverCalled(flag) {
  if (flag === true) return 'yes';
  return 'no';
}
