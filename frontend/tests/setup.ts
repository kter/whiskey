/**
 * Vitest global setup file
 * テスト環境のグローバルセットアップ
 */

// Global test utilities
import { beforeEach, vi } from 'vitest'

// Reset all mocks before each test
beforeEach(() => {
  vi.clearAllMocks()
})

// Mock global objects that might be undefined in test environment
Object.defineProperty(global, 'process', {
  value: {
    client: true,
    server: false,
    dev: false,
    env: {
      NODE_ENV: 'test'
    }
  },
  writable: true
})

// Mock window object for browser APIs
Object.defineProperty(global, 'window', {
  value: {
    innerWidth: 1024,
    innerHeight: 768,
    location: {
      href: 'http://localhost:3000',
      origin: 'http://localhost:3000'
    },
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  },
  writable: true
})

// Mock console methods to avoid noise in tests
global.console = {
  ...console,
  warn: vi.fn(),
  error: vi.fn(),
  log: vi.fn()
}

// Mock Nuxt composables globally
global.useRuntimeConfig = vi.fn(() => ({
  public: {
    apiBaseUrl: 'https://api.test.whiskeybar.site',
    userPoolId: 'ap-northeast-1_test',
    userPoolClientId: 'test-client-id',
    region: 'ap-northeast-1',
    environment: 'test'
  }
}))