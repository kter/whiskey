/**
 * Tests for useWhiskeySearch Composable
 * ウイスキー検索コンポーザブルのテスト
 */
import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest'
import { ref, nextTick } from 'vue'
import { useWhiskeySearch } from '~/composables/useWhiskeySearch'
import type { WhiskeySuggestion, SearchFilters } from '~/composables/useWhiskeySearch'

// Mock fetch and runtime config
const mockFetch = vi.fn() as Mock
global.fetch = mockFetch

// Mock useRuntimeConfig globally
global.useRuntimeConfig = vi.fn(() => ({
  public: {
    apiBaseUrl: 'https://api.test.whiskeybar.site'
  }
}))

// Mock process.client for mobile detection
Object.defineProperty(global, 'process', {
  value: { client: true }
})

// Mock window for mobile detection
Object.defineProperty(global, 'window', {
  value: { innerWidth: 1024 }
})

// Sample whiskey data for testing
const mockWhiskeyData: WhiskeySuggestion[] = [
  {
    id: 'whiskey-1',
    name_ja: '響 21年',
    name_en: 'Hibiki 21 Year Old',
    distillery_ja: 'サントリー',
    distillery_en: 'Suntory',
    region: 'Japan',
    type: 'Blended',
    description: 'Premium Japanese whisky'
  },
  {
    id: 'whiskey-2',
    name_ja: 'マッカラン 18年',
    name_en: 'The Macallan 18',
    distillery_ja: 'マッカラン',
    distillery_en: 'The Macallan',
    region: 'Speyside',
    type: 'Single Malt',
    description: 'Premium Scotch whisky'
  }
]

