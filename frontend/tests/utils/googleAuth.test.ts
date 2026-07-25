import { describe, expect, it } from 'vitest'
import { isGoogleAuthEnabled } from '~/utils/googleAuth'

describe('isGoogleAuthEnabled', () => {
  it.each(['1', 1, 'true', true])('enables Google authentication for %j', (value) => {
    expect(isGoogleAuthEnabled(value)).toBe(true)
  })

  it.each(['0', 0, undefined, '', 'yes', null])('disables Google authentication for %j', (value) => {
    expect(isGoogleAuthEnabled(value)).toBe(false)
  })
})
