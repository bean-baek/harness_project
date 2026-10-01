// web_target/jest.config.ts

const config = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  // 주의: 올바른 키는 setupFilesAfterEnv. setupFilesAfterFramework 는 Jest 옵션이 아니어서
  // 조용히 무시되고(Validation Warning만 출력) jest-dom 매처가 로드되지 않았다 (TS-006).
  setupFilesAfterEnv: ['@testing-library/jest-dom'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.(css|less|scss|sass)$': '<rootDir>/__mocks__/styleMock.js',
  },
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/main.tsx',
  ],
  coverageThreshold: {
    global: {
      branches:  80,
      functions: 80,
      lines:     80,
      statements: 80,
    },
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      tsconfig: { jsx: 'react-jsx' },
    }],
  },
  testMatch: ['**/*.test.{ts,tsx}'],
  testPathIgnorePatterns: ['/node_modules/', '/dist/'],
};

export default config;
