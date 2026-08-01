import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import { ApiError } from '~/composables/useApi'
import {
  clearPendingItemPlaceIds,
  copyStoreToPendingItems,
  isPlaceSelectedForPendingItems,
  setPlaceOnPendingItems,
  useDrinkLogBatch,
  type DrinkLogBatchDependencies,
  type DrinkLogBatchItem,
} from '~/composables/useDrinkLogBatch'
import type { CreateDrinkLogPayload, DrinkLog, DrinkLogAnalysis } from '~/composables/useDrinkLogs'

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
  } satisfies DrinkLogBatchDependencies
}

describe('useDrinkLogBatch', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(file => `blob:${file.size}:${Math.random()}`),
      revokeObjectURL: vi.fn(),
    })
  })

  it('creates one log for every input photo', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogBatch(dependencies)
    const files = Array.from({ length: 4 }, (_, index) => new File(['photo'], `${index}.jpg`, { type: 'image/jpeg' }))

    await batch.processFiles(files)
    batch.items.value.forEach(item => {
      item.storeName = '共通店'
      item.placeId = 'place-1'
    })
    const created = await batch.savePending()

    expect(dependencies.resizeImage).toHaveBeenCalledTimes(4)
    expect(dependencies.getUploadUrl).toHaveBeenCalledTimes(4)
    dependencies.getUploadUrl.mock.calls.forEach(call => expect(call[0]).toBe('image/jpeg'))
    expect(dependencies.analyze).toHaveBeenCalledTimes(4)
    expect(dependencies.createLog).toHaveBeenCalledTimes(4)
    dependencies.createLog.mock.calls.forEach(call => expect(call[0]).toEqual(expect.objectContaining({
      store: { name: '共通店', place_id: 'place-1' },
    })))
    expect(created).toHaveLength(4)
    expect(batch.allSaved.value).toBe(true)
  })

  it('saves each item with its own store name and place id', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([
      new File(['first'], 'first.jpg'),
      new File(['second'], 'second.jpg'),
    ])
    Object.assign(batch.items.value[0]!, { storeName: '一軒目', placeId: 'place-first' })
    Object.assign(batch.items.value[1]!, { storeName: '二軒目', placeId: 'place-second' })

    await batch.savePending()

    expect(dependencies.createLog).toHaveBeenCalledTimes(2)
    expect(dependencies.createLog.mock.calls.map(([payload]) => payload.store)).toEqual([
      { name: '一軒目', place_id: 'place-first' },
      { name: '二軒目', place_id: 'place-second' },
    ])
  })

  it('omits store from the payload when both item store fields are empty', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([new File(['photo'], 'no-store.jpg')])

    await batch.savePending()

    expect(dependencies.createLog.mock.calls[0]?.[0]).not.toHaveProperty('store')
  })

  it('reads capture time from the original file and includes it when saving', async () => {
    const dependencies = makeDependencies()
    dependencies.readExifCapturedAt.mockResolvedValue('2026-08-01T21:30:00+09:00')
    const batch = useDrinkLogBatch(dependencies)
    const original = new File(['original-with-exif'], 'captured.jpg', { type: 'image/jpeg' })

    await batch.processFiles([original])
    await batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['photo'], 'skewed.jpg', { type: 'image/jpeg' })])
    await batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['photo'], 'invalid.jpg', { type: 'image/jpeg' })])
    await batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([new File(['photo'], 'manual.jpg')])
    batch.items.value[0]!.brandText = '手入力銘柄'

    await batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['photo'], 'multiple.jpg')])

    const item = batch.items.value[0]!
    expect(item.candidates).toHaveLength(2)
    expect(item.selectedCandidateIndex).toBeNull()
    expect(item).not.toHaveProperty('candidateSelection')
    expectTypeOf<'candidateSelection' extends keyof DrinkLogBatchItem ? true : false>().toEqualTypeOf<false>()
    expect(item.brandText).toBe('')
  })

  it('limits one selection to the first ten photos', async () => {
    const dependencies = makeDependencies()
    const batch = useDrinkLogBatch(dependencies)
    const files = Array.from({ length: 12 }, (_, index) => new File(['photo'], `${index}.jpg`))

    const result = await batch.processFiles(files)

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
    const batch = useDrinkLogBatch(dependencies)
    const processing = batch.processFiles(Array.from(
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
    const batch = useDrinkLogBatch(dependencies)
    const files = Array.from({ length: 3 }, (_, index) => new File(['photo'], `${index}.jpg`))

    await batch.processFiles(files)
    const saving = batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([
      new File(['photo'], 'one.jpg'),
      new File(['photo'], 'two.jpg'),
    ])

    const firstAttempt = await batch.savePending()

    expect(firstAttempt).toHaveLength(1)
    expect(batch.items.value.map(item => item.saveStatus).sort()).toEqual(['failed', 'saved'])
    expect(batch.items.value.find(item => item.saveStatus === 'failed')?.saveError).toContain('本日の上限')

    const retry = await batch.savePending()

    expect(retry).toHaveLength(1)
    expect(dependencies.createLog).toHaveBeenCalledTimes(3)
    expect(batch.allSaved.value).toBe(true)
  })

  it('does not enqueue the same save twice', async () => {
    const dependencies = makeDependencies()
    dependencies.createLog.mockImplementation(async () => {
      await new Promise(resolve => setTimeout(resolve, 5))
      return makeLog(1)
    })
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([new File(['photo'], 'one.jpg')])

    await Promise.all([batch.savePending(), batch.savePending()])

    expect(dependencies.createLog).toHaveBeenCalledTimes(1)
  })

  it('keeps analysis failures separate from successful cards', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockRejectedValueOnce(new Error('解析失敗'))
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['a'], 'bad.jpg'), new File(['b'], 'good.jpg')])

    expect(batch.items.value.map(item => item.phase).sort()).toEqual(['failed', 'ready'])
    expect(batch.items.value.find(item => item.phase === 'failed')?.error).toBe('解析失敗')
    await batch.savePending()
    expect(dependencies.createLog).toHaveBeenCalledTimes(1)

    const failed = batch.items.value.find(item => item.phase === 'failed')
    expect(failed).toBeDefined()
    await batch.retryProcessing(failed!)
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
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['p'], 'a.jpg', { type: 'image/jpeg' })])
    const item = batch.items.value[0]
    expect(item.phase).toBe('failed')
    item.storeName = '再解析前に選んだ店'
    item.placeId = 'place-before-retry'

    // Two synchronous retry clicks in the same frame must trigger only one reprocess.
    await Promise.all([batch.retryProcessing(item), batch.retryProcessing(item)])

    expect(dependencies.resizeImage).toHaveBeenCalledTimes(2) // 1 initial + 1 retry, not 3
    expect(analyzeCalls).toBe(2)
    expect(item.phase).toBe('ready')
    expect(item.storeName).toBe('再解析前に選んだ店')
    expect(item.placeId).toBe('place-before-retry')
  })
})

