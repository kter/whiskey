import { computed, onUnmounted, ref, watch } from 'vue'
import { useApi } from '~/composables/useApi'

export interface WhiskeySuggestion {
  id: string
  name: string
  name_ja: string
  name_en: string
  distillery: string
  region: string
  type: string
  description: string
}

export interface SearchFilters {
  name: string
}

interface SearchApiResponse {
  whiskeys: Array<Partial<WhiskeySuggestion> & { id: string }>
  count: number
  next_token: string | null
}

const toSuggestion = (whiskey: Partial<WhiskeySuggestion> & { id: string }): WhiskeySuggestion => ({
  id: whiskey.id,
  name: whiskey.name || whiskey.name_ja || whiskey.name_en || '',
  name_ja: whiskey.name_ja || '',
  name_en: whiskey.name_en || whiskey.name || '',
  distillery: whiskey.distillery || '',
  region: whiskey.region || '',
  type: whiskey.type || '',
  description: whiskey.description || '',
})

export const useWhiskeySearch = () => {
  const api = useApi()
  const searchQuery = ref('')
  const searchResults = ref<WhiskeySuggestion[]>([])
  const isSearching = ref(false)
  const searchError = ref('')
  const showSuggestions = ref(false)
  const searchFilters = ref<SearchFilters>({ name: '' })
  const advancedResults = ref<WhiskeySuggestion[]>([])
  const advancedNextToken = ref<string | null>(null)
  const isAdvancedSearching = ref(false)
  const advancedSearchError = ref('')
  let searchTimeout: ReturnType<typeof setTimeout> | null = null

  const performIncrementalSearch = async (query: string, limit = 10) => {
    if (!query.trim()) {
      searchResults.value = []
      showSuggestions.value = false
      return
    }
    isSearching.value = true
    searchError.value = ''
    try {
      const data = await api.request<SearchApiResponse>('/api/whiskeys/search', {
        auth: 'none',
        query: { q: query.trim(), limit },
      })
      searchResults.value = (data.whiskeys || []).map(toSuggestion)
      showSuggestions.value = true
    } catch (error) {
      searchError.value = error instanceof Error ? error.message : '検索中にエラーが発生しました'
      searchResults.value = []
      showSuggestions.value = false
    } finally {
      isSearching.value = false
    }
  }

  const debouncedSearch = (query: string, delay = 300) => {
    if (searchTimeout) clearTimeout(searchTimeout)
    searchTimeout = setTimeout(() => void performIncrementalSearch(query), delay)
  }

  watch(searchQuery, query => {
    if (query.trim()) debouncedSearch(query)
    else {
      searchResults.value = []
      showSuggestions.value = false
    }
  })

  onUnmounted(() => {
    if (searchTimeout) clearTimeout(searchTimeout)
  })

  const performAdvancedSearch = async (filters: Partial<SearchFilters>, limit = 20, append = false) => {
    isAdvancedSearching.value = true
    advancedSearchError.value = ''
    try {
      const token = append ? advancedNextToken.value : null
      const data = await api.request<SearchApiResponse>('/api/whiskeys/search', {
        auth: 'none',
        query: { q: filters.name?.trim() || '', limit, next_token: token },
      })
      const items = (data.whiskeys || []).map(toSuggestion)
      advancedResults.value = append ? [...advancedResults.value, ...items] : items
      advancedNextToken.value = data.next_token || null
      return data
    } catch (error) {
      advancedSearchError.value = error instanceof Error ? error.message : '検索中にエラーが発生しました'
      if (!append) advancedResults.value = []
      throw error
    } finally {
      isAdvancedSearching.value = false
    }
  }

  const loadMoreAdvancedResults = (limit = 20) => performAdvancedSearch(searchFilters.value, limit, true)

  const clearSearch = () => {
    searchQuery.value = ''
    searchResults.value = []
    searchError.value = ''
    showSuggestions.value = false
    if (searchTimeout) clearTimeout(searchTimeout)
    searchTimeout = null
  }

  const clearAdvancedSearch = () => {
    searchFilters.value = { name: '' }
    advancedResults.value = []
    advancedNextToken.value = null
    advancedSearchError.value = ''
  }

  const selectSuggestion = (suggestion: WhiskeySuggestion) => {
    const name = suggestion.name_ja || suggestion.name_en || suggestion.name
    searchQuery.value = name
    showSuggestions.value = false
    return { id: suggestion.id, name, distillery: suggestion.distillery }
  }

  const hideSuggestions = () => setTimeout(() => { showSuggestions.value = false }, 150)
  const showSuggestionsIfHasResults = () => {
    if (searchResults.value.length) showSuggestions.value = true
  }
  const formatSuggestionDisplay = (suggestion: WhiskeySuggestion) => suggestion.name_ja || suggestion.name_en || suggestion.name
  const formatSuggestionSecondaryText = (suggestion: WhiskeySuggestion) => [suggestion.region, suggestion.type].filter(Boolean).join(' • ')

  return {
    searchQuery,
    searchResults,
    isSearching,
    searchError,
    showSuggestions,
    searchFilters,
    advancedResults,
    advancedNextToken,
    isAdvancedSearching,
    advancedSearchError,
    hasResults: computed(() => searchResults.value.length > 0),
    hasAdvancedResults: computed(() => advancedResults.value.length > 0),
    isAnySearchActive: computed(() => isSearching.value || isAdvancedSearching.value),
    isMobile: computed(() => typeof window !== 'undefined' && window.innerWidth < 768),
    suggestionLimit: computed(() => typeof window !== 'undefined' && window.innerWidth < 768 ? 5 : 10),
    performIncrementalSearch,
    debouncedSearch,
    performAdvancedSearch,
    loadMoreAdvancedResults,
    clearSearch,
    clearAdvancedSearch,
    clearAllSearch: () => { clearSearch(); clearAdvancedSearch() },
    selectSuggestion,
    hideSuggestions,
    showSuggestionsIfHasResults,
    formatSuggestionDisplay,
    formatSuggestionSecondaryText,
  }
}
