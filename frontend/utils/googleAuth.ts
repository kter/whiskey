export const isGoogleAuthEnabled = (value: unknown): boolean => (
  value === '1'
  || value === 1
  || value === 'true'
  || value === true
)
