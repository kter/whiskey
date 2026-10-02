import { beforeEach, describe, expect, it, vi } from 'vitest'

const getToken = vi.fn()
const getTokenSafely = vi.fn()
const waitForAuthReady = vi.fn()

vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({ getToken, getTokenSafely, waitForAuthReady }),
}))

import { errorMessageFor, formatDailyQuotaReset, isDailyQuotaError, ApiError, normalizeApiBaseUrl, normalizeApiPath, useApi } from '~/composables/useApi'

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
    expect(normalizeApiPath('/api/whiskeys///')).toBe('/api/whiskeys')
  })

  it('does not acquire a token in none mode', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await useApi().request('/api/whiskeys', { auth: 'none', query: { limit: 10 } })

    expect(fetch).toHaveBeenCalledWith('https://example.test/dev/api/whiskeys?limit=10', expect.any(Object))
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

  it.each([
    ['Daily analysis limit exceeded', '本日の画像解析の上限に達しました。'],
    ['Daily upload limit exceeded', '本日の画像アップロードの上限に達しました。'],
    ['Daily create or storage limit exceeded', '本日の記録作成の上限（または保存容量の上限）に達しました。'],
    ['Daily scan budget exceeded', '本日の検索の上限に達しました。'],
  ])('explains daily quota error %s', (error, message) => {
    const now = new Date('2026-10-01T00:00:00Z')
    expect(errorMessageFor(429, { error }, now, 'Asia/Tokyo')).toBe(`${message}10月2日 9:00 にリセットされます。`)
    expect(isDailyQuotaError(new ApiError(message, 429, { error }))).toBe(true)
  })

  it('formats the UTC reset in an explicit browser time zone', () => {
    expect(formatDailyQuotaReset(new Date('2026-10-01T00:00:00Z'), 'Asia/Tokyo')).toBe('10月2日 9:00')
  })

  it('explains the monthly analysis quota without a reset time', () => {
    expect(errorMessageFor(503, { error: 'Monthly analysis budget exhausted' })).toBe('今月の画像解析の上限に達しました。')
    expect(isDailyQuotaError(new ApiError('quota', 503, { error: 'Monthly analysis budget exhausted' }))).toBe(true)
  })
})
