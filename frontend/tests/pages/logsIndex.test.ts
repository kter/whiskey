import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { describe, expect, it } from 'vitest'
import type { DrinkLog } from '~/composables/useDrinkLogs'
import { groupDrinkLogsByLocalDate } from '~/utils/drinkLogs'

const source = readFileSync(resolve(process.cwd(), 'pages/logs/index.vue'), 'utf8')

const record = (id: string, datetime: string): DrinkLog => ({
  id,
  user_id: 'user-1',
  status: 'complete',
  datetime,
  brand_text: id,
  brand_source: 'manual',
  store: { name: '' },
})

describe('logs timeline', () => {
  it('groups UTC timestamps by their Japanese date in the selected local timezone', () => {
    const groups = groupDrinkLogsByLocalDate([
      record('before-midnight-utc', '2026-07-21T23:30:00Z'),
      record('same-local-day', '2026-07-22T10:00:00Z'),
      record('next-local-day', '2026-07-22T16:00:00Z'),
    ], 'Asia/Tokyo')

    expect(groups.map(group => [group.label, group.logs.map(log => log.id)])).toEqual([
      ['2026年7月22日', ['before-midnight-utc', 'same-local-day']],
      ['2026年7月23日', ['next-local-day']],
    ])
  })

  it('uses the next token for appended server pages from an intersection observer', () => {
    expect(source).toContain("new IntersectionObserver")
    expect(source).toContain("loadLogs(true)")
    expect(source).toContain("next_token: nextToken.value")
    expect(source).toContain("mergeDrinkLogs(visibleLogs.value, response.results)")
  })

  it('sends trimmed brand and store chips as server filters and resets the cursor', () => {
    expect(source).toContain("brand: activeBrand.value")
    expect(source).toContain("store: activeStore.value")
    expect(source).toContain("nextToken.value = null")
    expect(source).toContain("銘柄: {{ activeBrand }} ×")
    expect(source).toContain("店: {{ activeStore }} ×")
  })
})
