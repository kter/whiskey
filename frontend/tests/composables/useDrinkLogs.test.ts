import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.fn()
vi.mock('~/composables/useApi', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useApi')>()
  return { ...actual, useApi: () => ({ request }) }
})

import { useDrinkLogs } from '~/composables/useDrinkLogs'

const state = new Map<string, ReturnType<typeof ref>>()

describe('useDrinkLogs API contract', () => {
  beforeEach(() => {
    request.mockReset()
    request.mockResolvedValue({})
    state.clear()
    vi.stubGlobal('useState', <T>(key: string, init: () => T) => {
      if (!state.has(key)) state.set(key, ref(init()))
      return state.get(key)
    })
  })

  it('uses the required upload, analyze and create contracts', async () => {
    request
      .mockResolvedValueOnce({ upload_url: 'https://s3.test', fields: { key: 'tmp/u/a.jpg' }, s3_key: 'tmp/u/a.jpg' })
      .mockResolvedValueOnce({ analysis_id: 'a1', candidates: [], model_id: 'model', confidence: 0 })
      .mockResolvedValueOnce({ id: 'log-1' })
    const drinkLogs = useDrinkLogs()

    await drinkLogs.getUploadUrl('image/jpeg')
    await drinkLogs.analyze('tmp/u/a.jpg')
    await drinkLogs.createLog({ analysis_id: 'a1', candidate_index: 0 })

    expect(request).toHaveBeenNthCalledWith(1, '/api/drink-logs/upload-url', {
      method: 'POST', auth: 'required', body: { content_type: 'image/jpeg' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/drink-logs/analyze', {
      method: 'POST', auth: 'required', body: { s3_key: 'tmp/u/a.jpg' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/api/drink-logs', {
      method: 'POST', auth: 'required', body: { analysis_id: 'a1', candidate_index: 0 },
    })
  })

  it('uses every list, detail, update, delete and Places endpoint with required auth', async () => {
    request
      .mockResolvedValueOnce({ results: [], count: 0, next_token: null })
      .mockResolvedValueOnce({ id: 'log/1' })
      .mockResolvedValueOnce({ id: 'log/1' })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ results: [] })
    const drinkLogs = useDrinkLogs()

    await drinkLogs.listLogs({ limit: 10, next_token: 'next', brand: '響', store: 'bar', place_id: 'p1' })
    await drinkLogs.getLog('log/1')
    await drinkLogs.updateLog('log/1', { brand_text: '響' })
    await drinkLogs.deleteLog('log/1')
    await drinkLogs.searchPlaces(35, 139)
    await drinkLogs.resolvePlaces([{ log_id: 'log/1', place_id: 'p1' }])

    expect(request.mock.calls).toEqual([
      ['/api/drink-logs', { auth: 'required', query: { limit: 10, next_token: 'next', brand: '響', store: 'bar', place_id: 'p1' } }],
      ['/api/drink-logs/log%2F1', { auth: 'required' }],
      ['/api/drink-logs/log%2F1', { method: 'PUT', auth: 'required', body: { brand_text: '響' } }],
      ['/api/drink-logs/log%2F1', { method: 'DELETE', auth: 'required' }],
      ['/api/drink-logs/places', { method: 'POST', auth: 'required', body: { lat: 35, lng: 139 } }],
      ['/api/drink-logs/places/resolve', { method: 'POST', auth: 'required', body: { items: [{ log_id: 'log/1', place_id: 'p1' }] } }],
    ])
  })

  it('uploads a multipart form with XHR and reports progress', async () => {
    const progress = vi.fn()
    const open = vi.fn()
    const send = vi.fn(function (this: MockXhr, body: FormData) {
      expect(body.get('key')).toBe('tmp/u/a.jpg')
      expect(body.get('file')).toBeInstanceOf(Blob)
      this.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 } as ProgressEvent)
      this.onload?.(new ProgressEvent('load'))
    })
    class MockXhr {
      status = 204
      upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
      onload: ((event: ProgressEvent) => void) | null = null
      onerror: ((event: ProgressEvent) => void) | null = null
      onabort: ((event: ProgressEvent) => void) | null = null
      open = open
      send = send
    }
    vi.stubGlobal('XMLHttpRequest', MockXhr)

    await useDrinkLogs().uploadToS3(
      'https://s3.test/upload',
      { key: 'tmp/u/a.jpg' },
      new Blob(['jpeg'], { type: 'image/jpeg' }),
      progress,
    )

    expect(open).toHaveBeenCalledWith('POST', 'https://s3.test/upload')
    expect(progress).toHaveBeenNthCalledWith(1, 50)
    expect(progress).toHaveBeenLastCalledWith(100)
    expect(request).not.toHaveBeenCalled()
  })
})

