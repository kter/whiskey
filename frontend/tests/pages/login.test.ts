import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { mount } from '@vue/test-utils'
import { computed, defineComponent, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { isGoogleAuthEnabled } from '~/utils/googleAuth'

const source = readFileSync(resolve(process.cwd(), 'pages/login.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1]

if (!template) throw new Error('login.vue template not found')

const renderLogin = (googleAuthEnabled: unknown) => mount(defineComponent({
  setup: () => ({
    email: ref(''),
    password: ref(''),
    error: ref(''),
    loading: ref(false),
    googleEnabled: computed(() => isGoogleAuthEnabled(googleAuthEnabled)),
    handleSignIn: vi.fn(),
    handleGoogleSignIn: vi.fn(),
  }),
  template,
}))

describe('login page Google authentication', () => {
  it('renders the Google button when the flag is the number 1', () => {
    const wrapper = renderLogin(1)

    expect(wrapper.text()).toContain('Googleでログイン')
  })

  it('does not render the Google button when the flag is the number 0', () => {
    const wrapper = renderLogin(0)

    expect(wrapper.text()).not.toContain('Googleでログイン')
  })
})
