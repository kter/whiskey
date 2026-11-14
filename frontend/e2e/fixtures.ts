import { test as base, expect } from '@playwright/test'

/**
 * Shared fixture: any browser console error or uncaught page error fails the test.
 * Messages are collected while the test runs and asserted after it finishes, so
 * the failure screenshot still shows the page in the state the error occurred.
 */
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('console', message => {
        if (message.type() === 'error') errors.push(`console: ${message.text()}`)
      })
      page.on('pageerror', error => errors.push(`pageerror: ${error.message}`))
      await use(errors)
      expect(errors, 'browser console errors').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }
