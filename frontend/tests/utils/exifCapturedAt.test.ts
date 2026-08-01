import exifr from 'exifr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readExifCapturedAt } from '~/utils/exifCapturedAt'

const parseMock = vi.mocked(exifr.parse)
const file = new File(['image'], 'photo.jpg', { type: 'image/jpeg' })

describe('readExifCapturedAt', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-01T12:30:00Z'))
    parseMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns offset-aware RFC3339 from DateTimeOriginal', async () => {
    parseMock.mockResolvedValue({
      DateTimeOriginal: '2026:08:01 21:30:00',
      OffsetTimeOriginal: '+09:00',
    })

    await expect(readExifCapturedAt(file)).resolves.toBe('2026-08-01T21:30:00+09:00')
    expect(parseMock).toHaveBeenCalledWith(file, expect.objectContaining({
      pick: ['DateTimeOriginal', 'OffsetTimeOriginal', 'CreateDate'],
      reviveValues: false,
    }))
  })

  it('interprets an offset-less timestamp in the browser local timezone', async () => {
    parseMock.mockResolvedValue({ DateTimeOriginal: '2026:07:01 21:30:00' })
    const expectedInstant = new Date(2026, 6, 1, 21, 30, 0).getTime()

    const result = await readExifCapturedAt(file)

    expect(result).toMatch(/^2026-07-01T21:30:00[+-]\d{2}:\d{2}$/)
    expect(Date.parse(result!)).toBe(expectedInstant)
  })

  it('falls back to CreateDate when DateTimeOriginal is absent', async () => {
    parseMock.mockResolvedValue({
      CreateDate: '2026:07:01 10:00:00',
      OffsetTimeOriginal: 'Z',
    })

    await expect(readExifCapturedAt(file)).resolves.toBe('2026-07-01T10:00:00Z')
  })

  it('returns null when capture metadata is absent', async () => {
    parseMock.mockResolvedValue({})

    await expect(readExifCapturedAt(file)).resolves.toBeNull()
  })

  it.each([
    { DateTimeOriginal: 'not-a-date' },
    { DateTimeOriginal: '2026:02:30 10:00:00' },
    { DateTimeOriginal: '2026:07:01 10:00:00', OffsetTimeOriginal: 'UTC+9' },
  ])('returns null for broken EXIF values: %o', async metadata => {
    parseMock.mockResolvedValue(metadata)

    await expect(readExifCapturedAt(file)).resolves.toBeNull()
  })

  it.each([
    { DateTimeOriginal: '1999:12:31 23:59:59', OffsetTimeOriginal: 'Z' },
    { DateTimeOriginal: '2026:08:01 12:36:00', OffsetTimeOriginal: 'Z' },
  ])('returns null for out-of-range capture times: %o', async metadata => {
    parseMock.mockResolvedValue(metadata)

    await expect(readExifCapturedAt(file)).resolves.toBeNull()
  })

  it('returns null instead of throwing when EXIF parsing fails', async () => {
    parseMock.mockRejectedValue(new Error('unsupported image'))

    await expect(readExifCapturedAt(file)).resolves.toBeNull()
  })
})
