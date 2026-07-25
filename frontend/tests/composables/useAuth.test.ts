import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as amplify from '@aws-amplify/auth'

vi.mock('@aws-amplify/auth', () => ({
  confirmResetPassword: vi.fn(),
  confirmSignUp: vi.fn(),
  fetchAuthSession: vi.fn(),
  fetchUserAttributes: vi.fn(),
  getCurrentUser: vi.fn(),
  resendSignUpCode: vi.fn(),
  resetPassword: vi.fn(),
  signIn: vi.fn(),
  signInWithRedirect: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
}))

import { __resetAuthStateForTests, __useAuthForTests, deriveUsername, useAuth } from '~/composables/useAuth'

describe('useAuth', () => {
  beforeEach(() => {
    __resetAuthStateForTests()
    sessionStorage.clear()
    vi.stubGlobal('useRuntimeConfig', () => ({ public: { mockAuth: '0', googleAuthEnabled: '0' } }))
  })

  it('returns the ID token', async () => {
    vi.mocked(amplify.fetchAuthSession).mockResolvedValue({
      tokens: {
        idToken: { toString: () => 'id-token' },
      },
    } as never)

    await expect(useAuth().getToken()).resolves.toBe('id-token')
  })

  it('uses the development-only local auth provider', async () => {
    vi.stubGlobal('useRuntimeConfig', () => ({ public: { mockAuth: '1', googleAuthEnabled: '0' } }))
    const auth = __useAuthForTests(true)
    await auth.initialize()

    expect(auth.isAuthenticated.value).toBe(true)
    expect(auth.currentUserId.value).toBe('local-user')
    await expect(auth.getToken()).resolves.toBe('mock-id-token')
    expect(amplify.fetchAuthSession).not.toHaveBeenCalled()
  })

  it('derives a stable opaque username from normalized email', async () => {
    const first = await deriveUsername(' Person@Example.COM ')
    const second = await deriveUsername('person@example.com')
    expect(first).toBe(second)
    expect(first).toMatch(/^w[a-f0-9]{64}$/)
    expect(first).not.toContain('@')
  })

  it('re-derives the username when sessionStorage was cleared before confirmation', async () => {
    vi.mocked(amplify.signUp).mockResolvedValue({ isSignUpComplete: false } as never)
    vi.mocked(amplify.confirmSignUp).mockResolvedValue({ isSignUpComplete: true } as never)
    const auth = useAuth()
    await auth.signUp('person@example.com', 'password123')
    sessionStorage.clear()
    await auth.confirmSignUp('PERSON@example.com', '123456')

    const username = await deriveUsername('person@example.com')
    expect(amplify.confirmSignUp).toHaveBeenCalledWith({ username, confirmationCode: '123456' })
  })

  it('derives the username from a different confirmation email instead of using the pending username', async () => {
    vi.mocked(amplify.signUp).mockResolvedValue({ isSignUpComplete: false } as never)
    vi.mocked(amplify.confirmSignUp).mockResolvedValue({ isSignUpComplete: false } as never)
    const auth = useAuth()
    await auth.signUp('first@example.com', 'password123')

    const firstUsername = await deriveUsername('first@example.com')
    expect(sessionStorage.getItem('whiskey.pending-signup-username')).toBe(JSON.stringify({
      email: 'first@example.com',
      username: firstUsername,
    }))

    await auth.confirmSignUp(' second@example.com ', '123456')

    const secondUsername = await deriveUsername('second@example.com')
    expect(amplify.confirmSignUp).toHaveBeenCalledWith({ username: secondUsername, confirmationCode: '123456' })
  })

  it('derives the username from a different resend email instead of using the pending username', async () => {
    vi.mocked(amplify.signUp).mockResolvedValue({ isSignUpComplete: false } as never)
    const auth = useAuth()
    await auth.signUp('first@example.com', 'password123')
    await auth.resendSignUpCode('SECOND@example.com')

    const secondUsername = await deriveUsername('second@example.com')
    expect(amplify.resendSignUpCode).toHaveBeenCalledWith({ username: secondUsername })
  })

  it('ignores a legacy plain-string pending username', async () => {
    const legacyUsername = await deriveUsername('first@example.com')
    sessionStorage.setItem('whiskey.pending-signup-username', legacyUsername)
    vi.mocked(amplify.confirmSignUp).mockResolvedValue({ isSignUpComplete: false } as never)

    await useAuth().confirmSignUp('second@example.com', '123456')

    const secondUsername = await deriveUsername('second@example.com')
    expect(amplify.confirmSignUp).toHaveBeenCalledWith({ username: secondUsername, confirmationCode: '123456' })
  })

  it('rejects Google sign-in when Google authentication is disabled', async () => {
    const auth = useAuth()

    await expect(auth.googleSignIn()).rejects.toThrow('Google認証は利用できません。')
    expect(amplify.signInWithRedirect).not.toHaveBeenCalled()
  })

  it('redirects to Google sign-in when the flag is the number 1', async () => {
    vi.stubGlobal('useRuntimeConfig', () => ({ public: { mockAuth: '0', googleAuthEnabled: 1 } }))
    const auth = useAuth()

    await auth.googleSignIn()

    expect(amplify.signInWithRedirect).toHaveBeenCalledWith({ provider: 'Google' })
  })
})
