import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImageLightbox from '~/components/ImageLightbox.vue'
import type { RecordingSessionItem } from '~/composables/useDrinkLogRecordingSession'
import { buildDrinkLogPayload, type DrinkLogCandidate, type PlaceCandidate } from '~/composables/useDrinkLogs'
import LogsNewPage from '~/pages/logs/new.vue'

const pageMocks = vi.hoisted(() => ({
  analyze: vi.fn(),
  createLog: vi.fn(),
  getUploadUrl: vi.fn(),
  initialItems: [] as unknown[],
  initialPageError: '',
  initialPlaceError: '',
  initialPlaces: [] as unknown[],
  readExifCapturedAt: vi.fn(),
  readExifGps: vi.fn(),
  requestPosition: vi.fn(),
  navigateTo: vi.fn(),
  resizeImage: vi.fn(),
  searchPlaces: vi.fn(),
  uploadToS3: vi.fn(),
  upsertLogs: vi.fn(),
}))

vi.mock('~/composables/useGeolocation', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useGeolocation')>()
  const { ref: vueRef } = await import('vue')
  return {
    ...actual,
    useGeolocation: () => ({
      disclosure: actual.GEOLOCATION_DISCLOSURE,
      requesting: vueRef(false),
      requestPosition: pageMocks.requestPosition,
    }),
  }
})

vi.mock('~/composables/useDrinkLogRecordingSession', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useDrinkLogRecordingSession')>()
  return {
    ...actual,
    useDrinkLogRecordingSession: () => {
      const session = actual.useDrinkLogRecordingSession({
        analyze: pageMocks.analyze,
        createLog: pageMocks.createLog,
        getUploadUrl: pageMocks.getUploadUrl,
        readExifCapturedAt: pageMocks.readExifCapturedAt,
        readExifGps: pageMocks.readExifGps,
        resizeImage: pageMocks.resizeImage,
        searchPlaces: pageMocks.searchPlaces,
        uploadToS3: pageMocks.uploadToS3,
        upsertLogs: pageMocks.upsertLogs,
      })
      session.items.value = pageMocks.initialItems as RecordingSessionItem[]
      session.places.value = pageMocks.initialPlaces as PlaceCandidate[]
      session.pageError.value = pageMocks.initialPageError
      session.placeError.value = pageMocks.initialPlaceError
      return session
    },
  }
})

const batchItem = (candidates: DrinkLogCandidate[] = [], index = 0): RecordingSessionItem => ({
  id: `photo-${index + 1}`,
  file: new File(['photo'], 'photo.jpg', { type: 'image/jpeg' }),
  capturedAt: null,
  phase: 'ready',
  uploadProgress: 100,
  previewUrl: 'blob:preview',
  analysisId: 'analysis-1',
  candidates,
  selectedCandidateIndex: candidates.length === 1 ? 0 : null,
  brandText: candidates.length === 1 ? candidates[0]?.brand_text || '' : '',
  servingStyle: '',
  rating: null,
  storeName: '',
  placeId: '',
  notes: '',
  error: '',
  saveStatus: 'idle',
  saveError: '',
  createdLog: null,
})

const mountLogPage = () => mount(LogsNewPage, {
  global: {
    components: { ImageLightbox },
    stubs: { GoogleAttributions: true, NuxtLink: true },
  },
})

const renderLogPage = (options: {
  pageError?: string
  placeError?: string
  candidates?: DrinkLogCandidate[]
  places?: PlaceCandidate[]
  itemCount?: number
  capturedAt?: string | null
} = {}) => {
  pageMocks.initialItems = Array.from(
    { length: options.itemCount || 1 },
    (_, index) => ({ ...batchItem(options.candidates || [], index), capturedAt: options.capturedAt || null }),
  )
  pageMocks.initialPlaces = options.places || []
  pageMocks.initialPageError = options.pageError || ''
  pageMocks.initialPlaceError = options.placeError || ''
  return mountLogPage()
}

const mountActualLogPage = mountLogPage

const selectFiles = async (wrapper: ReturnType<typeof mountActualLogPage>, files: File[]) => {
  const input = wrapper.get<HTMLInputElement>('#drink-photo')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  input.element.dispatchEvent(new Event('change', { bubbles: true }))
  await flushPromises()
}

