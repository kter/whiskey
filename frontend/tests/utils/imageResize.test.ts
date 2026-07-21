import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HeicUnsupportedError, resizeImage } from '~/utils/imageResize'

let sourceWidth = 3200
let sourceHeight = 1600
let encodedSizes: number[] = []
let canvas: HTMLCanvasElement
const qualities: number[] = []
const drawImage = vi.fn()

class MockImage {
  naturalWidth = sourceWidth
  naturalHeight = sourceHeight
  width = sourceWidth
  height = sourceHeight
  onload: null | (() => void) = null
  onerror: null | (() => void) = null

  set src(_value: string) {
    this.onload?.()
  }
}

describe('resizeImage', () => {
  beforeEach(() => {
    sourceWidth = 3200
    sourceHeight = 1600
    encodedSizes = [100]
    qualities.length = 0
    drawImage.mockReset()
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
        const size = encodedSizes.shift() ?? 100
        callback({ size, type } as Blob)
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
  ])('rejects HEIC/HEIF before decoding (%s, %s)', async (name, type) => {
    const file = new File(['image'], name, { type })
    await expect(resizeImage(file)).rejects.toBeInstanceOf(HeicUnsupportedError)
    expect(URL.createObjectURL).not.toHaveBeenCalled()
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
