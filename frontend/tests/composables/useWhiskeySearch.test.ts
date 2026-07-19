import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWhiskeySearch } from '~/composables/useWhiskeySearch'

const request = vi.fn()
vi.mock('~/composables/useApi', () => ({ useApi: () => ({ request }) }))

describe('useWhiskeySearch', () => {
  beforeEach(() => request.mockReset())

  it('searches the public name endpoint without a trailing slash', async () => {
    request.mockResolvedValue({
      whiskeys: [{ id: 'w1', name: '山崎', distillery: '山崎蒸溜所' }],
      count: 1,
      next_token: 'next',
    })
    const search = useWhiskeySearch()

    await search.performIncrementalSearch(' 山崎 ', 10)

    expect(request).toHaveBeenCalledWith('/api/whiskeys/search', {
      auth: 'none',
      query: { q: '山崎', limit: 10 },
    })
    expect(search.searchResults.value[0]).toMatchObject({ id: 'w1', name: '山崎' })
  })

  it('appends a next-token search page', async () => {
    request
      .mockResolvedValueOnce({ whiskeys: [{ id: 'w1', name: 'One' }], count: 1, next_token: 'token-2' })
      .mockResolvedValueOnce({ whiskeys: [{ id: 'w2', name: 'Two' }], count: 1, next_token: null })
    const search = useWhiskeySearch()
    search.searchFilters.value.name = 'malt'

    await search.performAdvancedSearch(search.searchFilters.value)
    await search.loadMoreAdvancedResults()

    expect(request).toHaveBeenLastCalledWith('/api/whiskeys/search', {
      auth: 'none',
      query: { q: 'malt', limit: 20, next_token: 'token-2' },
    })
    expect(search.advancedResults.value.map(item => item.id)).toEqual(['w1', 'w2'])
    expect(search.advancedNextToken.value).toBeNull()
  })

  it('returns the whiskey id when a suggestion is selected', () => {
    const search = useWhiskeySearch()
    expect(search.selectSuggestion({
      id: 'w1',
      name: 'Yamazaki',
      name_ja: '山崎',
      name_en: 'Yamazaki',
      distillery: '山崎蒸溜所',
      region: '',
      type: '',
      description: '',
    })).toEqual({ id: 'w1', name: '山崎', distillery: '山崎蒸溜所' })
  })
})
