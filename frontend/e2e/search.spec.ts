import { test, expect } from './fixtures'

// Names come from scripts/local/seed_data (seeded by `make local-init`).
const cases = [
  { query: 'bowmore', expected: /Bowmore|ボウモア/ },
  { query: '山崎', expected: /山崎/ },
]

for (const { query, expected } of cases) {
  test(`検索: ${query} で結果が表示される`, async ({ page }) => {
    await page.goto('/search')
    await expect(page.getByRole('heading', { name: 'ウイスキー検索' })).toBeVisible()

    await page.getByRole('searchbox').fill(query)
    await page.getByRole('button', { name: '検索', exact: true }).click()

    const results = page.getByRole('article')
    await expect(results.first()).toBeVisible()
    await expect(results.filter({ hasText: expected }).first()).toBeVisible()
    await expect(page.getByText('該当するウイスキーが見つかりませんでした。')).toHaveCount(0)
  })
}
