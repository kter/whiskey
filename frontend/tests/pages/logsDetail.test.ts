import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { describe, expect, it } from 'vitest'
import { buildUpdateDrinkLogPayload } from '~/composables/useDrinkLogs'

const source = readFileSync(resolve(process.cwd(), 'pages/logs/[id].vue'), 'utf8')

describe('log detail editing and deletion', () => {
  it('builds a PUT body containing mutable fields only', () => {
    const payload = buildUpdateDrinkLogPayload({
      brandText: ' 山崎 12年 ',
      storeName: ' Bar ',
      placeId: 'place-1',
      servingStyle: 'NEAT',
      rating: 5,
      notes: ' note ',
    })
    expect(payload).toEqual({
      brand_text: '山崎 12年',
      store: { name: 'Bar', place_id: 'place-1' },
      serving_style: 'NEAT',
      rating: 5,
      notes: 'note',
    })
    for (const immutable of ['id', 'user_id', 's3_image_key', 'created_at', 'datetime']) {
      expect(payload).not.toHaveProperty(immutable)
    }
  })

  it('uses an inline confirmation and removes the deleted record from shared state', () => {
    expect(source).toContain('role="dialog"')
    expect(source).toContain('removeLog(log.value.id)')
    expect(source).toContain("router.push('/logs')")
    expect(source).not.toMatch(/\b(?:confirm|alert)\s*\(/)
  })

  it('maps an owned-detail 404 to a not-found or unauthorized message', () => {
    expect(source).toContain('cause instanceof ApiError && cause.status === 404')
    expect(source).toContain('削除されたか、表示する権限がありません。')
  })

  it('opens the refreshed detail image in the shared lightbox', () => {
    expect(source).toContain('class="block w-full cursor-zoom-in disabled:cursor-default"')
    expect(source).toContain(':disabled="!log.image_url"')
    expect(source).toContain('lightbox.src = log.value.image_url')
    expect(source).toContain('<ImageLightbox v-model:open="lightbox.open"')
  })

  it('omits the record-information toggle and status field', () => {
    expect(source).not.toContain('<summary class="cursor-pointer text-stone-300">記録情報</summary>')
    expect(source).not.toContain('<dt class="text-xs uppercase tracking-wide text-stone-400">状態</dt>')
    expect(source).not.toContain('log.created_at')
    expect(source).not.toContain('log.updated_at')
    expect(source).not.toContain('JSON.stringify(log.ai')
  })
})
