import { ref } from 'vue'
import { useApi } from '~/composables/useApi'

interface SuggestResponse {
  whiskeys: Array<{ name?: string; name_ja?: string; name_en?: string }>
}

export const useSuggestWhiskeys = () => {
  const api = useApi()
  const suggestions = ref<string[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let timeout: ReturnType<typeof setTimeout> | null = null

  const searchWhiskeys = async (query: string) => {
    if (query.trim().length < 2) {
      suggestions.value = []
      return
    }
    loading.value = true
    error.value = null
    try {
      const data = await api.request<SuggestResponse>('/api/whiskeys/search', {
        auth: 'none',
        query: { q: query.trim(), limit: 10 },
      })
      suggestions.value = (data.whiskeys || []).map(item => item.name_ja || item.name_en || item.name || '')
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'サジェストの取得に失敗しました'
      suggestions.value = []
    } finally {
      loading.value = false
    }
  }

  const debouncedSearch = (query: string) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => void searchWhiskeys(query), 300)
  }

  return { suggestions, loading, error, searchWhiskeys, debouncedSearch }
}
