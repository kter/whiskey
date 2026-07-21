import { describe, expect, it, vi } from 'vitest'
import { GEOLOCATION_DISCLOSURE, useGeolocation } from '~/composables/useGeolocation'

describe('useGeolocation', () => {
  it('provides the disclosure before requesting location and resolves coordinates after an explicit call', async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => success({
      coords: { latitude: 35.6812, longitude: 139.7671 },
    } as GeolocationPosition))
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition } })

    const geolocation = useGeolocation()
    expect(geolocation.disclosure).toBe(GEOLOCATION_DISCLOSURE)
    expect(geolocation.disclosure).toContain('Google Places')
    expect(geolocation.disclosure).toContain('保存しません')
    expect(getCurrentPosition).not.toHaveBeenCalled()

    await expect(geolocation.requestPosition()).resolves.toEqual({ lat: 35.6812, lng: 139.7671 })
    expect(getCurrentPosition).toHaveBeenCalledWith(expect.any(Function), expect.any(Function), {
      enableHighAccuracy: false,
      timeout: 10_000,
      maximumAge: 0,
    })
  })

  it('returns null when permission is denied', async () => {
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: (_success: PositionCallback, error: PositionErrorCallback) => error({
          code: 1,
          message: 'denied',
          PERMISSION_DENIED: 1,
          POSITION_UNAVAILABLE: 2,
          TIMEOUT: 3,
        }),
      },
    })

    await expect(useGeolocation().requestPosition()).resolves.toBeNull()
  })
})

