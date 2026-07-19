import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.fn()
vi.mock('~/composables/useApi', () => ({ useApi: () => ({ request }) }))

import { useWhiskeys } from '~/composables/useWhiskeys'

describe('useWhiskeys pagination', () => {
  beforeEach(() => request.mockReset())

  it('appends review pages and tracks next_token', async () => {
    request
      .mockResolvedValueOnce({ results: [{ id: 'r1' }], count: 1, next_token: 'next-2' })
      .mockResolvedValueOnce({ results: [{ id: 'r2' }], count: 1, next_token: null })
    const whiskey = useWhiskeys()

    await whiskey.fetchReviews({ limit: 10 })
    await whiskey.fetchReviews({ limit: 10, next_token: whiskey.nextToken.value }, true)

    expect(request).toHaveBeenLastCalledWith('/api/reviews', {
      auth: 'required',
      query: { limit: 10, next_token: 'next-2' },
    })
    expect(whiskey.reviews.value.map(review => review.id)).toEqual(['r1', 'r2'])
    expect(whiskey.nextToken.value).toBeNull()
  })

  it('uses the separated public endpoint without authentication', async () => {
    request.mockResolvedValue({ results: [], count: 0, next_token: null })
    await useWhiskeys().fetchPublicReviews({ limit: 5 })
    expect(request).toHaveBeenCalledWith('/api/reviews/public', {
      auth: 'none',
      query: { limit: 5, next_token: undefined },
    })
  })
})
