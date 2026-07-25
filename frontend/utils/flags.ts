// Nuxt's runtimeConfig coerces string env values ("1") into numbers (1) in the
// built payload, so strict `=== '1'` comparisons silently fail. Accept the
// tolerant truthy set for public boolean flags while staying fail-closed:
// only '1'/1/'true'/true enable a flag; everything else (including '0'/0) is off.
export const isFlagEnabled = (value: unknown): boolean => (
  value === '1'
  || value === 1
  || value === 'true'
  || value === true
)
