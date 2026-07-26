import { ref } from 'vue'
import type {
  CursorParams,
  CursorResponse,
  Whiskey,
} from '~/types/whiskey'
import { useApi } from '~/composables/useApi'

export const useWhiskeys = () => {
  const api = useApi()
  const whiskeys = ref<Whiskey[]>([])
  const nextToken = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const run = async <T>(message: string, operation: () => Promise<T>): Promise<T> => {
    loading.value = true
    error.value = null
    try {
      return await operation()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : message
      throw cause
    } finally {
      loading.value = false
    }
  }

  const fetchWhiskeyList = (params: CursorParams = {}, append = false) => run(
    'ウイスキー一覧の取得に失敗しました',
    async () => {
      const data = await api.request<CursorResponse<Whiskey>>('/api/whiskeys', {
        auth: 'none',
        query: { limit: params.limit || 20, next_token: params.next_token },
      })
      const items = data.whiskeys || []
      whiskeys.value = append ? [...whiskeys.value, ...items] : items
      nextToken.value = data.next_token || null
      return items
    },
  )

  return {
    whiskeys,
    nextToken,
    loading,
    error,
    fetchWhiskeyList,
  }
}
