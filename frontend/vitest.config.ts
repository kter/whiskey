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
    setupFiles: ['./tests/setup.ts']
  },
  resolve: {
    alias: {
      '~': fileURLToPath(new URL('./', import.meta.url)),
      '@': fileURLToPath(new URL('./', import.meta.url)),
      'heic2any': fileURLToPath(new URL('./tests/mocks/heic2any.ts', import.meta.url)),
      '#app': fileURLToPath(new URL('./tests/mocks/nuxt.ts', import.meta.url))
    }
  }
})
