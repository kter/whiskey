import { chromium, type FullConfig } from '@playwright/test'

// On the first visit to a route, Vite's dev server may discover new dependencies
// (e.g. exifr / heic-to on /logs/new), re-optimise them and force a full page
// reload. That reload would wipe a test mid-flow, so every route is visited once
// before the tests run.
const ROUTES = ['/', '/search', '/logs', '/logs/new']

export default async function globalSetup(config: FullConfig) {
  const { baseURL, launchOptions } = config.projects[0]!.use
  const browser = await chromium.launch(launchOptions)
  try {
    const page = await browser.newPage({ baseURL })
    for (let pass = 0; pass < 2; pass++) {
      for (const route of ROUTES) {
        await page.goto(route, { waitUntil: 'networkidle', timeout: 120_000 })
        // Give a dependency re-optimisation time to trigger its reload.
        await page.waitForTimeout(1_500)
        await page.waitForLoadState('networkidle', { timeout: 120_000 })
      }
    }
  } finally {
    await browser.close()
  }
}
