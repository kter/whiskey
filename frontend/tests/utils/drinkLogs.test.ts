import { describe, expect, it } from 'vitest'
import { candidateNeedsConfirmation, servingStyleLabel } from '~/utils/drinkLogs'

describe('candidateNeedsConfirmation', () => {
  it('requires confirmation for unmatched or low-confidence candidates', () => {
    expect(candidateNeedsConfirmation({ confidence: 0.9 })).toBe(true)
    expect(candidateNeedsConfirmation({ brand_key: 'laphroaig', confidence: 0.69 })).toBe(true)
    expect(candidateNeedsConfirmation({ brand_key: 'laphroaig', confidence: 0.7 })).toBe(false)
    expect(candidateNeedsConfirmation({ whiskey_id: 'w1', confidence: 0.9 })).toBe(false)
  })

  it('labels an unknown serving style as unset', () => {
    expect(servingStyleLabel('UNKNOWN')).toBe('未設定')
  })
})
