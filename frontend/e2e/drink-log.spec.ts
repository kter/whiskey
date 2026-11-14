import { fileURLToPath } from 'node:url'
import { test, expect } from './fixtures'

const photo = fileURLToPath(new URL('./fixtures/bottle.jpg', import.meta.url))

// The local API runs with MOCK_AI=1 / MOCK_PLACES=1, which return a single
// whiskey (モックウイスキー) and a single place (モックバー). A unique store name
// lets the history scenario find this run's record even on a reused stack.
const storeName = `E2Eバー ${Date.now()}`

test.describe.configure({ mode: 'serial' })

test.describe('テイスティング記録', () => {
  test.use({
    geolocation: { latitude: 35.6812, longitude: 139.7671 },
    permissions: ['geolocation'],
  })

  test('記録: 写真を選び、解析・店候補の選択を経て保存できる', async ({ page }) => {
    await page.goto('/logs/new')
    await expect(page.getByRole('heading', { name: '今日の一杯を記録' })).toBeVisible()

    await page.getByLabel('ボトルやグラスの写真 *').setInputFiles(photo)

    // Upload to moto + mock analysis.
    await expect(page.getByText('解析完了')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('heading', { name: '1杯目の確認' })).toBeVisible()
    // The mock returns one candidate, which is applied to the brand field.
    const brand = page.getByLabel('銘柄名 *')
    await expect(brand).toHaveValue(/\S/)
    await expect(page.getByText(/AIの読み取り:/)).toBeVisible()

    // Emulated geolocation -> mock Places -> choose the place candidate.
    await page.getByRole('button', { name: '近くの店を探す' }).click()
    const place = page.getByRole('group', { name: '近くの店候補' }).getByRole('button', { name: /モックバー/ })
    await expect(place).toBeVisible()
    await place.click()
    await expect(place).toHaveAttribute('aria-pressed', 'true')

    await page.getByLabel('記録に残す店名（任意）').fill(storeName)
    await page.getByRole('button', { name: '評価 4' }).click()

    await page.getByRole('button', { name: 'この一杯を記録' }).click()
    await expect(page).toHaveURL(/\/logs$/, { timeout: 30_000 })
  })

  test('履歴: 保存した記録が一覧に表示され、詳細が開ける', async ({ page }) => {
    await page.goto('/logs')
    await expect(page.getByRole('heading', { name: 'テイスティング履歴' })).toBeVisible()

    const record = page.getByRole('article').filter({ hasText: storeName })
    await expect(record).toBeVisible()
    const brandText = (await record.getByRole('heading', { level: 3 }).innerText()).trim()
    expect(brandText).not.toBe('')

    await record.getByRole('heading', { level: 3 }).getByRole('link').click()
    await expect(page).toHaveURL(/\/logs\/[^/]+$/)
    await expect(page.getByRole('heading', { level: 1, name: brandText })).toBeVisible()
    await expect(page.getByText(storeName).first()).toBeVisible()
  })
})
