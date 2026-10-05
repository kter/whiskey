import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import LogsPage from '~/pages/logs/index.vue'
import DrinkLogChat from '~/components/DrinkLogChat.vue'

const auth = vi.hoisted(() => ({ currentUserId: null as unknown }))
vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({ currentUserId: auth.currentUserId, waitForAuthReady: async () => {} }),
}))
vi.mock('~/composables/useDrinkLogs', () => ({
  useDrinkLogs: () => ({ logs: { value: [] }, listLogs: async () => ({ results: [], next_token: null }), upsertLogs: () => {} }),
  mergeDrinkLogs: () => [], sortDrinkLogs: () => [],
}))
vi.mock('~/composables/useVisiblePlaceResolver', () => ({
  useVisiblePlaceResolver: () => ({ resolvedPlaces: {}, register: () => {} }),
}))

beforeEach(() => {
  vi.stubGlobal('useRoute', () => ({ query: {} }))
  vi.stubGlobal('useRouter', () => ({ replace: vi.fn() }))
  vi.stubGlobal('navigateTo', vi.fn())
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBaseUrl: 'https://api.test.whiskeybar.site' } }))
})
afterEach(() => { vi.unstubAllGlobals() })

describe('Drink Log chat on the history page', () => {
  it.each(['user-1', null])('shows chat only for an authenticated user (%s)', async (user) => {
    auth.currentUserId = ref(user)
    const wrapper = mount(LogsPage, { global: { stubs: { NuxtLink: true } } })
    await flushPromises()
    expect(wrapper.findComponent(DrinkLogChat).exists()).toBe(Boolean(user))
    wrapper.unmount()
  })
})
