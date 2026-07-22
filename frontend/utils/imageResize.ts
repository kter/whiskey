const HEIC_MIME_TYPES = new Set(['image/heic', 'image/heif'])
const HEIC_EXTENSION_PATTERN = /\.(?:heic|heif)$/i
const OUTPUT_CONTENT_TYPE = 'image/jpeg'
const MAX_OUTPUT_SIZE = 3_670_016

const resizeAttempts = [
  { maxDimension: 1600, quality: 0.85 },
  { maxDimension: 1600, quality: 0.7 },
  { maxDimension: 1600, quality: 0.55 },
  { maxDimension: 1280, quality: 0.7 },
  { maxDimension: 1280, quality: 0.55 },
  { maxDimension: 1024, quality: 0.55 },
] as const

export class ImageTooLargeError extends Error {
  constructor() {
    super('画像を3.5MB以下に縮小できませんでした。')
    this.name = 'ImageTooLargeError'
  }
}

const loadImage = (blob: Blob): Promise<HTMLImageElement> => new Promise((resolve, reject) => {
  const objectUrl = URL.createObjectURL(blob)
  const image = new Image()
  image.onload = () => {
    URL.revokeObjectURL(objectUrl)
    resolve(image)
  }
  image.onerror = () => {
    URL.revokeObjectURL(objectUrl)
    reject(new Error('画像を読み込めませんでした。'))
  }
  image.src = objectUrl
})

const dimensionsWithin = (width: number, height: number, maxDimension: number) => {
  const scale = Math.min(1, maxDimension / Math.max(width, height))
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

const canvasToBlob = (canvas: HTMLCanvasElement, quality: number): Promise<Blob> => new Promise((resolve, reject) => {
  canvas.toBlob(blob => {
    if (blob) resolve(blob)
    else reject(new Error('画像の変換に失敗しました。'))
  }, OUTPUT_CONTENT_TYPE, quality)
})

/** Remove metadata and resize an image to a bounded JPEG suitable for Drink Logs. */
export const resizeImage = async (file: File): Promise<{ blob: Blob, contentType: string }> => {
  const isHeic = HEIC_MIME_TYPES.has(file.type.toLowerCase()) || HEIC_EXTENSION_PATTERN.test(file.name)
  let image: HTMLImageElement

  try {
    image = await loadImage(file)
  } catch (nativeDecodeError) {
    if (!isHeic) throw nativeDecodeError

    try {
      // A future CSP must add 'wasm-unsafe-eval' to script-src for this lazy HEIC decoder.
      const { default: heic2any } = await import('heic2any')
      const converted = await heic2any({ blob: file, toType: OUTPUT_CONTENT_TYPE, quality: 0.92 })
      const jpegBlob = Array.isArray(converted) ? converted[0] : converted
      if (!jpegBlob) throw new Error('HEIC変換結果が空です。')
      image = await loadImage(jpegBlob)
    } catch (conversionError) {
      // Keep the underlying cause in the console to aid real-device field diagnostics.
      console.warn('HEIC conversion failed', conversionError)
      throw new Error('HEIC画像を変換できませんでした。JPEGで撮り直してください。')
    }
  }

  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')
  if (!context) throw new Error('画像処理を開始できませんでした。')

  for (const attempt of resizeAttempts) {
    const { width, height } = dimensionsWithin(image.naturalWidth || image.width, image.naturalHeight || image.height, attempt.maxDimension)
    canvas.width = width
    canvas.height = height
    context.clearRect(0, 0, width, height)
    context.drawImage(image, 0, 0, width, height)

    const blob = await canvasToBlob(canvas, attempt.quality)
    if (blob.size <= MAX_OUTPUT_SIZE) return { blob, contentType: OUTPUT_CONTENT_TYPE }
  }

  throw new ImageTooLargeError()
}
