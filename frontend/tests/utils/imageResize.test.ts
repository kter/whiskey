import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { heicTo } from 'heic-to'
import { resizeImage } from '~/utils/imageResize'

let sourceWidth = 3200
let sourceHeight = 1600
let encodedSizes: number[] = []
let failedImageLoads = 0
let canvas: HTMLCanvasElement
const qualities: number[] = []
const drawImage = vi.fn()
const heicToMock = vi.mocked(heicTo)

class MockImage {
  naturalWidth = sourceWidth
  naturalHeight = sourceHeight
  width = sourceWidth
  height = sourceHeight
  onload: null | (() => void) = null
  onerror: null | (() => void) = null

  set src(_value: string) {
    if (failedImageLoads > 0) {
      failedImageLoads -= 1
      this.onerror?.()
    } else {
      this.onload?.()
    }
  }
}

describe('resizeImage', () => {
  beforeEach(() => {
    sourceWidth = 3200
    sourceHeight = 1600
    encodedSizes = [100]
    failedImageLoads = 0
    qualities.length = 0
    drawImage.mockReset()
    heicToMock.mockReset()
    vi.stubGlobal('Image', MockImage)
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })

    const createElement = document.createElement.bind(document)
    canvas = createElement('canvas')
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => {
      if (tagName !== 'canvas') return createElement(tagName)
      return canvas
    }) as typeof document.createElement)
    Object.defineProperty(canvas, 'getContext', {
      configurable: true,
      value: vi.fn(() => ({ clearRect: vi.fn(), drawImage })),
    })
    Object.defineProperty(canvas, 'toBlob', {
      configurable: true,
      value: vi.fn((callback: BlobCallback, type?: string, quality?: number) => {
        qualities.push(Number(quality))
        const blob = new Blob(['encoded'], { type })
        Object.defineProperty(blob, 'size', { value: encodedSizes.shift() ?? 100 })
        callback(blob)
      }),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each([
    ['photo.heic', ''],
    ['photo.jpg', 'image/heif'],
  ])('uses the lazy HEIC converter after native decoding fails (%s, %s)', async (name, type) => {
    failedImageLoads = 1
    const converted = new Blob(['jpeg'], { type: 'image/jpeg' })
    heicToMock.mockResolvedValue(converted)
    const file = new File(['image'], name, { type })

    const result = await resizeImage(file)

    expect(heicToMock).toHaveBeenCalledWith({ blob: file, type: 'image/jpeg', quality: 0.92 })
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2)
    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.blob.type).toBe('image/jpeg')
    expect(result.contentType).toBe('image/jpeg')
  })

  it('uses native decoding for HEIC when the browser supports it', async () => {
    await resizeImage(new File(['image'], 'native.heic', { type: 'image/heic' }))

    expect(heicToMock).not.toHaveBeenCalled()
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('does not load the HEIC converter when a non-HEIC image cannot be decoded', async () => {
    failedImageLoads = 1

    await expect(resizeImage(new File(['image'], 'broken.jpg', { type: 'image/jpeg' })))
      .rejects.toThrow('画像を読み込めませんでした。')
    expect(heicToMock).not.toHaveBeenCalled()
  })

  it('returns a clear error when HEIC conversion fails', async () => {
    failedImageLoads = 1
    heicToMock.mockRejectedValue(new Error('decode failed'))

    await expect(resizeImage(new File(['image'], 'broken.heic', { type: 'image/heic' })))
      .rejects.toThrow('HEIC画像を変換できませんでした。JPEGで撮り直してください。')
  })

  it('reduces quality and dimensions in stages when the encoded image remains large', async () => {
    encodedSizes = [4_000_000, 4_000_000, 4_000_000, 4_000_000, 4_000_000, 3_000_000]

    const result = await resizeImage(new File(['image'], 'large.png', { type: 'image/png' }))

    expect(qualities).toEqual([0.85, 0.7, 0.55, 0.7, 0.55, 0.55])
    expect(canvas.width).toBe(1024)
    expect(canvas.height).toBe(512)
    expect(result).toEqual(expect.objectContaining({ contentType: 'image/jpeg' }))
  })

  it('limits the longest edge to 1600px without changing the aspect ratio', async () => {
    sourceWidth = 1200
    sourceHeight = 2400

    await resizeImage(new File(['image'], 'portrait.webp', { type: 'image/webp' }))

    expect(canvas.width).toBe(800)
    expect(canvas.height).toBe(1600)
    expect(drawImage).toHaveBeenCalledWith(expect.any(MockImage), 0, 0, 800, 1600)
  })
})