describe('useDrinkLogBatch save validation', () => {
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
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([new File(['photo'], 'multi.jpg')])
    const item = batch.items.value[0]!

    await batch.savePending()

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
    const batch = useDrinkLogBatch(dependencies)
    await batch.processFiles([new File(['photo'], 'none.jpg')])
    const item = batch.items.value[0]!

    await batch.savePending()

    expect(item.saveError).toBe('銘柄名を入力してください。')
  })
})

describe('per-card store helpers', () => {
  const storeItem = (overrides: Partial<DrinkLogBatchItem> = {}) => ({
    storeName: '',
    placeId: '',
    saveStatus: 'idle' as DrinkLogBatchItem['saveStatus'],
    ...overrides,
  }) as DrinkLogBatchItem

  it('copies the source store onto the other pending cards', () => {
    const source = storeItem({ storeName: 'いつものバー', placeId: 'place-1' })
    const other = storeItem()
    const items = [source, other]

    copyStoreToPendingItems(items, source)

    expect(other.storeName).toBe('いつものバー')
    expect(other.placeId).toBe('place-1')
  })

  it('never overwrites a card that is already saved', () => {
    const source = storeItem({ storeName: '2軒目', placeId: 'place-2' })
    const saved = storeItem({ storeName: '1軒目', placeId: 'place-1', saveStatus: 'saved' })

    copyStoreToPendingItems([source, saved], source)

    expect(saved.storeName).toBe('1軒目')
    expect(saved.placeId).toBe('place-1')
  })

  it('clears place ids on pending cards only, and keeps the typed store name', () => {
    const pending = storeItem({ storeName: '手入力の店', placeId: 'stale-place' })
    const saved = storeItem({ storeName: '保存済みの店', placeId: 'place-1', saveStatus: 'saved' })

    clearPendingItemPlaceIds([pending, saved])

    expect(pending.placeId).toBe('')
    expect(pending.storeName).toBe('手入力の店')
    expect(saved.placeId).toBe('place-1')
  })

  it('sets a place on pending cards without changing a saved card', () => {
    const firstPending = storeItem({ placeId: 'place-old-1' })
    const secondPending = storeItem({ placeId: 'place-old-2', saveStatus: 'failed' })
    const saved = storeItem({ placeId: 'place-saved', saveStatus: 'saved' })

    setPlaceOnPendingItems([firstPending, secondPending, saved], 'place-new')

    expect(firstPending.placeId).toBe('place-new')
    expect(secondPending.placeId).toBe('place-new')
    expect(saved.placeId).toBe('place-saved')
  })

  it('clears the place on every pending card when passed an empty place id', () => {
    const pending = storeItem({ placeId: 'place-1' })
    const saved = storeItem({ placeId: 'place-saved', saveStatus: 'saved' })

    setPlaceOnPendingItems([pending, saved], '')

    expect(pending.placeId).toBe('')
    expect(saved.placeId).toBe('place-saved')
  })

  it('reports a place selected only when every pending card matches it', () => {
    const first = storeItem({ placeId: 'place-1' })
    const second = storeItem({ placeId: 'place-1' })

    expect(isPlaceSelectedForPendingItems([first, second], 'place-1')).toBe(true)

    second.placeId = 'place-2'
    expect(isPlaceSelectedForPendingItems([first, second], 'place-1')).toBe(false)
  })

  it('does not report a place selected when there are no pending cards', () => {
    const saved = storeItem({ placeId: 'place-1', saveStatus: 'saved' })

    expect(isPlaceSelectedForPendingItems([saved], 'place-1')).toBe(false)
  })

  it('treats an empty place id as selected when every pending card has no place', () => {
    const emptyItems = [storeItem(), storeItem()]
    const mixedItems = [storeItem(), storeItem({ placeId: 'place-1' })]

    expect(isPlaceSelectedForPendingItems(emptyItems, '')).toBe(true)
    expect(isPlaceSelectedForPendingItems(mixedItems, '')).toBe(false)
  })
})
