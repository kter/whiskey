import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import { ApiError } from '~/composables/useApi'
import {
  useDrinkLogRecordingSession,
  type RecordingSessionDependencies,
  type RecordingSessionItem,
} from '~/composables/useDrinkLogRecordingSession'
import type { CreateDrinkLogPayload, DrinkLog, DrinkLogAnalysis, PlaceCandidate } from '~/composables/useDrinkLogs'

const makeLog = (index: number): DrinkLog => ({
  id: `log-${index}`,
  user_id: 'user-1',
  status: 'complete',
  brand_text: `Brand ${index}`,
  brand_source: 'ai',
  store: { name: '' },
  datetime: '2026-07-22T00:00:00Z',
})

const makeDependencies = () => {
  let uploadSequence = 0
  let createSequence = 0
  return {
    readExifCapturedAt: vi.fn(async (_file: File): Promise<string | null> => null),
    readExifGps: vi.fn(async (_file: File) => null),
    resizeImage: vi.fn(async () => ({ blob: new Blob(['jpeg'], { type: 'image/jpeg' }), contentType: 'image/jpeg' })),
    getUploadUrl: vi.fn(async (_contentType: string) => ({ upload_url: 'https://upload.test', fields: {}, s3_key: `photo-${++uploadSequence}` })),
    uploadToS3: vi.fn(async (_url, _fields, _blob, onProgress) => onProgress?.(100)),
    // Annotated with the real response type so mockResolvedValue can set
    // optional fields such as multiple_detected. Without it the mock's type is
    // inferred from this literal alone and every optional field is a type error.
    analyze: vi.fn(async (s3Key: string): Promise<DrinkLogAnalysis> => ({
      analysis_id: `analysis-${s3Key}`,
      candidates: [{ brand_text: `Brand ${s3Key}`, confidence: 0.9 }],
      model_id: 'test-model',
      confidence: 0.9,
    })),
    createLog: vi.fn(async (_payload: CreateDrinkLogPayload) => makeLog(++createSequence)),
    searchPlaces: vi.fn(async (): Promise<PlaceCandidate[]> => []),
    upsertLogs: vi.fn(),
  } satisfies RecordingSessionDependencies
}

