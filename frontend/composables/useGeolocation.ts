import { ref } from 'vue'
import type { Coordinates } from '~/utils/exifLocation'

export const GEOLOCATION_DISCLOSURE = '写真の位置情報（EXIF）またはお使いの端末の現在地をサーバー経由で Google Places に送信し、近くの店候補の検索だけに使用します。座標は保存しません。位置情報を使わず、店名を手入力して登録することもできます。'

export const useGeolocation = () => {
  const requesting = ref(false)

  const requestPosition = async (): Promise<Coordinates | null> => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return null

    requesting.value = true
    try {
      return await new Promise(resolve => {
        navigator.geolocation.getCurrentPosition(
          position => resolve({ lat: position.coords.latitude, lng: position.coords.longitude }),
          () => resolve(null),
          { enableHighAccuracy: false, timeout: 10_000, maximumAge: 0 },
        )
      })
    } catch {
      return null
    } finally {
      requesting.value = false
    }
  }

  return { disclosure: GEOLOCATION_DISCLOSURE, requesting, requestPosition }
}
