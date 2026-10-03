import { describe, test, expect } from 'vitest';
import { resolve } from './app.js';
import { PAGES } from './routes.js';

describe('APP-01: 선언된 경로가 모두 라우터에 등록된다', () => {
  test('APP-01.1: PAGES 의 각 경로가 그대로 해석된다', () => {
    PAGES.forEach((p) => expect(resolve(p)).toBe(p));
  });
});

describe('APP-02: 알 수 없는 경로는 홈으로 떨어진다', () => {
  test('APP-02.1: 없는 경로로 가면 / 가 된다', () => {
    expect(resolve('/nope')).toBe('/');
  });
});
