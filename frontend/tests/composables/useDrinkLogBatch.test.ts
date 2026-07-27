import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDrinkLogBatch, type DrinkLogBatchDependencies } from '~/composables/useDrinkLogBatch'
import type { CreateDrinkLogPayload, DrinkLog } from '~/composables/useDrinkLogs'

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
    resizeImage: vi.fn(async () => ({ blob: new Blob(['jpeg'], { type: 'image/jpeg' }), contentType: 'image/jpeg' })),
    getUploadUrl: vi.fn(async (_contentType: string) => ({ upload_url: 'https://upload.test', fields: {}, s3_key: `photo-${++uploadSequence}` })),
    uploadToS3: vi.fn(async (_url, _fields, _blob, onProgress) => onProgress?.(100)),
    analyze: vi.fn(async s3Key => ({
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
    const created = await batch.savePending('共通店', 'place-1')

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

    await batch.savePending('', '')

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
    expect(item.candidateSelection).toBe('')
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

  it('keeps processing and save concurrency at two or fewer', async () => {
    const dependencies = makeDependencies()
    let processingActive = 0
    let processingMaximum = 0
    dependencies.uploadToS3.mockImplementation(async () => {
      processingActive += 1
      processingMaximum = Math.max(processingMaximum, processingActive)
      await new Promise(resolve => setTimeout(resolve, 5))
      processingActive -= 1
    })
    let saveActive = 0
    let saveMaximum = 0
    dependencies.createLog.mockImplementation(async () => {
      saveActive += 1
      saveMaximum = Math.max(saveMaximum, saveActive)
      await new Promise(resolve => setTimeout(resolve, 5))
      saveActive -= 1
      return makeLog(Date.now() + saveActive)
    })
    const batch = useDrinkLogBatch(dependencies)
    const files = Array.from({ length: 7 }, (_, index) => new File(['photo'], `${index}.jpg`))

    await batch.processFiles(files)
    await batch.savePending('', '')

    expect(processingMaximum).toBe(2)
    expect(saveMaximum).toBe(2)
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

    const firstAttempt = await batch.savePending('', '')

    expect(firstAttempt).toHaveLength(1)
    expect(batch.items.value.map(item => item.saveStatus).sort()).toEqual(['failed', 'saved'])
    expect(batch.items.value.find(item => item.saveStatus === 'failed')?.saveError).toContain('本日の上限')

    const retry = await batch.savePending('', '')

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

    await Promise.all([batch.savePending('', ''), batch.savePending('', '')])

    expect(dependencies.createLog).toHaveBeenCalledTimes(1)
  })

  it('keeps analysis failures separate from successful cards', async () => {
    const dependencies = makeDependencies()
    dependencies.analyze.mockRejectedValueOnce(new Error('解析失敗'))
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['a'], 'bad.jpg'), new File(['b'], 'good.jpg')])

    expect(batch.items.value.map(item => item.phase).sort()).toEqual(['failed', 'ready'])
    expect(batch.items.value.find(item => item.phase === 'failed')?.error).toBe('解析失敗')
    await batch.savePending('', '')
    expect(dependencies.createLog).toHaveBeenCalledTimes(1)

    const failed = batch.items.value.find(item => item.phase === 'failed')
    expect(failed).toBeDefined()
    await batch.retryProcessing(failed!)
    expect(failed?.phase).toBe('ready')
  })

  it('ignores a duplicate retry for an item already re-queued (double-click guard)', async () => {
    const dependencies = makeDependencies()
    let analyzeCalls = 0
    dependencies.analyze = vi.fn(async (s3Key: string) => {
      analyzeCalls += 1
      if (analyzeCalls === 1) throw new Error('degraded')
      return { analysis_id: `analysis-${s3Key}`, candidates: [{ brand_text: 'X', confidence: 0.9 }], model_id: 'm', confidence: 0.9 }
    })
    const batch = useDrinkLogBatch(dependencies)

    await batch.processFiles([new File(['p'], 'a.jpg', { type: 'image/jpeg' })])
    const item = batch.items.value[0]
    expect(item.phase).toBe('failed')

    // Two synchronous retry clicks in the same frame must trigger only one reprocess.
    await Promise.all([batch.retryProcessing(item), batch.retryProcessing(item)])

    expect(dependencies.resizeImage).toHaveBeenCalledTimes(2) // 1 initial + 1 retry, not 3
    expect(analyzeCalls).toBe(2)
    expect(item.phase).toBe('ready')
  })
})