describe('useDrinkLogRecordingSession', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(file => `blob:${file.size}:${Math.random()}`),
      revokeObjectURL: vi.fn(),
    })
  })

  it('creates one log for every input photo', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogRecordingSession(dependencies)
    const files = Array.from({ length: 4 }, (_, index) => new File(['photo'], `${index}.jpg`, { type: 'image/jpeg' }))

    await batch.selectFiles(files)
    batch.items.value.forEach(item => {
      item.storeName = '共通店'
      item.placeId = 'place-1'
    })
    const saved = await batch.saveAll()

    expect(dependencies.resizeImage).toHaveBeenCalledTimes(4)
    expect(dependencies.getUploadUrl).toHaveBeenCalledTimes(4)
    dependencies.getUploadUrl.mock.calls.forEach(call => expect(call[0]).toBe('image/jpeg'))
    expect(dependencies.analyze).toHaveBeenCalledTimes(4)
    expect(dependencies.createLog).toHaveBeenCalledTimes(4)
    dependencies.createLog.mock.calls.forEach(call => expect(call[0]).toEqual(expect.objectContaining({
      store: { name: '共通店', place_id: 'place-1' },
    })))
    expect(saved).toBe(true)
    expect(dependencies.upsertLogs).toHaveBeenCalledWith([
      makeLog(1),
      makeLog(2),
      makeLog(3),
      makeLog(4),
    ])
    expect(batch.allSaved.value).toBe(true)
  })

  it('saves each item with its own store name and place id', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([
      new File(['first'], 'first.jpg'),
      new File(['second'], 'second.jpg'),
    ])
    Object.assign(batch.items.value[0]!, { storeName: '一軒目', placeId: 'place-first' })
    Object.assign(batch.items.value[1]!, { storeName: '二軒目', placeId: 'place-second' })

    await batch.saveAll()

    expect(dependencies.createLog).toHaveBeenCalledTimes(2)
    expect(dependencies.createLog.mock.calls.map(([payload]) => payload.store)).toEqual([
      { name: '一軒目', place_id: 'place-first' },
      { name: '二軒目', place_id: 'place-second' },
    ])
  })

  it('omits store from the payload when both item store fields are empty', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([new File(['photo'], 'no-store.jpg')])

    await batch.saveAll()

    expect(dependencies.createLog.mock.calls[0]?.[0]).not.toHaveProperty('store')
  })

  it('reads capture time from the original file and includes it when saving', async () => {
    const dependencies = makeDependencies()
    dependencies.readExifCapturedAt.mockResolvedValue('2026-08-01T21:30:00+09:00')
    const batch = useDrinkLogRecordingSession(dependencies)
    const original = new File(['original-with-exif'], 'captured.jpg', { type: 'image/jpeg' })

    await batch.selectFiles([original])
    await batch.saveAll()

    expect(dependencies.readExifCapturedAt).toHaveBeenCalledWith(original)
    expect(dependencies.createLog).toHaveBeenCalledWith(expect.objectContaining({
      datetime: '2026-08-01T21:30:00+09:00',
    }))
  })

  it('retries once without the capture time when the server rejects it', async () => {
    const dependencies = makeDependencies()
    dependencies.readExifCapturedAt.mockResolvedValue('2126-08-01T21:30:00+09:00')
    // A device clock running ahead of the server produces a 400 that resending
    // the same payload could never clear.
    dependencies.createLog.mockRejectedValueOnce(
      new ApiError('Validation failed', 400, { error: 'Validation failed', fields: { datetime: 'Must be RFC3339' } }),
    )
    const batch = useDrinkLogRecordingSession(dependencies)

    await batch.selectFiles([new File(['photo'], 'skewed.jpg', { type: 'image/jpeg' })])
    await batch.saveAll()

    expect(dependencies.createLog).toHaveBeenCalledTimes(2)
    expect(dependencies.createLog.mock.calls[0]?.[0]).toHaveProperty('datetime')
    expect(dependencies.createLog.mock.calls[1]?.[0]).not.toHaveProperty('datetime')
    expect(batch.items.value[0]?.saveStatus).toBe('saved')
    expect(batch.items.value[0]?.capturedAt).toBeNull()
  })

  it('does not retry a save failure unrelated to the capture time', async () => {
    const dependencies = makeDependencies()
    dependencies.readExifCapturedAt.mockResolvedValue('2026-08-01T21:30:00+09:00')
    dependencies.createLog.mockRejectedValueOnce(
      new ApiError('Validation failed', 400, { error: 'Validation failed', fields: { brand_text: 'Field is required' } }),
    )
    const batch = useDrinkLogRecordingSession(dependencies)

    await batch.selectFiles([new File(['photo'], 'invalid.jpg', { type: 'image/jpeg' })])
    await batch.saveAll()

    expect(dependencies.createLog).toHaveBeenCalledTimes(1)
    expect(batch.items.value[0]?.saveStatus).toBe('failed')
    expect(batch.items.value[0]?.capturedAt).toBe('2026-08-01T21:30:00+09:00')
  })

  it('saves degraded analysis with a manually entered brand', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockResolvedValue({
      analysis_id: 'analysis-degraded',
      candidates: [],
      model_id: 'test-model',
      confidence: 0,
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([new File(['photo'], 'manual.jpg')])
    batch.items.value[0]!.brandText = '手入力銘柄'

    await batch.saveAll()

    expect(dependencies.createLog).toHaveBeenCalledWith({
      analysis_id: 'analysis-degraded',
      brand_text: '手入力銘柄',
    })
  })

  it('does not automatically select when multiple bottles are detected', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockResolvedValue({
      analysis_id: 'analysis-multiple',
      candidates: [
        { brand_text: 'グレンリベット 12年', confidence: 0.95 },
        { brand_text: 'ラガヴーリン 16年', confidence: 0.94 },
      ],
      model_id: 'test-model',
      confidence: 0.95,
      multiple_detected: true,
    })
    const batch = useDrinkLogRecordingSession(dependencies)

    await batch.selectFiles([new File(['photo'], 'multiple.jpg')])

    const item = batch.items.value[0]!
    expect(item.candidates).toHaveLength(2)
    expect(item.selectedCandidateIndex).toBeNull()
    expect(item).not.toHaveProperty('candidateSelection')
    expectTypeOf<'candidateSelection' extends keyof RecordingSessionItem ? true : false>().toEqualTypeOf<false>()
    expect(item.brandText).toBe('')
  })

  it('limits one selection to the first ten photos', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogRecordingSession(dependencies)
    const files = Array.from({ length: 12 }, (_, index) => new File(['photo'], `${index}.jpg`))

    const result = await batch.selectFiles(files)

    expect(result).toEqual({ accepted: 10, rejected: 2 })
    expect(batch.items.value).toHaveLength(10)
    expect(dependencies.resizeImage).toHaveBeenCalledTimes(10)
  })

  it('keeps two items in flight during processing', async () => {
    const dependencies = makeDependencies()
    let processingActive = 0
    let processingMaximum = 0
    const releases: Array<() => void> = []
    dependencies.analyze.mockImplementation(async (s3Key: string) => {
      processingActive += 1
      processingMaximum = Math.max(processingMaximum, processingActive)
      await new Promise<void>(resolve => releases.push(resolve))
      processingActive -= 1
      return {
        analysis_id: `analysis-${s3Key}`,
        candidates: [{ brand_text: `Brand ${s3Key}`, confidence: 0.9 }],
        model_id: 'test-model',
        confidence: 0.9,
      }
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    const processing = batch.selectFiles(Array.from(
      { length: 3 },
      (_, index) => new File(['photo'], `${index}.jpg`),
    ))

    await vi.waitFor(() => expect(dependencies.analyze).toHaveBeenCalledTimes(2))
    expect(processingMaximum).toBe(2)
    releases.shift()?.()
    await vi.waitFor(() => expect(dependencies.analyze).toHaveBeenCalledTimes(3))
    releases.splice(0).forEach(release => release())
    await processing

    expect(processingMaximum).toBe(2)
  })

  it('serializes saves so only one createLog is in flight', async () => {
    const dependencies = makeDependencies()
    let saveActive = 0
    let saveMaximum = 0
    const releases: Array<() => void> = []
    dependencies.createLog.mockImplementation(async () => {
      saveActive += 1
      saveMaximum = Math.max(saveMaximum, saveActive)
      await new Promise<void>(resolve => releases.push(resolve))
      saveActive -= 1
      return makeLog(Date.now() + saveActive)
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    const files = Array.from({ length: 3 }, (_, index) => new File(['photo'], `${index}.jpg`))

    await batch.selectFiles(files)
    const saving = batch.saveAll()

    await vi.waitFor(() => expect(dependencies.createLog).toHaveBeenCalledTimes(1))
    expect(saveActive).toBe(1)
    releases.shift()?.()
    await vi.waitFor(() => expect(dependencies.createLog).toHaveBeenCalledTimes(2))
    expect(saveActive).toBe(1)
    releases.shift()?.()
    await vi.waitFor(() => expect(dependencies.createLog).toHaveBeenCalledTimes(3))
    expect(saveActive).toBe(1)
    releases.shift()?.()
    await saving

    expect(saveMaximum).toBe(1)
  })

  it('isolates failures and retries only unsaved items', async () => {
    const dependencies = makeDependencies()
    dependencies.createLog
      .mockResolvedValueOnce(makeLog(1))
      .mockRejectedValueOnce(new Error('本日の上限に達しました'))
      .mockResolvedValueOnce(makeLog(3))
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([
      new File(['photo'], 'one.jpg'),
      new File(['photo'], 'two.jpg'),
    ])

    const firstAttempt = await batch.saveAll()

    expect(firstAttempt).toBe(false)
    expect(batch.items.value.map(item => item.saveStatus).sort()).toEqual(['failed', 'saved'])
    expect(batch.items.value.find(item => item.saveStatus === 'failed')?.saveError).toContain('本日の上限')

    const retry = await batch.saveAll()

    expect(retry).toBe(true)
    expect(dependencies.createLog).toHaveBeenCalledTimes(3)
    expect(batch.allSaved.value).toBe(true)
  })

  it('does not enqueue the same save twice', async () => {
    const dependencies = makeDependencies()
    dependencies.createLog.mockImplementation(async () => {
      await new Promise(resolve => setTimeout(resolve, 5))
      return makeLog(1)
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([new File(['photo'], 'one.jpg')])

    await Promise.all([batch.saveAll(), batch.saveAll()])

    expect(dependencies.createLog).toHaveBeenCalledTimes(1)
  })

  it('keeps analysis failures separate from successful cards', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockRejectedValueOnce(new Error('解析失敗'))
    const batch = useDrinkLogRecordingSession(dependencies)

    await batch.selectFiles([new File(['a'], 'bad.jpg'), new File(['b'], 'good.jpg')])

    expect(batch.items.value.map(item => item.phase).sort()).toEqual(['failed', 'ready'])
    expect(batch.items.value.find(item => item.phase === 'failed')?.error).toBe('解析失敗')
    await batch.saveAll()
    expect(dependencies.createLog).toHaveBeenCalledTimes(1)

    const failed = batch.items.value.find(item => item.phase === 'failed')
    expect(failed).toBeDefined()
    await batch.retryItemProcessing(failed!)
    expect(failed?.phase).toBe('ready')
  })

  it('ignores a duplicate retry for an item already re-queued (double-click guard)', async () => {
    const dependencies = makeDependencies()
    let analyzeCalls = 0
    dependencies.analyze = vi.fn(async (s3Key: string): Promise<DrinkLogAnalysis> => {
      analyzeCalls += 1
      if (analyzeCalls === 1) throw new Error('degraded')
      return { analysis_id: `analysis-${s3Key}`, candidates: [{ brand_text: 'X', confidence: 0.9 }], model_id: 'm', confidence: 0.9 }
    })
    const batch = useDrinkLogRecordingSession(dependencies)

    await batch.selectFiles([new File(['p'], 'a.jpg', { type: 'image/jpeg' })])
    const item = batch.items.value[0]
    expect(item.phase).toBe('failed')
    item.storeName = '再解析前に選んだ店'
    item.placeId = 'place-before-retry'

    // Two synchronous retry clicks in the same frame must trigger only one reprocess.
    await Promise.all([batch.retryItemProcessing(item), batch.retryItemProcessing(item)])

    expect(dependencies.resizeImage).toHaveBeenCalledTimes(2) // 1 initial + 1 retry, not 3
    expect(analyzeCalls).toBe(2)
    expect(item.phase).toBe('ready')
    expect(item.storeName).toBe('再解析前に選んだ店')
    expect(item.placeId).toBe('place-before-retry')
  })
})

describe('useDrinkLogRecordingSession save validation', () => {
  it('asks the user to pick a bottle when several were detected', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockResolvedValue({
      analysis_id: 'analysis-multi',
      candidates: [
        { brand_text: 'グレンリベット 12年', confidence: 0.95 },
        { brand_text: 'ラガヴーリン 16年', confidence: 0.94 },
      ],
      model_id: 'test-model',
      confidence: 0.95,
      multiple_detected: true,
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([new File(['photo'], 'multi.jpg')])
    const item = batch.items.value[0]!

    await batch.saveAll()

    expect(item.saveError).toBe('検出された銘柄から1つ選んでください。')
  })

  it('still asks for a brand name when nothing was detected', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockResolvedValue({
      analysis_id: 'analysis-none',
      candidates: [],
      model_id: 'test-model',
      confidence: 0,
    })
    const batch = useDrinkLogRecordingSession(dependencies)
    await batch.selectFiles([new File(['photo'], 'none.jpg')])
    const item = batch.items.value[0]!

    await batch.saveAll()

    expect(item.saveError).toBe('銘柄名を入力してください。')
  })
})

describe('recording session store intents', () => {
  const sessionWithItems = async () => {
    const dependencies = makeDependencies()
    const session = useDrinkLogRecordingSession(dependencies)
    await session.selectFiles([
      new File(['first'], 'first.jpg'),
      new File(['second'], 'second.jpg'),
    ])
    return { dependencies, session }
  }

  it('copies the first store onto other unsaved drinks', async () => {
    const { session } = await sessionWithItems()
    Object.assign(session.items.value[0]!, { storeName: 'いつものバー', placeId: 'place-1' })

    session.copyFirstStoreToAll()

    expect(session.items.value[1]).toEqual(expect.objectContaining({
      storeName: 'いつものバー',
      placeId: 'place-1',
    }))
  })

  it('never overwrites a saved drink', async () => {
    const { session } = await sessionWithItems()
    Object.assign(session.items.value[0]!, { storeName: '2軒目', placeId: 'place-2' })
    Object.assign(session.items.value[1]!, {
      storeName: '1軒目',
      placeId: 'place-1',
      saveStatus: 'saved',
    })

    session.copyFirstStoreToAll()
    session.toggleSharedPlace('place-new')

    expect(session.items.value[1]).toEqual(expect.objectContaining({
      storeName: '1軒目',
      placeId: 'place-1',
    }))
  })

  it('owns shared place selection and clears it when clicked again', async () => {
    const { session } = await sessionWithItems()

    session.toggleSharedPlace('place-1')
    expect(session.isSharedPlaceSelected('place-1')).toBe(true)
    expect(session.items.value.map(item => item.placeId)).toEqual(['place-1', 'place-1'])

    session.toggleSharedPlace('place-1')
    expect(session.items.value.map(item => item.placeId)).toEqual(['', ''])
  })

  it('clears stale place ids after a new search but keeps typed names', async () => {
    const { dependencies, session } = await sessionWithItems()
    Object.assign(session.items.value[0]!, { storeName: '手入力の店', placeId: 'stale-place' })
    dependencies.searchPlaces.mockResolvedValue([
      { place_id: 'new-place', display_name: '候補店', formatted_address: '東京都', attributions: [] },
    ])

    await session.findNearbyPlaces(async () => ({ lat: 35, lng: 139 }))

    expect(session.items.value[0]).toEqual(expect.objectContaining({
      storeName: '手入力の店',
      placeId: '',
    }))
    expect(session.places.value).toHaveLength(1)
  })
})
