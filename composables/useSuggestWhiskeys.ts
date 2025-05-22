import { ref } from 'vue'
import { useAuth } from '~/composables/useAuth'

export const useSuggestWhiskeys = () => {
  const { getToken } = useAuth()
  const config = useRuntimeConfig()

  const suggestions = ref<string[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // サジェスト検索
  const searchWhiskeys = async (query: string) => {
    if (query.length < 2) {
      suggestions.value = []
      return
    }

    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(
        `${config.public.apiBaseUrl}/api/whiskeys/suggest?q=${encodeURIComponent(query)}`,
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      )

      if (!response.ok) {
        throw new Error('サジェストの取得に失敗しました')
      }

      const data = await response.json()
      suggestions.value = data.suggestions
    } catch (err) {
      error.value = 'サジェストの取得に失敗しました'
      suggestions.value = []
    } finally {
      loading.value = false
    }
  }

  // デバウンス処理
  let timeout: NodeJS.Timeout
  const debouncedSearch = (query: string) => {
    clearTimeout(timeout)
    timeout = setTimeout(() => {
      searchWhiskeys(query)
    }, 300)
  }

  return {
    suggestions,
    loading,
    error,
    searchWhiskeys,
    debouncedSearch
  }
} 