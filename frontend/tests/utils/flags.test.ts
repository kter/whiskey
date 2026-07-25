import { describe, expect, it } from 'vitest'
import { isFlagEnabled } from '~/utils/flags'

describe('isFlagEnabled', () => {
  // Nuxt runtimeConfig coerces "1" env values into the number 1, so both must enable.
  it.each([['1'], [1], ['true'], [true]])('treats %o as enabled', (value) => {
    expect(isFlagEnabled(value)).toBe(true)
  })

  it.each([['0'], [0], [''], ['false'], [false], [undefined], [null], ['yes']])(
    'treats %o as disabled (fail-closed)',
    (value) => {
      expect(isFlagEnabled(value)).toBe(false)
    },
  )
})
