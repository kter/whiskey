import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GoogleAttributions from '~/components/GoogleAttributions.vue'

describe('GoogleAttributions', () => {
  it('links Google Maps to a URL-encoded place-name search', () => {
    const wrapper = mount(GoogleAttributions, {
      props: { attributions: [], query: 'Bar 621 東京' },
    })
    const link = wrapper.get('a')

    expect(link.text()).toBe('Google Maps')
    expect(link.attributes()).toMatchObject({
      href: 'https://www.google.com/maps/search/?api=1&query=Bar%20621%20%E6%9D%B1%E4%BA%AC',
      target: '_blank',
      rel: 'noopener noreferrer',
      translate: 'no',
    })
  })

  it.each([undefined, ''])('keeps Google Maps as plain text without a query (%s)', query => {
    const wrapper = mount(GoogleAttributions, {
      props: { attributions: [], query },
    })

    expect(wrapper.text()).toContain('Google Maps')
    expect(wrapper.find('a').exists()).toBe(false)
  })
})
