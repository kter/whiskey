import { computed } from 'vue'
import { ApiError, useApi } from '~/composables/useApi'

export interface DrinkLogCandidate {
  brand_text: string
  name_ja?: string
  name_en?: string
  brand_ja?: string
  brand_en?: string
  brand_key?: string
  distillery_ja?: string
  confidence: number
  whiskey_id?: string
  match_source?: string
  ai_name_ja?: string
  ai_name_en?: string
}

export interface DrinkLogAnalysis {
  analysis_id: string
  candidates: DrinkLogCandidate[]
  serving_style?: string
  model_id: string
  confidence: number | null
  multiple_detected?: boolean
}

export interface DrinkLogStore {
  name: string
  place_id?: string
}

export interface DrinkLog {
  id: string
  user_id: string
  status: 'pending' | 'complete' | 'deleting'
  image_url?: string
  brand_text: string
  brand_source: 'ai' | 'manual' | 'matched'
  serving_style?: string
  store: DrinkLogStore
  datetime: string
  notes?: string
  rating?: number
  ai?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface CreateDrinkLogPayload {
  analysis_id: string
  datetime?: string
  candidate_index?: number
  brand_text?: string
  serving_style?: string
  store?: DrinkLogStore
  notes?: string
  rating?: number
}

export interface DrinkLogFormValues {
  analysisId: string
  capturedAt?: string | null
  candidateIndex: number | null
  brandText: string
  servingStyle?: string
  storeName?: string
  placeId?: string
  notes?: string
  rating?: number | null
}

export interface DrinkLogEditValues {
  brandText: string
  servingStyle: string
  storeName: string
  placeId?: string
  notes: string
  rating: number | null
}

export interface UpdateDrinkLogPayload {
  brand_text?: string
  store?: { name: string; place_id?: string | null }
  notes?: string
  rating?: number
  serving_style?: string
}

export interface DrinkLogListParams {
  limit?: number
  next_token?: string | null
  brand?: string
  store?: string
  place_id?: string
}

export interface DrinkLogListResponse {
  results: DrinkLog[]
  count: number
  next_token: string | null
}

export interface PlaceCandidate {
  place_id: string
  display_name: string
  formatted_address: string
  attributions: unknown[]
}

export interface ResolvePlaceItem {
  log_id: string
  place_id: string
}

export interface ResolvedPlace {
  log_id: string
  display_name: string
  name_source: 'google' | string
  attributions: unknown[]
}

interface UploadUrlResponse {
  upload_url: string
  fields: Record<string, string>
  s3_key: string
}

type UploadProgressCallback = (progress: number) => void

export const normalizeDrinkLogError = (cause: unknown, fallback: string) => {
  if (cause instanceof ApiError) return cause.message
  if (cause instanceof Error && cause.message) return cause.message
  return fallback
}

export const buildDrinkLogPayload = (form: DrinkLogFormValues): CreateDrinkLogPayload => ({
  analysis_id: form.analysisId,
  ...(form.capturedAt ? { datetime: form.capturedAt } : {}),
  ...(form.candidateIndex === null
    ? { brand_text: form.brandText.trim() }
    : { candidate_index: form.candidateIndex }),
  ...(form.servingStyle ? { serving_style: form.servingStyle } : {}),
  ...(form.storeName?.trim() || form.placeId
    ? { store: { name: form.storeName?.trim() || '', ...(form.placeId ? { place_id: form.placeId } : {}) } }
    : {}),
  ...(form.notes?.trim() ? { notes: form.notes.trim() } : {}),
  ...(form.rating ? { rating: form.rating } : {}),
})

export const candidateIndexAfterBrandEdit = (
  candidates: DrinkLogCandidate[],
  selectedIndex: number | null,
  brandText: string,
) => selectedIndex !== null && candidates[selectedIndex]?.brand_text === brandText ? selectedIndex : null

export const buildUpdateDrinkLogPayload = (form: DrinkLogEditValues): UpdateDrinkLogPayload => ({
  brand_text: form.brandText.trim(),
  store: {
    name: form.storeName.trim(),
    ...(form.placeId ? { place_id: form.placeId } : {}),
  },
  serving_style: form.servingStyle,
  notes: form.notes.trim(),
  ...(form.rating === null ? {} : { rating: form.rating }),
})

const drinkLogTimestamp = (log: DrinkLog) => {
  const timestamp = Date.parse(log.datetime)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

export const sortDrinkLogs = (logs: DrinkLog[]) => [...logs].sort((left, right) => {
  const byDate = drinkLogTimestamp(right) - drinkLogTimestamp(left)
  return byDate || left.id.localeCompare(right.id)
})

export const mergeDrinkLogs = (...collections: DrinkLog[][]) => {
  const byId = new Map<string, DrinkLog>()
  collections.flat().forEach(log => byId.set(log.id, log))
  return sortDrinkLogs([...byId.values()])
}

export const useDrinkLogs = () => {
  const api = useApi()
  const logs = useState<DrinkLog[]>('drink-logs', () => [])
  const loadingCount = useState<number>('drink-logs-loading-count', () => 0)
  const error = useState<string | null>('drink-logs-error', () => null)
  const loading = computed(() => loadingCount.value > 0)

  const run = async <T>(fallback: string, operation: () => Promise<T>): Promise<T> => {
    loadingCount.value += 1
    error.value = null
    try {
      return await operation()
    } catch (cause) {
      error.value = normalizeDrinkLogError(cause, fallback)
      throw cause
    } finally {
      loadingCount.value = Math.max(0, loadingCount.value - 1)
    }
  }

  const getUploadUrl = (contentType: string) => run(
    '画像アップロードの準備に失敗しました。',
    () => api.request<UploadUrlResponse>('/api/drink-logs/upload-url', {
      method: 'POST', auth: 'required', body: { content_type: contentType },
    }),
  )

  const uploadToS3 = (
    uploadUrl: string,
    fields: Record<string, string>,
    blob: Blob,
    onProgress?: UploadProgressCallback,
  ) => run('画像のアップロードに失敗しました。', () => new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    Object.entries(fields).forEach(([key, value]) => form.append(key, value))
    form.append('file', blob, 'drink-log.jpg')

    xhr.open('POST', uploadUrl)
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100)
        resolve()
      } else {
        reject(new Error(`画像のアップロードに失敗しました (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new Error('画像のアップロード中に通信エラーが発生しました。'))
    xhr.onabort = () => reject(new Error('画像のアップロードが中断されました。'))
    xhr.send(form)
  }))

  const analyze = (s3Key: string) => run(
    '画像解析に失敗しました。銘柄を確認して、もう一度お試しください。',
    () => api.request<DrinkLogAnalysis>('/api/drink-logs/analyze', {
      method: 'POST', auth: 'required', body: { s3_key: s3Key },
    }),
  )

  const createLog = (payload: CreateDrinkLogPayload) => run(
    '記録の保存に失敗しました。',
    () => api.request<DrinkLog>('/api/drink-logs', { method: 'POST', auth: 'required', body: payload }),
  )

  const listLogs = (params: DrinkLogListParams = {}) => run(
    '記録一覧の取得に失敗しました。',
    () => api.request<DrinkLogListResponse>('/api/drink-logs', {
      auth: 'required',
      query: {
        limit: params.limit,
        next_token: params.next_token,
        brand: params.brand,
        store: params.store,
        place_id: params.place_id,
      },
    }),
  )

  const getLog = (id: string) => run(
    '記録の取得に失敗しました。',
    () => api.request<DrinkLog>(`/api/drink-logs/${encodeURIComponent(id)}`, { auth: 'required' }),
  )

  const updateLog = (id: string, payload: UpdateDrinkLogPayload) => run(
    '記録の更新に失敗しました。',
    () => api.request<DrinkLog>(`/api/drink-logs/${encodeURIComponent(id)}`, {
      method: 'PUT', auth: 'required', body: payload,
    }),
  )

  const deleteLog = (id: string) => run(
    '記録の削除に失敗しました。',
    () => api.request<void>(`/api/drink-logs/${encodeURIComponent(id)}`, { method: 'DELETE', auth: 'required' }),
  )

  const searchPlaces = (lat: number, lng: number) => run(
    '近くの店を検索できませんでした。店名は手入力できます。',
    () => api.request<PlaceCandidate[]>('/api/drink-logs/places', {
      method: 'POST', auth: 'required', body: { lat, lng },
    }),
  )

  const resolvePlaces = (items: ResolvePlaceItem[]) => run(
    '店情報の取得に失敗しました。',
    async () => (await api.request<{ results: ResolvedPlace[] }>('/api/drink-logs/places/resolve', {
      method: 'POST', auth: 'required', body: { items },
    })).results,
  )

  const upsertLog = (log: DrinkLog) => {
    logs.value = mergeDrinkLogs(logs.value, [log])
  }

  const upsertLogs = (records: DrinkLog[]) => {
    logs.value = mergeDrinkLogs(logs.value, records)
  }

  const removeLog = (id: string) => {
    logs.value = logs.value.filter(log => log.id !== id)
  }

  return {
    logs,
    loading,
    error,
    getUploadUrl,
    uploadToS3,
    analyze,
    createLog,
    listLogs,
    getLog,
    updateLog,
    deleteLog,
    searchPlaces,
    resolvePlaces,
    upsertLog,
    upsertLogs,
    removeLog,
  }
}