describe('logs/new form behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('navigateTo', pageMocks.navigateTo)
    pageMocks.initialItems = []
    pageMocks.initialPlaces = []
    pageMocks.initialPageError = ''
    pageMocks.initialPlaceError = ''
    pageMocks.readExifCapturedAt.mockResolvedValue(null)
    pageMocks.readExifGps.mockResolvedValue(null)
    pageMocks.requestPosition.mockResolvedValue({ lat: 35.0, lng: 139.0 })
    pageMocks.resizeImage.mockResolvedValue({
      blob: new Blob(['jpeg'], { type: 'image/jpeg' }),
      contentType: 'image/jpeg',
    })
    pageMocks.getUploadUrl.mockResolvedValue({
      upload_url: 'https://upload.test',
      fields: {},
      s3_key: 'tmp/user/photo.jpg',
    })
    pageMocks.uploadToS3.mockImplementation(async (_url, _fields, _blob, onProgress) => {
      onProgress?.(100)
    })
    pageMocks.analyze.mockResolvedValue({
      analysis_id: 'analysis-processed',
      candidates: [{ brand_text: 'Mock Brand', confidence: 0.9 }],
      model_id: 'test-model',
      confidence: 0.9,
    })
    pageMocks.createLog.mockResolvedValue({
      id: 'log-1',
      user_id: 'user-1',
      status: 'complete',
      brand_text: 'Mock Brand',
      brand_source: 'ai',
      store: { name: '' },
      datetime: '2026-08-01T00:00:00Z',
    })
    pageMocks.searchPlaces.mockResolvedValue([])
  })

  it('sends candidate_index only when an AI candidate remains selected', () => {
    expect(buildDrinkLogPayload({ analysisId: 'a1', candidateIndex: 0, brandText: 'AI銘柄' })).toEqual({
      analysis_id: 'a1',
      candidate_index: 0,
    })
  })

  it('shows a captured timestamp when EXIF exists and a save-time fallback otherwise', () => {
    expect(renderLogPage({ capturedAt: '2026-07-01T21:30:00+09:00' }).text()).toContain('撮影日時:')
    expect(renderLogPage().text()).toContain('記録日時: 保存時刻')
  })

  it('sends brand_text without candidate_index for manual input', () => {
    const brandText = '手入力銘柄'
    expect(buildDrinkLogPayload({ analysisId: 'a1', candidateIndex: null, brandText })).toEqual({
      analysis_id: 'a1',
      brand_text: brandText,
    })
  })

  it('accepts HEIC and multiple files with the ten-photo guidance', () => {
    const wrapper = renderLogPage()
    const input = wrapper.get('#drink-photo')

    expect(input.attributes('multiple')).toBeDefined()
    expect(input.attributes('accept')).toBe('image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif')
    expect(wrapper.text()).toContain('一度に最大10枚')
  })

  it('shows the shared manual store fallback when location permission is denied', () => {
    const wrapper = renderLogPage({ placeError: '位置情報を取得できませんでした。店名を手入力して記録できます。' })
    expect(wrapper.text()).toContain('店名を手入力して記録できます。')
    expect(wrapper.find('input[id^="store-name-"]').exists()).toBe(true)
  })

  it.each([
    'リクエストが集中しています。しばらく待ってからお試しください。',
    'サービスを一時的に利用できません。しばらく待ってからお試しください。',
  ])('shows normalized API errors without hiding the editable card', message => {
    const wrapper = renderLogPage({ pageError: message })
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    expect(wrapper.find('input[id^="brand-text-"]').exists()).toBe(true)
  })

  it('shows no candidate control and asks for manual brand input when analysis returns no candidates', () => {
    const wrapper = renderLogPage({ candidates: [] })
    expect(wrapper.text()).toContain('銘柄候補を特定できませんでした。')
    expect(wrapper.get('input[id^="brand-text-"]').attributes('required')).toBeDefined()
    expect(wrapper.find('select[id^="brand-candidate-"]').exists()).toBe(false)
  })

  it('shows one detected brand in the text field without rendering a candidate select', () => {
    const wrapper = renderLogPage({
      candidates: [{ brand_text: 'カリラ 12年', confidence: 0.904, match_source: 'catalog' }],
    })

    expect(wrapper.find('select[id^="brand-candidate-"]').exists()).toBe(false)
    expect(wrapper.get<HTMLInputElement>('input[id^="brand-text-"]').element.value).toBe('カリラ 12年')
    expect(wrapper.text()).toContain('AIの読み取り: カリラ 12年（確度 90%・カタログ一致）')
  })

  it('renders multiple candidates as chips and clears the selection when the brand is edited', async () => {
    const wrapper = renderLogPage({
      candidates: [
        { brand_text: 'カリラ 12年', confidence: 0.9, match_source: 'catalog' },
        { brand_text: '山崎', confidence: 0.8, match_source: 'ai' },
      ],
    })

    const chips = wrapper.findAll('button[aria-pressed]')
    expect(chips).toHaveLength(2)
    expect(chips[0]!.text()).toBe('カリラ 12年（90%）')
    expect(chips[1]!.text()).toBe('山崎（80%）')
    expect(wrapper.text()).toContain('複数のボトルを検出しました。')

    const secondChip = chips[1]!
    const secondChipElement = secondChip.element as HTMLButtonElement
    secondChipElement.click()
    await wrapper.vm.$nextTick()
    const brandInput = wrapper.get<HTMLInputElement>('input[id^="brand-text-"]')
    expect(brandInput.element.value).toBe('山崎')
    expect(secondChip.attributes('aria-pressed')).toBe('true')

    brandInput.element.value = '山崎を手入力で修正'
    brandInput.element.dispatchEvent(new Event('input', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(secondChip.attributes('aria-pressed')).toBe('false')
  })

  it('shows AI-read matching text for a single non-catalog candidate', () => {
    const wrapper = renderLogPage({
      candidates: [{ brand_text: '山崎', confidence: 0.8, match_source: 'ai' }],
    })

    expect(wrapper.text()).toContain('AIの読み取り: 山崎（確度 80%・AI読取）')
  })

  it('updates the store selection and manual store name on each card', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
      { place_id: 'place-2', display_name: '候補店B', formatted_address: '東京都B', attributions: [] },
    ]
    const wrapper = renderLogPage({ places })

    const placeSelect = wrapper.get<HTMLSelectElement>('#place-photo-1')
    placeSelect.element.value = 'place-2'
    placeSelect.element.dispatchEvent(new Event('change', { bubbles: true }))
    const storeInput = wrapper.get<HTMLInputElement>('#store-name-photo-1')
    storeInput.element.value = '記録用の店名'
    storeInput.element.dispatchEvent(new Event('input', { bubbles: true }))
    await wrapper.vm.$nextTick()

    const item = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items[0]!
    expect(item.placeId).toBe('place-2')
    expect(item.storeName).toBe('記録用の店名')
  })

  it('applies a nearby-place candidate to every unsaved card', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })

    wrapper.findAll('button').find(button => button.text().includes('候補店A'))!.element.click()
    await wrapper.vm.$nextTick()

    const items = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items
    expect(items.map(item => item.placeId)).toEqual(['place-1', 'place-1'])
  })

  it('clears every unsaved place id when the selected candidate is clicked again', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const candidateButton = wrapper.findAll('button').find(button => button.text().includes('候補店A'))!
    const items = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items

    candidateButton.element.click()
    await wrapper.vm.$nextTick()
    // Assert the selection landed first: '' is also the initial value, so without
    // this an inert button would satisfy the final assertion.
    expect(items.map(item => item.placeId)).toEqual(['place-1', 'place-1'])

    candidateButton.element.click()
    await wrapper.vm.$nextTick()

    expect(items.map(item => item.placeId)).toEqual(['', ''])
  })

  it('keeps the Google attributions outside the candidate button', () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places })

    // GoogleAttributions renders links, so nesting it inside the button would be
    // invalid interactive markup.
    expect(wrapper.find('button google-attributions-stub').exists()).toBe(false)
    expect(wrapper.find('google-attributions-stub').exists()).toBe(true)
  })

  it('exposes the shared candidate selection through aria-pressed', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
      { place_id: 'place-2', display_name: '候補店B', formatted_address: '東京都B', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const placeButtons = wrapper.findAll('button').filter(button => button.text().includes('候補店'))

    expect(placeButtons.map(button => button.attributes('aria-pressed'))).toEqual(['false', 'false'])
    placeButtons[0]!.element.click()
    await wrapper.vm.$nextTick()

    expect(placeButtons.map(button => button.attributes('aria-pressed'))).toEqual(['true', 'false'])
  })

  it('marks the selected candidate without relying on colour alone', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
      { place_id: 'place-2', display_name: '候補店B', formatted_address: '東京都B', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const placeButtons = wrapper.findAll('button').filter(button => button.text().includes('候補店'))

    expect(placeButtons.filter(button => button.text().includes('選択中'))).toHaveLength(0)
    placeButtons[0]!.element.click()
    await wrapper.vm.$nextTick()

    // Dark-mode extensions flatten the selected background, so the state has to be
    // readable from the text/mark rather than the colour.
    expect(placeButtons[0]!.text()).toContain('選択中')
    expect(placeButtons[0]!.text()).toContain('✓')
    expect(placeButtons[1]!.text()).not.toContain('選択中')
  })

  it('does not change a saved card when a nearby-place candidate is clicked', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-new', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const items = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items
    Object.assign(items[1]!, { placeId: 'place-saved', saveStatus: 'saved' })

    wrapper.findAll('button').find(button => button.text().includes('候補店A'))!.element.click()
    await wrapper.vm.$nextTick()

    expect(items[0]!.placeId).toBe('place-new')
    expect(items[1]!.placeId).toBe('place-saved')
  })

  it('never copies a Google display name into the manual store name', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: 'Googleの候補店名', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const items = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items
    items[0]!.storeName = 'ユーザー入力の店名'

    wrapper.findAll('button').find(button => button.text().includes('Googleの候補店名'))!.element.click()
    await wrapper.vm.$nextTick()

    expect(items.map(item => item.storeName)).toEqual(['ユーザー入力の店名', ''])
  })

  it('copies the first card store fields to the other unsaved cards', async () => {
    const places: PlaceCandidate[] = [
      { place_id: 'place-1', display_name: '候補店A', formatted_address: '東京都A', attributions: [] },
    ]
    const wrapper = renderLogPage({ places, itemCount: 2 })
    const placeSelect = wrapper.get<HTMLSelectElement>('#place-photo-1')
    placeSelect.element.value = 'place-1'
    placeSelect.element.dispatchEvent(new Event('change', { bubbles: true }))
    const storeInput = wrapper.get<HTMLInputElement>('#store-name-photo-1')
    storeInput.element.value = '一杯目の店'
    storeInput.element.dispatchEvent(new Event('input', { bubbles: true }))
    await wrapper.vm.$nextTick()

    wrapper.findAll('button').find(button => button.text() === '最初の一杯の店を全カードに適用')!.element.click()
    await wrapper.vm.$nextTick()

    const items = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items
    expect(items[1]).toEqual(expect.objectContaining({ placeId: 'place-1', storeName: '一杯目の店' }))
  })

  it('opens the selected confirmation-card preview in the lightbox', async () => {
    const wrapper = renderLogPage()

    wrapper.get<HTMLButtonElement>('button[aria-label="写真を拡大表示"]').element.click()
    await wrapper.vm.$nextTick()

    const dialog = wrapper.get('[role="dialog"]')
    const image = dialog.get('img')
    expect(image.attributes('src')).toBe('blob:preview')
    expect(image.attributes('alt')).toBe('1杯目のテイスティング写真')
    wrapper.unmount()
  })

  it('automatically searches Places with the first photo that has EXIF GPS', async () => {
    const files = [
      new File(['first'], 'without-gps.jpg', { type: 'image/jpeg' }),
      new File(['second'], 'with-gps.heic', { type: 'image/heic' }),
      new File(['third'], 'unused.jpg', { type: 'image/jpeg' }),
    ]
    pageMocks.readExifGps
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ lat: 35.681236, lng: 139.767125 })
    const wrapper = mountActualLogPage()

    await selectFiles(wrapper, files)

    expect(pageMocks.readExifGps).toHaveBeenCalledTimes(2)
    expect(pageMocks.readExifGps).toHaveBeenNthCalledWith(1, files[0])
    expect(pageMocks.readExifGps).toHaveBeenNthCalledWith(2, files[1])
    expect(pageMocks.searchPlaces).toHaveBeenCalledOnce()
    expect(pageMocks.searchPlaces).toHaveBeenCalledWith(35.681236, 139.767125)
    expect(wrapper.text()).toContain('写真の位置情報から近くの店を検索しました。')
    wrapper.unmount()
  })

  it('keeps the device-location button as the fallback when photos have no GPS', async () => {
    const files = [new File(['photo'], 'without-gps.webp', { type: 'image/webp' })]
    const wrapper = mountActualLogPage()

    await selectFiles(wrapper, files)
    expect(pageMocks.searchPlaces).not.toHaveBeenCalled()

    const nearbyButton = wrapper.findAll('button').find(button => button.text() === '近くの店を探す')
    expect(nearbyButton).toBeDefined()
    nearbyButton!.element.click()
    await flushPromises()

    expect(pageMocks.requestPosition).toHaveBeenCalledOnce()
    expect(pageMocks.searchPlaces).toHaveBeenCalledWith(35.0, 139.0)
    wrapper.unmount()
  })

  it('does not pass EXIF coordinates into the save pipeline', async () => {
    const file = new File(['photo'], 'with-gps.jpg', { type: 'image/jpeg' })
    pageMocks.readExifGps.mockResolvedValue({ lat: 35.681236, lng: 139.767125 })
    const wrapper = mountActualLogPage()

    await selectFiles(wrapper, [file])
    wrapper.get('form').element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    expect(pageMocks.searchPlaces).toHaveBeenCalledWith(35.681236, 139.767125)
    expect(pageMocks.createLog).toHaveBeenCalledOnce()
    expect(pageMocks.createLog.mock.calls.flat()).not.toContain(35.681236)
    expect(pageMocks.createLog.mock.calls.flat()).not.toContain(139.767125)
    const item = (wrapper.vm as unknown as { items: ReturnType<typeof batchItem>[] }).items[0]!
    expect(item.storeName).toBe('')
    expect(item.placeId).toBe('')
    expect(item.storeName).not.toContain('35.681236')
    expect(item.placeId).not.toContain('139.767125')
    wrapper.unmount()
  })
})
