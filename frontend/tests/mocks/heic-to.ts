import { vi } from 'vitest'

// heic-to exposes named exports (heicTo/isHeic); the lazy import in imageResize.ts
// only uses heicTo. isHeic is stubbed for completeness.
export const heicTo = vi.fn()
export const isHeic = vi.fn()
