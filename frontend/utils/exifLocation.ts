export interface Coordinates {
  lat: number
  lng: number
}

/** 元ファイルの EXIF から GPS を読む。無い/失敗時は null。座標は保存しないこと。 */
export const readExifGps = async (file: File): Promise<Coordinates | null> => {
  try {
    const exifr = (await import('exifr')).default
    const gps = await exifr.gps(file)
    const latitude = gps?.latitude
    const longitude = gps?.longitude

    if (
      typeof latitude !== 'number'
      || typeof longitude !== 'number'
      || !Number.isFinite(latitude)
      || !Number.isFinite(longitude)
      || latitude < -90
      || latitude > 90
      || longitude < -180
      || longitude > 180
    ) {
      return null
    }

    return { lat: latitude, lng: longitude }
  } catch {
    return null
  }
}
