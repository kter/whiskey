import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrinkLog } from '~/composables/useDrinkLogs'

const getLog = vi.fn()
const upsertLog = vi.fn()
vi.mock('~/composables/useDrinkLogs', () => ({
  useDrinkLogs: () => ({ getLog, upsertLog }),
}))

import DrinkLogImage from '~/components/DrinkLogImage.vue'

const original: DrinkLog = {
  id: 'log-1',
  user_id: 'user-1',
  status: 'complete',
  datetime: '2026-07-21T00:00:00Z',
  image_url: 'https://signed.test/expired',
  brand_text: '響',
  brand_source: 'manual',
  store: { name: '' },
}

describe('DrinkLogImage', () => {
  beforeEach(() => {
    getLog.mockReset()
    upsertLog.mockReset()
  })

  it('re-signs once on image error, then settles on a placeholder', async () => {
    const refreshed = { ...original, image_url: 'https://signed.test/refreshed' }
    getLog.mockResolvedValue(refreshed)
    const wrapper = mount(DrinkLogImage, { props: { log: original, alt: '記録写真' } })

    wrapper.get('img').element.dispatchEvent(new Event('error'))
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0))
    expect(getLog).toHaveBeenCalledTimes(1)
    expect(wrapper.get('img').attributes('src')).toBe(refreshed.image_url)
    expect(upsertLog).toHaveBeenCalledWith(refreshed)

    wrapper.get('img').element.dispatchEvent(new Event('error'))
    await nextTick()
    expect(getLog).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('画像を表示できません')
  })
})
