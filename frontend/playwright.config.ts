import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

// Browser smoke tests for the local stack (moto + `make api` + `nuxt dev`).
// `make e2e` (scripts/local/e2e.sh) starts and stops the stack; this config
// only drives the browser against it.

// Failure artefacts (screenshots, traces) live under the repo's git-ignored .cache/.
const outputDir = fileURLToPath(new URL('../.cache/e2e/test-results', import.meta.url))

// Cloud agents cannot reach cdn.playwright.dev, so a preinstalled Chromium can be
// supplied explicitly. Without it, `npx playwright install chromium` provides one.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  outputDir,
  // The history scenario reads the record the recording scenario saves.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    // The API and the moto bucket only allow this origin in CORS.
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    browserName: 'chromium',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 1,
    locale: 'ja-JP',
    timezoneId: 'Asia/Tokyo',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: { executablePath },
  },
})
