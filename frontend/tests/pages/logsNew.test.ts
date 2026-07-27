import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, defineComponent, reactive, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImageLightbox from '~/components/ImageLightbox.vue'
import { buildDrinkLogPayload, candidateIndexAfterBrandEdit } from '~/composables/useDrinkLogs'
import LogsNewPage from '~/pages/logs/new.vue'
import { SERVING_STYLES } from '~/types/whiskey'

const pageMocks = vi.hoisted(() => ({
  processFiles: vi.fn(),
  readExifGps: vi.fn(),
  requestPosition: vi.fn(),
  savePending: vi.fn(),
  searchPlaces: vi.fn(),
  upsertLogs: vi.fn(),
}))

vi.mock('~/utils/exifLocation', () => ({
  readExifGps: pageMocks.readExifGps,
}))

vi.mock('~/composables/useDrinkLogs', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useDrinkLogs')>()
  return {
    ...actual,
    useDrinkLogs: () => ({
      searchPlaces: pageMocks.searchPlaces,
      upsertLogs: pageMocks.upsertLogs,
    }),
  }
})

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

vi.mock('~/composables/useDrinkLogBatch', async importOriginal => {
  const actual = await importOriginal<typeof import('~/composables/useDrinkLogBatch')>()
  const { computed: vueComputed, ref: vueRef } = await import('vue')

  return {
    ...actual,
    useDrinkLogBatch: () => {
      const items = vueRef<ReturnType<typeof batchItem>[]>([])
      const processFiles = async (files: File[]) => {
        pageMocks.processFiles(files)
        items.value = files.slice(0, actual.MAX_DRINK_LOG_BATCH_SIZE).map(file => ({
          ...batchItem(),
          id: `processed-${file.name}`,
          file,
          brandText: 'Mock Brand',
        }))
        return { accepted: items.value.length, rejected: Math.max(0, files.length - items.value.length) }
      }

      return {
        items,
        isProcessing: vueComputed(() => false),
        isSaving: vueComputed(() => false),
        allSaved: vueComputed(() => false),
        processFiles,
        retryProcessing: vi.fn(),
        savePending: pageMocks.savePending,
        retrySave: vi.fn(),
        reset: () => {
          items.value = []
        },
      }
    },
  }
})