describe('useWhiskeySearch', () => {
  let composable: ReturnType<typeof useWhiskeySearch>

  beforeEach(() => {
    vi.clearAllMocks()
    composable = useWhiskeySearch()
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  describe('Initial State', () => {
    it('should initialize with empty search state', () => {
      expect(composable.searchQuery.value).toBe('')
      expect(composable.searchResults.value).toEqual([])
      expect(composable.isSearching.value).toBe(false)
      expect(composable.searchError.value).toBe('')
      expect(composable.showSuggestions.value).toBe(false)
    })

    it('should initialize with empty advanced search state', () => {
      expect(composable.searchFilters.value).toEqual({
        name: '',
        distillery: '',
        region: '',
        type: ''
      })
      expect(composable.advancedResults.value).toEqual([])
      expect(composable.isAdvancedSearching.value).toBe(false)
      expect(composable.advancedSearchError.value).toBe('')
    })

    it('should have correct computed properties for empty state', () => {
      expect(composable.hasResults.value).toBe(false)
      expect(composable.hasAdvancedResults.value).toBe(false)
      expect(composable.isAnySearchActive.value).toBe(false)
    })
  })

  describe('Incremental Search', () => {
    it('should perform successful incremental search', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({
          whiskeys: [
            {
              id: 'whiskey-1',
              name: '響 21年',
              distillery: 'サントリー',
              region: 'Japan',
              type: 'Blended'
            }
          ]
        })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('響')

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search/suggest?q=%E9%9F%BF&limit=10',
        {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        }
      )

      expect(composable.searchResults.value).toHaveLength(1)
      expect(composable.searchResults.value[0].name_ja).toBe('響 21年')
      expect(composable.showSuggestions.value).toBe(true)
      expect(composable.isSearching.value).toBe(false)
      expect(composable.searchError.value).toBe('')
    })

    it('should handle empty query', async () => {
      await composable.performIncrementalSearch('')

      expect(mockFetch).not.toHaveBeenCalled()
      expect(composable.searchResults.value).toEqual([])
      expect(composable.showSuggestions.value).toBe(false)
    })

    it('should handle search API error', async () => {
      const mockResponse = {
        ok: false,
        status: 500
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('test')

      expect(composable.searchError.value).toBe('検索エラー: 500')
      expect(composable.searchResults.value).toEqual([])
      expect(composable.showSuggestions.value).toBe(false)
      expect(composable.isSearching.value).toBe(false)
    })

    it('should handle API response with error field', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({
          error: 'Database connection failed'
        })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('test')

      expect(composable.searchError.value).toBe('Database connection failed')
      expect(composable.searchResults.value).toEqual([])
    })

    it('should handle network error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'))

      await composable.performIncrementalSearch('test')

      expect(composable.searchError.value).toBe('Network error')
      expect(composable.searchResults.value).toEqual([])
      expect(composable.isSearching.value).toBe(false)
    })

    it('should handle custom limit parameter', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [] })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('test', 5)

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search/suggest?q=test&limit=5',
        expect.any(Object)
      )
    })
  })

  describe('Debounced Search', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should debounce search calls', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [] })
      }
      mockFetch.mockResolvedValue(mockResponse)

      // Call debouncedSearch multiple times quickly
      composable.debouncedSearch('test1')
      composable.debouncedSearch('test2')
      composable.debouncedSearch('test3')

      // No calls should be made yet
      expect(mockFetch).not.toHaveBeenCalled()

      // Fast-forward time
      vi.advanceTimersByTime(300)
      await nextTick()

      // Only the last search should be executed
      expect(mockFetch).toHaveBeenCalledTimes(1)
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search/suggest?q=test3&limit=10',
        expect.any(Object)
      )
    })

    it('should use custom delay', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [] })
      }
      mockFetch.mockResolvedValue(mockResponse)

      composable.debouncedSearch('test', 500)

      // Advance time by less than delay
      vi.advanceTimersByTime(400)
      expect(mockFetch).not.toHaveBeenCalled()

      // Advance time to exceed delay
      vi.advanceTimersByTime(100)
      await nextTick()

      expect(mockFetch).toHaveBeenCalledTimes(1)
    })
  })

  describe('Advanced Search', () => {
    it('should perform successful advanced search', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({
          whiskeys: mockWhiskeyData.map(w => ({
            id: w.id,
            name: w.name_ja,
            distillery: w.distillery_ja,
            region: w.region,
            type: w.type
          }))
        })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      const filters: SearchFilters = {
        name: '響',
        distillery: 'サントリー',
        region: '',
        type: ''
      }

      await composable.performAdvancedSearch(filters)

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search?q=%E9%9F%BF+%E3%82%B5%E3%83%B3%E3%83%88%E3%83%AA%E3%83%BC',
        {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        }
      )

      expect(composable.advancedResults.value).toHaveLength(2)
      expect(composable.isAdvancedSearching.value).toBe(false)
      expect(composable.advancedSearchError.value).toBe('')
    })

    it('should handle empty filters (fetch all)', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [] })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performAdvancedSearch({})

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search?q=',
        expect.any(Object)
      )
    })

    it('should handle advanced search error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Advanced search failed'))

      const filters: SearchFilters = { name: 'test', distillery: '', region: '', type: '' }

      await expect(composable.performAdvancedSearch(filters)).rejects.toThrow('Advanced search failed')

      expect(composable.advancedSearchError.value).toBe('Advanced search failed')
      expect(composable.advancedResults.value).toEqual([])
      expect(composable.isAdvancedSearching.value).toBe(false)
    })

    it('should combine multiple filter terms', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [] })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      const filters: SearchFilters = {
        name: 'whisky',
        distillery: 'macallan',
        region: 'speyside',
        type: 'single malt'
      }

      await composable.performAdvancedSearch(filters)

      // URLSearchParams encodes spaces as + instead of %20
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.whiskeybar.site/api/whiskeys/search?q=whisky+macallan+speyside+single+malt',
        expect.any(Object)
      )
    })
  })

  describe('Search Management', () => {
    it('should clear search state', () => {
      // Set some search state
      composable.searchQuery.value = 'test'
      composable.searchResults.value = mockWhiskeyData
      composable.showSuggestions.value = true
      composable.searchError.value = 'some error'

      composable.clearSearch()

      expect(composable.searchQuery.value).toBe('')
      expect(composable.searchResults.value).toEqual([])
      expect(composable.showSuggestions.value).toBe(false)
      expect(composable.searchError.value).toBe('')
    })

    it('should clear advanced search state', () => {
      // Set some advanced search state
      composable.searchFilters.value = {
        name: 'test',
        distillery: 'test',
        region: 'test',
        type: 'test'
      }
      composable.advancedResults.value = mockWhiskeyData
      composable.advancedSearchError.value = 'some error'

      composable.clearAdvancedSearch()

      expect(composable.searchFilters.value).toEqual({
        name: '',
        distillery: '',
        region: '',
        type: ''
      })
      expect(composable.advancedResults.value).toEqual([])
      expect(composable.advancedSearchError.value).toBe('')
    })

    it('should clear all search state', () => {
      // Set both search states
      composable.searchQuery.value = 'test'
      composable.searchResults.value = mockWhiskeyData
      composable.searchFilters.value = { name: 'test', distillery: '', region: '', type: '' }
      composable.advancedResults.value = mockWhiskeyData

      composable.clearAllSearch()

      expect(composable.searchQuery.value).toBe('')
      expect(composable.searchResults.value).toEqual([])
      expect(composable.searchFilters.value).toEqual({
        name: '',
        distillery: '',
        region: '',
        type: ''
      })
      expect(composable.advancedResults.value).toEqual([])
    })
  })

  describe('Suggestion Selection', () => {
    it('should select suggestion and return formatted data', () => {
      const suggestion = mockWhiskeyData[0]
      const result = composable.selectSuggestion(suggestion)

      expect(composable.searchQuery.value).toBe('響 21年')
      expect(composable.showSuggestions.value).toBe(false)
      expect(result).toEqual({
        name: '響 21年',
        distillery: 'サントリー'
      })
    })

    it('should fallback to English names if Japanese not available', () => {
      const suggestion: WhiskeySuggestion = {
        id: 'test',
        name_ja: '',
        name_en: 'Test Whiskey',
        distillery_ja: '',
        distillery_en: 'Test Distillery',
        region: '',
        type: '',
        description: ''
      }

      const result = composable.selectSuggestion(suggestion)

      expect(composable.searchQuery.value).toBe('Test Whiskey')
      expect(result).toEqual({
        name: 'Test Whiskey',
        distillery: 'Test Distillery'
      })
    })
  })

  describe('UI Control Functions', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should hide suggestions with delay', () => {
      composable.showSuggestions.value = true

      composable.hideSuggestions()

      // Should still be visible immediately
      expect(composable.showSuggestions.value).toBe(true)

      // Should be hidden after delay
      vi.advanceTimersByTime(150)
      expect(composable.showSuggestions.value).toBe(false)
    })

    it('should show suggestions if there are results', () => {
      composable.searchResults.value = mockWhiskeyData
      composable.showSuggestions.value = false

      composable.showSuggestionsIfHasResults()

      expect(composable.showSuggestions.value).toBe(true)
    })

    it('should not show suggestions if no results', () => {
      composable.searchResults.value = []
      composable.showSuggestions.value = false

      composable.showSuggestionsIfHasResults()

      expect(composable.showSuggestions.value).toBe(false)
    })
  })

  describe('Formatting Functions', () => {
    it('should format suggestion display with distillery', () => {
      const suggestion = mockWhiskeyData[0]
      const formatted = composable.formatSuggestionDisplay(suggestion)

      expect(formatted).toBe('響 21年 (サントリー)')
    })

    it('should format suggestion display without distillery if same as name', () => {
      const suggestion: WhiskeySuggestion = {
        ...mockWhiskeyData[0],
        name_ja: 'サントリー',
        distillery_ja: 'サントリー'
      }
      const formatted = composable.formatSuggestionDisplay(suggestion)

      expect(formatted).toBe('サントリー')
    })

    it('should format secondary text with region and type', () => {
      const suggestion = mockWhiskeyData[0]
      const formatted = composable.formatSuggestionSecondaryText(suggestion)

      expect(formatted).toBe('Japan • Blended')
    })

    it('should format secondary text with only region', () => {
      const suggestion: WhiskeySuggestion = {
        ...mockWhiskeyData[0],
        type: ''
      }
      const formatted = composable.formatSuggestionSecondaryText(suggestion)

      expect(formatted).toBe('Japan')
    })

    it('should return empty string for no region or type', () => {
      const suggestion: WhiskeySuggestion = {
        ...mockWhiskeyData[0],
        region: '',
        type: ''
      }
      const formatted = composable.formatSuggestionSecondaryText(suggestion)

      expect(formatted).toBe('')
    })
  })

  describe('Mobile Responsive Features', () => {
    it('should detect desktop as non-mobile', () => {
      // Mock desktop width
      Object.defineProperty(window, 'innerWidth', { value: 1024 })

      expect(composable.isMobile.value).toBe(false)
      expect(composable.suggestionLimit.value).toBe(10)
    })

    it('should detect mobile screen', () => {
      // Mock mobile width
      Object.defineProperty(window, 'innerWidth', { value: 640 })

      const mobileComposable = useWhiskeySearch()
      expect(mobileComposable.suggestionLimit.value).toBe(5)
    })
  })

  describe('Computed Properties', () => {
    it('should track hasResults correctly', () => {
      expect(composable.hasResults.value).toBe(false)

      composable.searchResults.value = mockWhiskeyData
      expect(composable.hasResults.value).toBe(true)

      composable.searchResults.value = []
      expect(composable.hasResults.value).toBe(false)
    })

    it('should track hasAdvancedResults correctly', () => {
      expect(composable.hasAdvancedResults.value).toBe(false)

      composable.advancedResults.value = mockWhiskeyData
      expect(composable.hasAdvancedResults.value).toBe(true)

      composable.advancedResults.value = []
      expect(composable.hasAdvancedResults.value).toBe(false)
    })

    it('should track isAnySearchActive correctly', () => {
      expect(composable.isAnySearchActive.value).toBe(false)

      composable.isSearching.value = true
      expect(composable.isAnySearchActive.value).toBe(true)

      composable.isSearching.value = false
      composable.isAdvancedSearching.value = true
      expect(composable.isAnySearchActive.value).toBe(true)

      composable.isAdvancedSearching.value = false
      expect(composable.isAnySearchActive.value).toBe(false)
    })
  })

  describe('Data Transformation', () => {
    it('should transform API response to WhiskeySuggestion format', async () => {
      const mockApiResponse = {
        id: 'api-whiskey',
        name: 'API Whiskey',
        distillery: 'API Distillery',
        region: 'Scotland',
        type: 'Single Malt'
      }

      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [mockApiResponse] })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('test')

      const result = composable.searchResults.value[0]
      expect(result).toEqual({
        id: 'api-whiskey',
        name_ja: 'API Whiskey',
        name_en: 'API Whiskey',
        distillery_ja: 'API Distillery',
        distillery_en: 'API Distillery',
        region: 'Scotland',
        type: 'Single Malt',
        description: ''
      })
    })

    it('should handle missing fields in API response', async () => {
      const mockApiResponse = {
        id: 'minimal-whiskey',
        name: 'Minimal Whiskey'
        // Missing other fields
      }

      const mockResponse = {
        ok: true,
        json: async () => ({ whiskeys: [mockApiResponse] })
      }
      mockFetch.mockResolvedValueOnce(mockResponse)

      await composable.performIncrementalSearch('test')

      const result = composable.searchResults.value[0]
      expect(result).toEqual({
        id: 'minimal-whiskey',
        name_ja: 'Minimal Whiskey',
        name_en: 'Minimal Whiskey',
        distillery_ja: undefined,
        distillery_en: undefined,
        region: '',
        type: '',
        description: ''
      })
    })
  })
})