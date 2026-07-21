import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { mount } from '@vue/test-utils'
import { computed, defineComponent, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { buildDrinkLogPayload, candidateIndexAfterBrandEdit } from '~/composables/useDrinkLogs'
import { SERVING_STYLES } from '~/types/whiskey'

const source = readFileSync(resolve(process.cwd(), 'pages/logs/new.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1]
if (!template) throw new Error('logs/new.vue template not found')

const renderLogPage = (options: { pageError?: string, placeError?: string, candidates?: unknown[] } = {}) => mount(defineComponent({
  setup: () => ({
    phase: ref('ready'),
    uploadProgress: ref(100),
    previewUrl: ref('blob:preview'),
    candidates: ref(options.candidates || []),
    candidateSelection: ref(''),
    brandText: ref(''),
    servingStyle: ref(''),
    places: ref([]),
    selectedPlaceId: ref(''),
    selectedPlace: computed(() => null),
    storeName: ref(''),
    rating: ref(null),
    notes: ref(''),
    pageError: ref(options.pageError || ''),
    placeError: ref(options.placeError || ''),
    saving: ref(false),
    requestingLocation: ref(false),
    disclosure: '座標は Google Places に送信し、保存しません。',
    isProcessing: computed(() => false),
    canSave: computed(() => false),
    SERVING_STYLES,
    styleLabels: { NEAT: 'ストレート', ROCKS: 'ロック', WATER: '水割り', SODA: 'ハイボール', COCKTAIL: 'カクテル' },
    handleFileSelection: vi.fn(),
    handleSubmit: vi.fn(),
    handleCandidateSelection: vi.fn(),
    handleBrandInput: vi.fn(),
    findNearbyPlaces: vi.fn(),
    attributionView: vi.fn(() => ({ label: '', url: '' })),
  }),
  template,
}))

describe('logs/new form behavior', () => {
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

  it('shows the manual store fallback when location permission is denied', () => {
    const wrapper = renderLogPage({ placeError: '位置情報を取得できませんでした。店名を手入力して記録できます。' })
    expect(wrapper.text()).toContain('店名を手入力して記録できます。')
    expect(wrapper.find('#store-name').exists()).toBe(true)
  })

  it.each([
    'リクエストが集中しています。しばらく待ってからお試しください。',
    'サービスを一時的に利用できません。しばらく待ってからお試しください。',
  ])('shows normalized API errors without hiding the editable form', message => {
    const wrapper = renderLogPage({ pageError: message })
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    expect(wrapper.find('#brand-text').exists()).toBe(true)
  })

  it('asks for manual brand input when analysis returns no candidates', () => {
    const wrapper = renderLogPage({ candidates: [] })
    expect(wrapper.text()).toContain('銘柄候補を特定できませんでした。')
    expect(wrapper.find('#brand-text').attributes('required')).toBeDefined()
  })
})
