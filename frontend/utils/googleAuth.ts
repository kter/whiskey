import { isFlagEnabled } from './flags'

// Google auth is a public boolean flag subject to the same runtimeConfig
// number-coercion issue, so it reuses the shared tolerant helper.
export const isGoogleAuthEnabled = (value: unknown): boolean => isFlagEnabled(value)
