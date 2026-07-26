import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.fn()
vi.mock('~/composables/useApi', () => ({ useApi: () => ({ request }) }))

import { useWhiskeys } from '~/composables/useWhiskeys'

describe('useWhiskeys pagination', () => {
  beforeEach(() => request.mockReset())

  it('appends whiskey pages and tracks next_token', async () => {
    request
      .mockResolvedValueOnce({ whiskeys: [{ id: 'w1' }], count: 1, next_token: 'next-2' })
      .mockResolvedValueOnce({ whiskeys: [{ id: 'w2' }], count: 1, next_token: null })
    const whiskey = useWhiskeys()

    await whiskey.fetchWhiskeyList({ limit: 10 })
    await whiskey.fetchWhiskeyList({ limit: 10, next_token: whiskey.nextToken.value }, true)

    expect(request).toHaveBeenLastCalledWith('/api/whiskeys', {
      auth: 'none',
      query: { limit: 10, next_token: 'next-2' },
    })
    expect(whiskey.whiskeys.value.map(item => item.id)).toEqual(['w1', 'w2'])
    expect(whiskey.nextToken.value).toBeNull()
  })
})
