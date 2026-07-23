import exifr from 'exifr'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readExifGps } from '~/utils/exifLocation'

const gpsMock = vi.mocked(exifr.gps)
const file = new File(['image'], 'photo.heic', { type: 'image/heic' })

describe('readExifGps', () => {
  beforeEach(() => {
    gpsMock.mockReset()
  })

  it('normalizes valid EXIF GPS coordinates', async () => {
    gpsMock.mockResolvedValue({ latitude: 35.681236, longitude: 139.767125 })

    await expect(readExifGps(file)).resolves.toEqual({ lat: 35.681236, lng: 139.767125 })
    expect(gpsMock).toHaveBeenCalledWith(file)
  })

  it('returns null when GPS metadata is absent', async () => {
    // exifr's runtime returns undefined when GPS is absent, although its bundled
    // declaration currently narrows gps() to GpsOutput.
    gpsMock.mockResolvedValue(undefined as never)

    await expect(readExifGps(file)).resolves.toBeNull()
  })

  it.each([
    { latitude: 91, longitude: 139 },
    { latitude: 35, longitude: -181 },
    { latitude: Number.NaN, longitude: 139 },
    { latitude: 35, longitude: Number.POSITIVE_INFINITY },
  ])('returns null for invalid coordinates: %o', async gps => {
    gpsMock.mockResolvedValue(gps)

    await expect(readExifGps(file)).resolves.toBeNull()
  })

  it('returns null instead of throwing when EXIF parsing fails', async () => {
    gpsMock.mockRejectedValue(new Error('unsupported image'))

    await expect(readExifGps(file)).resolves.toBeNull()
  })
})
