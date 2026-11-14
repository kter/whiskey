import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // Nuxt and Vitest currently resolve separate compatible Vite type copies.
  plugins: [vue() as never],
  define: {
    'import.meta.dev': 'true',
    'import.meta.client': 'true'
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    // Playwright specs live in e2e/ and run via `make e2e`, not Vitest.
    exclude: ['**/node_modules/**', 'e2e/**']
  },
  resolve: {
    alias: {
      '~': fileURLToPath(new URL('./', import.meta.url)),
      '@': fileURLToPath(new URL('./', import.meta.url)),
      'exifr': fileURLToPath(new URL('./tests/mocks/exifr.ts', import.meta.url)),
      'heic-to': fileURLToPath(new URL('./tests/mocks/heic-to.ts', import.meta.url)),
      '#app': fileURLToPath(new URL('./tests/mocks/nuxt.ts', import.meta.url))
    }
  }
})
