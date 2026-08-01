import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrinkLog } from '~/composables/useDrinkLogs'

const resolvePlaces = vi.fn()
vi.mock('~/composables/useDrinkLogs', () => ({
  useDrinkLogs: () => ({ resolvePlaces }),
}))

import DrinkLogStoreDisplay from '~/components/DrinkLogStoreDisplay.vue'
import GoogleAttributions from '~/components/GoogleAttributions.vue'
import { useVisiblePlaceResolver } from '~/composables/useVisiblePlaceResolver'

let intersectionCallback: IntersectionObserverCallback
class MockIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  constructor(callback: IntersectionObserverCallback) {
    intersectionCallback = callback
  }
}

const record = (index: number): DrinkLog => ({
  id: `log-${index}`,
  user_id: 'user-1',
  status: 'complete',
  datetime: '2026-07-21T00:00:00Z',
  brand_text: '響',
  brand_source: 'manual',
  store: { name: '', place_id: `place-${index}` },
})

describe('visible Places resolution and attribution', () => {
  beforeEach(() => {
    resolvePlaces.mockReset()
    resolvePlaces.mockImplementation(async items => items.map((item: { log_id: string }) => ({
      log_id: item.log_id,
      display_name: `Google ${item.log_id}`,
      name_source: 'google',
      attributions: [{ provider: 'Provider' }],
    })))
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
  })

  it('deduplicates visible IDs and resolves in chunks of at most 10', async () => {
    const logs = Array.from({ length: 11 }, (_, index) => record(index))
    const Host = defineComponent({
      setup() {
        const { register } = useVisiblePlaceResolver()
        return { logs: ref(logs), register }
      },
      template: '<div><div v-for="log in logs" :key="log.id" :ref="el => register(el, log)" :data-log-id="log.id" :data-place-id="log.store.place_id"></div></div>',
    })
    const wrapper = mount(Host)
    const elements = wrapper.findAll('[data-log-id]').map(node => node.element)
    intersectionCallback([
      ...elements.map(element => ({ isIntersecting: true, target: element } as IntersectionObserverEntry)),
      { isIntersecting: true, target: elements[0] } as IntersectionObserverEntry,
    ], {} as IntersectionObserver)
    await nextTick()

    expect(resolvePlaces).toHaveBeenCalledTimes(2)
    expect(resolvePlaces.mock.calls.map(call => call[0].length)).toEqual([10, 1])
    expect(resolvePlaces.mock.calls.flatMap(call => call[0]).map(item => item.log_id)).toHaveLength(11)
  })

  it('renders Google attribution next to a resolved display name on both pages', () => {
    const wrapper = mount(DrinkLogStoreDisplay, {
      props: {
        log: record(1),
        resolvedPlace: {
          log_id: 'log-1',
          display_name: 'Google Bar',
          name_source: 'google',
          attributions: [{ provider: 'Provider' }],
        },
      },
      global: { components: { GoogleAttributions } },
    })
    expect(wrapper.text()).toContain('Google Bar')
    expect(wrapper.text()).toContain('Google Maps')
    expect(wrapper.text()).toContain('Provider')
    expect(wrapper.get('a').attributes('href')).toBe(
      'https://www.google.com/maps/search/?api=1&query=Google%20Bar',
    )

    for (const page of ['pages/logs/index.vue', 'pages/logs/[id].vue']) {
      const pageSource = readFileSync(resolve(process.cwd(), page), 'utf8')
      expect(pageSource).toContain('<DrinkLogStoreDisplay')
      expect(pageSource).toContain(':resolved-place=')
    }
  })

  it.each([
    [{ name: '', place_id: 'place-1' }, '場所登録済み'],
    [{ name: '' }, '場所未登録'],
  ])('does not search for the %s placeholder', (store, placeholder) => {
    const wrapper = mount(DrinkLogStoreDisplay, {
      props: {
        log: { ...record(1), store },
        resolvedPlace: {
          log_id: 'log-1',
          display_name: '',
          name_source: 'google',
          attributions: [],
        },
      },
      global: { components: { GoogleAttributions } },
    })

    expect(wrapper.text()).toContain(placeholder)
    expect(wrapper.find('a').exists()).toBe(false)
  })

  it('does not search for the Places resolution failure placeholder', () => {
    // PLACEHOLDER_NAME in lambda/drink-log-analyze/places.py: returned with
    // name_source "google" when the lookup fails, so it reaches the display
    // through the same path as a real resolved name.
    const wrapper = mount(DrinkLogStoreDisplay, {
      props: {
        log: { ...record(1), store: { name: '', place_id: 'place-1' } },
        resolvedPlace: {
          log_id: 'log-1',
          display_name: '店舗情報を取得できません',
          name_source: 'google',
          attributions: [],
        },
      },
      global: { components: { GoogleAttributions } },
    })

    expect(wrapper.text()).toContain('店舗情報を取得できません')
    expect(wrapper.find('a').exists()).toBe(false)
  })
})
