/**
 * Mock implementations for Nuxt composables and utilities
 * Nuxtコンポーザブルとユーティリティのモック実装
 */
import { vi } from 'vitest'

export const useRuntimeConfig = () => ({
  public: {
    apiBaseUrl: 'https://api.test.whiskeybar.site',
    userPoolId: 'ap-northeast-1_test',
    userPoolClientId: 'test-client-id',
    region: 'ap-northeast-1',
    environment: 'test'
  }
})

export const useRouter = () => ({
  push: vi.fn(),
  replace: vi.fn(),
  go: vi.fn(),
  back: vi.fn(),
  forward: vi.fn()
})

export const useRoute = () => ({
  params: {},
  query: {},
  path: '/',
  fullPath: '/',
  name: 'index'
})

export const navigateTo = vi.fn()

// Mock Nuxt's auto-imports
global.useRuntimeConfig = useRuntimeConfig
global.useRouter = useRouter  
global.useRoute = useRoute
global.navigateTo = navigateTo