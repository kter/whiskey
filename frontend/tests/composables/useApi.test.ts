import { beforeEach, describe, expect, it, vi } from 'vitest'

const getToken = vi.fn()
const getTokenSafely = vi.fn()
const waitForAuthReady = vi.fn()

vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({ getToken, getTokenSafely, waitForAuthReady }),
}))

import { normalizeApiBaseUrl, normalizeApiPath, useApi } from '~/composables/useApi'

describe('useApi', () => {
  beforeEach(() => {
    vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBaseUrl: 'https://example.test/dev/' } }))
    vi.stubGlobal('navigateTo', vi.fn())
    vi.stubGlobal('fetch', vi.fn())
    getToken.mockReset()
    getTokenSafely.mockReset()
    waitForAuthReady.mockReset()
  })

  it('normalizes execute-api bases and request paths', () => {
    expect(normalizeApiBaseUrl('https://example.test/dev///')).toBe('https://example.test/dev')
    expect(normalizeApiPath('/api/reviews///')).toBe('/api/reviews')
  })

  it('does not acquire a token in none mode', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await useApi().request('/api/reviews/public', { auth: 'none', query: { limit: 10 } })

    expect(fetch).toHaveBeenCalledWith('https://example.test/dev/api/reviews/public?limit=10', expect.any(Object))
    expect(getToken).not.toHaveBeenCalled()
    expect(getTokenSafely).not.toHaveBeenCalled()
  })

  it('continues anonymously when an optional token is unavailable', async () => {
    getTokenSafely.mockResolvedValue(null)
    vi.mocked(fetch).mockResolvedValue(new Response('{}', { status: 200 }))
    await useApi().request('/api/example', { auth: 'optional' })

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(new Headers(options.headers).has('Authorization')).toBe(false)
  })

  it.each([[429, 'リクエストが集中'], [503, '一時的に利用できません']])('normalizes status %i', async (status, message) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ error: 'internal wording' }), { status }))
    await expect(useApi().request('/api/example', { auth: 'none' })).rejects.toEqual(expect.objectContaining({ status, message: expect.stringContaining(message) }))
  })
})
