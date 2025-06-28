import { ref, computed, watch, nextTick } from 'vue'
import type { Ref } from 'vue'

export interface WhiskeySuggestion {
  id: string
  name_ja: string
  name_en: string
  distillery_ja: string
  distillery_en: string
  region: string
  type: string
  description: string
}

export interface SearchResponse {
  query: string
  suggestions: WhiskeySuggestion[]
  total: number
  error?: string
}

export interface SearchFilters {
  name: string
  distillery: string
  region: string
  type: string
}

export interface AdvancedSearchResponse {
  filters: SearchFilters
  results: WhiskeySuggestion[]
  total: number
  error?: string
}

export const useWhiskeySearch = () => {
  const config = useRuntimeConfig()
  
  // 検索状態
  const searchQuery = ref('')
  const searchResults = ref<WhiskeySuggestion[]>([])
  const isSearching = ref(false)
  const searchError = ref('')
  const showSuggestions = ref(false)
  
  // 高度な検索フィルター
  const searchFilters = ref<SearchFilters>({
    name: '',
    distillery: '',
    region: '',
    type: ''
  })
  
  // 詳細検索結果
  const advancedResults = ref<WhiskeySuggestion[]>([])
  const isAdvancedSearching = ref(false)
  const advancedSearchError = ref('')
  
  // デバウンス用タイマー
  let searchTimeout: NodeJS.Timeout | null = null
  
  // 計算されたプロパティ
  const hasResults = computed(() => searchResults.value.length > 0)
  const hasAdvancedResults = computed(() => advancedResults.value.length > 0)
  const isAnySearchActive = computed(() => isSearching.value || isAdvancedSearching.value)
  
  // インクリメンタル検索
  const performIncrementalSearch = async (query: string, limit: number = 10) => {
    if (!query || query.length < 1) {
      searchResults.value = []
      showSuggestions.value = false
      return
    }
    
    try {
      isSearching.value = true
      searchError.value = ''
      
      const response = await fetch(`${config.public.apiBaseUrl}/api/whiskeys/search/suggest?q=${encodeURIComponent(query)}&limit=${limit}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      })
      
      if (!response.ok) {
        throw new Error(`検索エラー: ${response.status}`)
      }
      
      const data = await response.json()
      
      if (data.error) {
        throw new Error(data.error)
      }
      
      // APIレスポンス形式に対応：data.whiskeys から WhiskeySuggestion形式に変換
      const suggestions: WhiskeySuggestion[] = (data.whiskeys || []).map((whiskey: any) => ({
        id: whiskey.id,
        name_ja: whiskey.name,
        name_en: whiskey.name,
        distillery_ja: whiskey.distillery,
        distillery_en: whiskey.distillery,
        region: whiskey.region || '',
        type: whiskey.type || '',
        description: whiskey.description || ''
      }))
      
      searchResults.value = suggestions
      showSuggestions.value = true
      
    } catch (error: any) {
      searchError.value = error.message || '検索中にエラーが発生しました'
      searchResults.value = []
      showSuggestions.value = false
    } finally {
      isSearching.value = false
    }
  }
  
  // デバウンス付き検索
  const debouncedSearch = (query: string, delay: number = 300) => {
    if (searchTimeout) {
      clearTimeout(searchTimeout)
    }
    
    searchTimeout = setTimeout(() => {
      performIncrementalSearch(query)
    }, delay)
  }
  
  // 検索クエリの監視（リアルタイム検索）
  watch(searchQuery, (newQuery) => {
    if (newQuery.length >= 1) {
      debouncedSearch(newQuery)
    } else {
      searchResults.value = []
      showSuggestions.value = false
    }
  })
  
  // 詳細検索
  const performAdvancedSearch = async (filters: Partial<SearchFilters>, limit: number = 20) => {
    try {
      isAdvancedSearching.value = true
      advancedSearchError.value = ''
      
      const params = new URLSearchParams()
      
      if (filters.name) params.append('name', filters.name)
      if (filters.distillery) params.append('distillery', filters.distillery)
      if (filters.region) params.append('region', filters.region)
      if (filters.type) params.append('type', filters.type)
      params.append('limit', limit.toString())
      
      const response = await fetch(`${config.public.apiBaseUrl}/api/whiskeys/search?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      })
      
      if (!response.ok) {
        throw new Error(`詳細検索エラー: ${response.status}`)
      }
      
      const data = await response.json()
      
      if (data.error) {
        throw new Error(data.error)
      }
      
      // APIレスポンス形式に対応：data.whiskeys から WhiskeySuggestion形式に変換
      const results: WhiskeySuggestion[] = (data.whiskeys || []).map((whiskey: any) => ({
        id: whiskey.id,
        name_ja: whiskey.name,
        name_en: whiskey.name,
        distillery_ja: whiskey.distillery,
        distillery_en: whiskey.distillery,
        region: whiskey.region || '',
        type: whiskey.type || '',
        description: whiskey.description || ''
      }))
      
      advancedResults.value = results
      
      return data
      
    } catch (error: any) {
      advancedSearchError.value = error.message || '詳細検索中にエラーが発生しました'
      advancedResults.value = []
      throw error
    } finally {
      isAdvancedSearching.value = false
    }
  }
  
  // 検索結果をクリア
  const clearSearch = () => {
    searchQuery.value = ''
    searchResults.value = []
    showSuggestions.value = false
    searchError.value = ''
    
    if (searchTimeout) {
      clearTimeout(searchTimeout)
      searchTimeout = null
    }
  }
  
  // 詳細検索結果をクリア
  const clearAdvancedSearch = () => {
    searchFilters.value = {
      name: '',
      distillery: '',
      region: '',
      type: ''
    }
    advancedResults.value = []
    advancedSearchError.value = ''
  }
  
  // 全検索状態をクリア
  const clearAllSearch = () => {
    clearSearch()
    clearAdvancedSearch()
  }
  
  // 検索候補を選択
  const selectSuggestion = (suggestion: WhiskeySuggestion) => {
    searchQuery.value = suggestion.name_ja || suggestion.name_en
    showSuggestions.value = false
    
    return {
      name: suggestion.name_ja || suggestion.name_en,
      distillery: suggestion.distillery_ja || suggestion.distillery_en
    }
  }
  
  // フォーカス管理（モバイル対応）
  const hideSuggestions = () => {
    // 少し遅延を設けてクリックイベントを処理できるようにする
    setTimeout(() => {
      showSuggestions.value = false
    }, 150)
  }
  
  const showSuggestionsIfHasResults = () => {
    if (searchResults.value.length > 0) {
      showSuggestions.value = true
    }
  }
  
  // 検索結果のフォーマット関数
  const formatSuggestionDisplay = (suggestion: WhiskeySuggestion) => {
    const name = suggestion.name_ja || suggestion.name_en
    const distillery = suggestion.distillery_ja || suggestion.distillery_en
    
    if (distillery && distillery !== name) {
      return `${name} (${distillery})`
    }
    return name
  }
  
  const formatSuggestionSecondaryText = (suggestion: WhiskeySuggestion) => {
    const parts = []
    
    if (suggestion.region) {
      parts.push(suggestion.region)
    }
    
    if (suggestion.type) {
      parts.push(suggestion.type)
    }
    
    return parts.join(' • ')
  }
  
  // モバイル用ユーティリティ
  const isMobile = computed(() => {
    if (process.client) {
      return window.innerWidth < 768
    }
    return false
  })
  
  const suggestionLimit = computed(() => {
    return isMobile.value ? 5 : 10
  })
  
  return {
    // リアクティブな状態
    searchQuery,
    searchResults,
    isSearching,
    searchError,
    showSuggestions,
    searchFilters,
    advancedResults,
    isAdvancedSearching,
    advancedSearchError,
    
    // 計算されたプロパティ
    hasResults,
    hasAdvancedResults,
    isAnySearchActive,
    isMobile,
    suggestionLimit,
    
    // 検索機能
    performIncrementalSearch,
    debouncedSearch,
    performAdvancedSearch,
    
    // 状態管理
    clearSearch,
    clearAdvancedSearch,
    clearAllSearch,
    selectSuggestion,
    
    // UI制御
    hideSuggestions,
    showSuggestionsIfHasResults,
    
    // フォーマット関数
    formatSuggestionDisplay,
    formatSuggestionSecondaryText
  }
}