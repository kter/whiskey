import { useAuth } from '~/composables/useAuth'

export type AuthMode = 'none' | 'optional' | 'required'
export type QueryValue = string | number | boolean | null | undefined

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  auth?: AuthMode
  query?: Record<string, QueryValue>
  body?: unknown
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export const normalizeApiBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, '')

export const normalizeApiPath = (path: string) => {
  const [pathname, query] = path.split('?', 2)
  const normalizedPath = `/${pathname}`.replace(/\/{2,}/g, '/').replace(/\/+$/, '')
  return query ? `${normalizedPath}?${query}` : normalizedPath
}

const errorMessageFor = (status: number, body: unknown) => {
  if (status === 429) return 'リクエストが集中しています。しばらく待ってからお試しください。'
  if (status === 503) return 'サービスを一時的に利用できません。しばらく待ってからお試しください。'
  if (body && typeof body === 'object') {
    const data = body as Record<string, unknown>
    const message = data.message || data.error
    if (typeof message === 'string' && message.trim()) return message
  }
  return `APIリクエストに失敗しました (${status})`
}

export const useApi = () => {
  const config = useRuntimeConfig()
  const auth = useAuth()
  const baseUrl = normalizeApiBaseUrl(config.public.apiBaseUrl)

  const request = async <T>(path: string, options: ApiRequestOptions = {}): Promise<T> => {
    const { auth: authMode = 'required', query, body, ...fetchOptions } = options
    const normalizedPath = normalizeApiPath(path)
    const url = new URL(`${baseUrl}${normalizedPath}`)
    Object.entries(query || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
    })

    const headers = new Headers(fetchOptions.headers)
    headers.set('Accept', 'application/json')

    if (authMode !== 'none') {
      if (authMode === 'required') await auth.waitForAuthReady()
      const token = authMode === 'optional' ? await auth.getTokenSafely() : await auth.getToken().catch(async () => {
        await navigateTo('/login')
        throw new ApiError('ログインが必要です。', 401)
      })
      if (token) headers.set('Authorization', `Bearer ${token}`)
    }

    let requestBody: BodyInit | undefined
    if (body !== undefined) {
      headers.set('Content-Type', 'application/json')
      requestBody = JSON.stringify(body)
    }

    const response = await fetch(url.toString(), { ...fetchOptions, headers, body: requestBody })
    if (response.status === 204) return undefined as T

    const text = await response.text()
    let responseBody: unknown = null
    if (text) {
      try {
        responseBody = JSON.parse(text)
      } catch {
        responseBody = text
      }
    }

    if (!response.ok) throw new ApiError(errorMessageFor(response.status, responseBody), response.status, responseBody)
    return responseBody as T
  }

  return { baseUrl, request }
}