const source = readFileSync(resolve(process.cwd(), 'pages/logs/new.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1]
if (!template) throw new Error('logs/new.vue template not found')

const batchItem = (candidates: unknown[] = []) => ({
  id: 'photo-1',
  file: new File(['photo'], 'photo.jpg', { type: 'image/jpeg' }),
  phase: 'ready',
  uploadProgress: 100,
  previewUrl: 'blob:preview',
  analysisId: 'analysis-1',
  candidates,
  candidateSelection: '',
  selectedCandidateIndex: null,
  brandText: '',
  servingStyle: '',
  rating: null,
  notes: '',
  error: '',
  saveStatus: 'idle',
  saveError: '',
  createdLog: null,
})

const renderLogPage = (options: { pageError?: string, placeError?: string, candidates?: unknown[] } = {}) => mount(defineComponent({
  setup: () => {
    const lightbox = reactive({ open: false, src: '', alt: '' })
    return {
      items: ref([batchItem(options.candidates || [])]),
      places: ref([]),
      selectedPlaceId: ref(''),
      selectedPlace: computed(() => null),
      storeName: ref(''),
      pageError: ref(options.pageError || ''),
      selectionNotice: ref(''),
      placeError: ref(options.placeError || ''),
      placeNotice: ref(''),
      lightbox,
      requestingLocation: ref(false),
      disclosure: '座標は Google Places に送信し、保存しません。',
      isProcessing: computed(() => false),
      isSaving: computed(() => false),
      canSave: computed(() => false),
      SERVING_STYLES,
      styleLabels: { NEAT: 'ストレート', ROCKS: 'ロック', WATER: '水割り', SODA: 'ハイボール', COCKTAIL: 'カクテル' },
      processingLabels: { queued: '処理中', resizing: '処理中', uploading: '処理中', analyzing: '処理中', ready: '解析完了', failed: '失敗' },
      handleFileSelection: vi.fn(),
      handleSubmit: vi.fn(),
      handleCandidateSelection: vi.fn(),
      handleBrandInput: vi.fn(),
      findNearbyPlaces: vi.fn(),
      handleProcessingRetry: vi.fn(),
      handleSaveRetry: vi.fn(),
      openLightbox: (src: string, alt: string) => {
        lightbox.src = src
        lightbox.alt = alt
        lightbox.open = true
      },
    }
  },
  template,
}), {
  global: {
    components: { ImageLightbox },
    stubs: { GoogleAttributions: true, NuxtLink: true },
  },
})

const mountActualLogPage = () => mount(LogsNewPage, {
  global: {
    components: { ImageLightbox },
    stubs: { GoogleAttributions: true, NuxtLink: true },
  },
})

const selectFiles = async (wrapper: ReturnType<typeof mountActualLogPage>, files: File[]) => {
  const input = wrapper.get<HTMLInputElement>('#drink-photo')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  input.element.dispatchEvent(new Event('change', { bubbles: true }))
  await flushPromises()
}

describe('logs/new form behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pageMocks.readExifGps.mockResolvedValue(null)
    pageMocks.requestPosition.mockResolvedValue({ lat: 35.0, lng: 139.0 })
    pageMocks.savePending.mockResolvedValue([])
    pageMocks.searchPlaces.mockResolvedValue([])
  })

  it('sends candidate_index only when an AI candidate remains selected', () => {
    expect(buildDrinkLogPayload({ analysisId: 'a1', candidateIndex: 0, brandText: 'AI銘柄' })).toEqual({
      analysis_id: 'a1',
      candidate_index: 0,
    })
  })

  it('sends brand_text without candidate_index for manual input', () => {
    const brandText = '手入力銘柄'
    expect(buildDrinkLogPayload({ analysisId: 'a1', candidateIndex: null, brandText })).toEqual({
      analysis_id: 'a1',
      brand_text: brandText,
    })
  })

  it('discards candidate_index and sends brand_text when a candidate is edited', () => {
    const candidates = [{ brand_text: 'AI候補', confidence: 0.9 }]
    const editedBrand = 'AI候補を編集'
    const candidateIndex = candidateIndexAfterBrandEdit(candidates, 0, editedBrand)

    expect(candidateIndex).toBeNull()
    expect(buildDrinkLogPayload({ analysisId: 'a1', candidateIndex, brandText: editedBrand })).toEqual({
      analysis_id: 'a1',
      brand_text: editedBrand,
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
    expect(wrapper.find('#store-name').exists()).toBe(true)
  })

  it.each([
    'リクエストが集中しています。しばらく待ってからお試しください。',
    'サービスを一時的に利用できません。しばらく待ってからお試しください。',
  ])('shows normalized API errors without hiding the editable card', message => {
    const wrapper = renderLogPage({ pageError: message })
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    expect(wrapper.find('input[id^="brand-text-"]').exists()).toBe(true)
  })

  it('asks for manual brand input when analysis returns no candidates', () => {
    const wrapper = renderLogPage({ candidates: [] })
    expect(wrapper.text()).toContain('銘柄候補を特定できませんでした。')
    expect(wrapper.get('input[id^="brand-text-"]').attributes('required')).toBeDefined()
  })

  it('shows catalog and AI candidate matching labels', () => {
    const wrapper = renderLogPage({
      candidates: [
        { brand_text: 'カリラ 12年', confidence: 0.9, match_source: 'catalog' },
        { brand_text: '山崎', confidence: 0.8, match_source: 'ai' },
      ],
    })

    const options = wrapper.findAll('option')
    expect(options[1].text()).toContain('カタログ一致')
    expect(options[1].text()).not.toContain('AI読取')
    expect(options[2].text()).toContain('AI読取')
    expect(options[2].text()).not.toContain('カタログ一致')
    expect(wrapper.text()).toContain('複数のボトルを検出しました。')
  })

  it('opens the selected confirmation-card preview in the lightbox', async () => {
    const wrapper = renderLogPage()

    wrapper.get<HTMLButtonElement>('button[aria-label="写真を拡大表示"]').element.click()
    await wrapper.vm.$nextTick()

    const dialog = wrapper.get('[role="dialog"]')
    const image = dialog.get('img')
    expect(image.attributes('src')).toBe('blob:preview')
    expect(image.attributes('alt')).toBe('1杯目の飲酒記録写真')
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
    expect(pageMocks.savePending).toHaveBeenCalledWith('', '')
    expect(pageMocks.savePending.mock.calls.flat()).not.toContain(35.681236)
    expect(pageMocks.savePending.mock.calls.flat()).not.toContain(139.767125)
    wrapper.unmount()
  })
})
