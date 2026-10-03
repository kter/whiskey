import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrinkLog } from '~/composables/useDrinkLogs'

const record = (store: DrinkLog['store']): DrinkLog => ({
  id: 'log-1',
  user_id: 'user-1',
  status: 'complete',
  datetime: '2026-07-25T11:58:37.000Z',
  brand_text: '響',
  brand_source: 'manual',
  store,
})

const resolvePlaces = vi.fn()
const getLog = vi.fn()

vi.mock('~/composables/useDrinkLogs', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useDrinkLogs')>()
  return {
    ...actual,
    useDrinkLogs: () => ({
      getLog,
      updateLog: vi.fn(),
      deleteLog: vi.fn(),
      upsertLog: vi.fn(),
      removeLog: vi.fn(),
      resolvePlaces,
    }),
  }
})

vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({
    currentUserId: { value: 'user-1' },
    waitForAuthReady: vi.fn(async () => {}),
  }),
}))

/**
 * Chrome delivers no IntersectionObserver entries while a tab is hidden, so a
 * detail page that waits for one would show a placeholder forever. Never
 * invoking the callback here reproduces that environment.
 */
class SilentIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

vi.stubGlobal('IntersectionObserver', SilentIntersectionObserver)
vi.stubGlobal('useRoute', () => ({ params: { id: 'log-1' } }))
vi.stubGlobal('useRouter', () => ({ push: vi.fn() }))
vi.stubGlobal('navigateTo', vi.fn())

const { default: LogsDetailPage } = await import('~/pages/logs/[id].vue')
const { default: DrinkLogStoreDisplay } = await import('~/components/DrinkLogStoreDisplay.vue')
const { default: GoogleAttributions } = await import('~/components/GoogleAttributions.vue')

const mountDetail = async () => {
  const wrapper = mount(LogsDetailPage, {
    global: {
      components: { DrinkLogStoreDisplay, GoogleAttributions },
      stubs: { NuxtLink: true, ImageLightbox: true, DrinkLogImage: true },
    },
  })
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
  await nextTick()
  return wrapper
}

describe('detail page place resolution', () => {
  beforeEach(() => {
    resolvePlaces.mockReset()
    resolvePlaces.mockImplementation(async (items: { log_id: string }[]) => items.map(item => ({
      log_id: item.log_id,
      display_name: 'Google Bar',
      name_source: 'google',
      attributions: [],
    })))
    getLog.mockReset()
  })

  it.each([undefined, 'UNKNOWN', 'ROCKS'] as const)(
    'defaults missing detail serving style to UNKNOWN and preserves %s',
    async (servingStyle) => {
      getLog.mockResolvedValue({ ...record({ name: '' }), serving_style: servingStyle })
      const wrapper = await mountDetail()
      wrapper.findAll('button').find(button => button.text() === '編集')!.element.dispatchEvent(new Event('click', { bubbles: true }))
      await nextTick()
      const radios = wrapper.findAll<HTMLInputElement>('input[name="edit-serving-style"]')
      expect(radios[0]?.element.value).toBe('UNKNOWN')
      expect(radios.find(radio => radio.element.checked)?.element.value).toBe(servingStyle || 'UNKNOWN')
      wrapper.unmount()
    },
  )

  it('resolves the store name without waiting for the row to become visible', async () => {
    getLog.mockResolvedValue(record({ name: '', place_id: 'place-1' }))

    const wrapper = await mountDetail()

    expect(resolvePlaces).toHaveBeenCalledWith([{ log_id: 'log-1', place_id: 'place-1' }])
    await nextTick()
    expect(wrapper.text()).toContain('Google Bar')
    wrapper.unmount()
  })

  it('does not spend a Places call when the user already named the store', async () => {
    getLog.mockResolvedValue(record({ name: 'いつものバー', place_id: 'place-1' }))

    const wrapper = await mountDetail()

    expect(resolvePlaces).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('いつものバー')
    wrapper.unmount()
  })

  it('does not spend a Places call when there is no place reference', async () => {
    getLog.mockResolvedValue(record({ name: '' }))

    const wrapper = await mountDetail()

    expect(resolvePlaces).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('場所未登録')
    wrapper.unmount()
  })
})
