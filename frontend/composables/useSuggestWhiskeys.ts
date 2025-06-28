import { ref } from 'vue'

export const useSuggestWhiskeys = () => {
  const config = useRuntimeConfig()

  const suggestions = ref<string[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // サジェスト検索（認証不要）
  const searchWhiskeys = async (query: string) => {
    if (query.length < 2) {
      suggestions.value = []
      return
    }

    try {
      loading.value = true
      error.value = null

      // サジェストAPIは認証不要のパブリックエンドポイント
      const response = await fetch(
        `${config.public.apiBaseUrl}/api/whiskeys/search/suggest?q=${encodeURIComponent(query)}&limit=10`
      )

      if (!response.ok) {
        throw new Error('サジェストの取得に失敗しました')
      }

      const data = await response.json()
      // バックエンドのレスポンス形式に応じて調整（whiskeysフィールドから名前を抽出）
      suggestions.value = data.whiskeys ? data.whiskeys.map((whiskey: any) => whiskey.name) : []
    } catch (err) {
      error.value = 'サジェストの取得に失敗しました'
      suggestions.value = []
      console.error('Search whiskeys error:', err)
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