import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import ImageLightbox from '~/components/ImageLightbox.vue'

afterEach(() => {
  document.body.style.overflow = ''
  document.body.replaceChildren()
})

describe('ImageLightbox', () => {
  it('renders the selected image only while open', async () => {
    const wrapper = mount(ImageLightbox, {
      props: {
        open: false,
        src: 'blob:selected-image',
        alt: '1杯目の飲酒記録写真',
      },
    })

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)

    await wrapper.setProps({ open: true })

    const dialog = wrapper.get('[role="dialog"]')
    const image = dialog.get('img')
    expect(dialog.attributes('aria-label')).toBe('1杯目の飲酒記録写真')
    expect(image.attributes('src')).toBe('blob:selected-image')
    expect(image.attributes('alt')).toBe('1杯目の飲酒記録写真')

    wrapper.unmount()
  })

  it('requests closing from the close button', async () => {
    const wrapper = mount(ImageLightbox, {
      props: { open: true, src: 'blob:image', alt: '記録写真' },
    })

    wrapper.get<HTMLButtonElement>('button[aria-label="閉じる"]').element.click()
    await nextTick()

    expect(wrapper.emitted('update:open')).toEqual([[false]])
    wrapper.unmount()
  })

  it('requests closing from an overlay click', async () => {
    const wrapper = mount(ImageLightbox, {
      props: { open: true, src: 'blob:image', alt: '記録写真' },
    })

    wrapper.get<HTMLElement>('[role="dialog"]').element.click()
    await nextTick()

    expect(wrapper.emitted('update:open')).toEqual([[false]])
    wrapper.unmount()
  })

  it('does not close when the image itself is clicked', async () => {
    const wrapper = mount(ImageLightbox, {
      props: { open: true, src: 'blob:image', alt: '記録写真' },
    })

    wrapper.get<HTMLImageElement>('img').element.click()
    await nextTick()

    expect(wrapper.emitted('update:open')).toBeUndefined()
    wrapper.unmount()
  })

  it('requests closing from the Escape key', () => {
    const wrapper = mount(ImageLightbox, {
      props: { open: true, src: 'blob:image', alt: '記録写真' },
    })
    const keydownCall = vi.mocked(window.addEventListener).mock.calls
      .find(([eventName]) => String(eventName) === 'keydown')
    expect(keydownCall).toBeDefined()

    const listener = keydownCall?.[1] as EventListener
    listener(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(wrapper.emitted('update:open')).toEqual([[false]])
    wrapper.unmount()
  })

  it('locks scrolling, focuses the close button, and restores both on close', async () => {
    document.body.style.overflow = 'auto'
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()

    const wrapper = mount(ImageLightbox, {
      attachTo: document.body,
      props: { open: false, src: 'blob:image', alt: '記録写真' },
    })
    await wrapper.setProps({ open: true })
    await nextTick()

    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement).toBe(wrapper.get('button[aria-label="閉じる"]').element)

    await wrapper.setProps({ open: false })
    await nextTick()

    expect(document.body.style.overflow).toBe('auto')
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })
})
