import { computed, ref } from 'vue'
import {
  buildDrinkLogPayload,
  normalizeDrinkLogError,
  useDrinkLogs,
  type DrinkLog,
  type DrinkLogAnalysis,
  type DrinkLogCandidate,
} from '~/composables/useDrinkLogs'
import { SERVING_STYLES, type ServingStyle } from '~/types/whiskey'
import { ImageTooLargeError, resizeImage } from '~/utils/imageResize'

export const MAX_DRINK_LOG_BATCH_SIZE = 10
export const DRINK_LOG_BATCH_CONCURRENCY = 2

export type BatchProcessingPhase = 'queued' | 'resizing' | 'uploading' | 'analyzing' | 'ready' | 'failed'
export type BatchSaveStatus = 'idle' | 'saving' | 'saved' | 'failed'

export interface DrinkLogBatchItem {
  id: string
  file: File
  phase: BatchProcessingPhase
  uploadProgress: number
  previewUrl: string
  analysisId: string
  candidates: DrinkLogCandidate[]
  selectedCandidateIndex: number | null
  brandText: string
  servingStyle: ServingStyle | ''
  rating: number | null
  storeName: string
  placeId: string
  notes: string
  error: string
  saveStatus: BatchSaveStatus
  saveError: string
  createdLog: DrinkLog | null
}

export interface DrinkLogBatchDependencies {
  resizeImage: typeof resizeImage
  getUploadUrl: ReturnType<typeof useDrinkLogs>['getUploadUrl']
  uploadToS3: ReturnType<typeof useDrinkLogs>['uploadToS3']
  analyze: ReturnType<typeof useDrinkLogs>['analyze']
  createLog: ReturnType<typeof useDrinkLogs>['createLog']
}

const createLimiter = (limit: number) => {
  let active = 0
  const waiters: Array<() => void> = []

  const acquire = () => {
    if (active < limit) {
      active += 1
      return Promise.resolve()
    }
    return new Promise<void>(resolve => waiters.push(resolve))
  }

  const release = () => {
    const next = waiters.shift()
    if (next) next()
    else active = Math.max(0, active - 1)
  }

  return async <T>(operation: () => Promise<T>): Promise<T> => {
    await acquire()
    try {
      return await operation()
    } finally {
      release()
    }
  }
}

/**
 * Copies one card's store onto the other cards. Saved cards are skipped: their
 * record is already persisted, so mutating them would misrepresent what was stored.
 */
export const copyStoreToPendingItems = (items: DrinkLogBatchItem[], source: DrinkLogBatchItem) => {
  items.forEach(item => {
    if (item === source || item.saveStatus === 'saved') return
    item.storeName = source.storeName
    item.placeId = source.placeId
  })
}

/** Drops place references that no longer belong to the current candidate set. */
export const clearPendingItemPlaceIds = (items: DrinkLogBatchItem[]) => {
  items.forEach(item => {
    if (item.saveStatus !== 'saved') item.placeId = ''
  })
}

const processingError = (cause: unknown) => {
  if (cause instanceof ImageTooLargeError) return '画像を3.5MB以下にできませんでした。別の画像を選択してください。'
  return normalizeDrinkLogError(cause, '画像の準備または解析に失敗しました。')
}

const newItem = (file: File, id: string): DrinkLogBatchItem => ({
  id,
  file,
  phase: 'queued',
  uploadProgress: 0,
  previewUrl: '',
  analysisId: '',
  candidates: [],
  selectedCandidateIndex: null,
  brandText: '',
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

export const useDrinkLogBatch = (provided?: DrinkLogBatchDependencies) => {
  const drinkLogs = provided ? null : useDrinkLogs()
  const dependencies: DrinkLogBatchDependencies = provided || {
    resizeImage,
    getUploadUrl: drinkLogs!.getUploadUrl,
    uploadToS3: drinkLogs!.uploadToS3,
    analyze: drinkLogs!.analyze,
    createLog: drinkLogs!.createLog,
  }
  const items = ref<DrinkLogBatchItem[]>([])
  const processWithLimit = createLimiter(DRINK_LOG_BATCH_CONCURRENCY)
  const saveWithLimit = createLimiter(DRINK_LOG_BATCH_CONCURRENCY)
  let itemSequence = 0

  const revokePreview = (item: DrinkLogBatchItem) => {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    item.previewUrl = ''
  }

  const reset = () => {
    items.value.forEach(revokePreview)
    items.value = []
  }

  const applyAnalysis = (item: DrinkLogBatchItem, analysis: DrinkLogAnalysis) => {
    item.analysisId = analysis.analysis_id
    item.candidates = analysis.candidates || []
    if (item.candidates.length === 1) {
      item.selectedCandidateIndex = 0
      item.brandText = item.candidates[0]?.brand_text || ''
    }
    if (analysis.serving_style && SERVING_STYLES.includes(analysis.serving_style as ServingStyle)) {
      item.servingStyle = analysis.serving_style as ServingStyle
    }
  }

  const processItem = async (item: DrinkLogBatchItem) => {
    revokePreview(item)
    item.phase = 'resizing'
    item.uploadProgress = 0
    item.analysisId = ''
    item.candidates = []
    item.selectedCandidateIndex = null
    item.brandText = ''
    item.servingStyle = ''
    item.error = ''
    item.saveStatus = 'idle'
    item.saveError = ''
    item.createdLog = null

    try {
      const resized = await dependencies.resizeImage(item.file)
      item.previewUrl = URL.createObjectURL(resized.blob)
      item.phase = 'uploading'
      const upload = await dependencies.getUploadUrl(resized.contentType)
      await dependencies.uploadToS3(upload.upload_url, upload.fields, resized.blob, progress => {
        item.uploadProgress = progress
      })
      item.phase = 'analyzing'
      applyAnalysis(item, await dependencies.analyze(upload.s3_key))
      item.phase = 'ready'
    } catch (cause) {
      item.phase = 'failed'
      item.error = processingError(cause)
    }
  }

  const enqueueProcessing = (item: DrinkLogBatchItem) => {
    item.phase = 'queued'
    item.error = ''
    return processWithLimit(() => processItem(item))
  }

  const retryProcessing = (item: DrinkLogBatchItem) => {
    // Guard against a same-frame double click: only a failed item may be re-queued.
    // The first click flips phase to 'queued', so a second synchronous call is a no-op
    // (prevents a duplicate upload and a leaked preview URL from re-processing).
    if (item.phase !== 'failed') return Promise.resolve()
    return enqueueProcessing(item)
  }

  const processFiles = async (files: File[]) => {
    reset()
    const accepted = files.slice(0, MAX_DRINK_LOG_BATCH_SIZE)
    items.value = accepted.map(file => newItem(file, `drink-photo-${++itemSequence}`))
    await Promise.all(items.value.map(item => enqueueProcessing(item)))
    return { accepted: accepted.length, rejected: Math.max(0, files.length - accepted.length) }
  }

  const saveItem = async (item: DrinkLogBatchItem) => {
    if (!item.analysisId || !item.brandText.trim()) {
      item.saveStatus = 'failed'
      // Multiple bottles are deliberately left unselected, so the required
      // action is picking one -- not typing a name.
      item.saveError = item.candidates.length > 1 && item.selectedCandidateIndex === null
        ? '検出された銘柄から1つ選んでください。'
        : '銘柄名を入力してください。'
      return null
    }

    item.saveStatus = 'saving'
    item.saveError = ''
    try {
      const created = await dependencies.createLog(buildDrinkLogPayload({
        analysisId: item.analysisId,
        candidateIndex: item.selectedCandidateIndex,
        brandText: item.brandText,
        servingStyle: item.servingStyle,
        storeName: item.storeName,
        placeId: item.placeId,
        notes: item.notes,
        rating: item.rating,
      }))
      item.createdLog = created
      item.saveStatus = 'saved'
      return created
    } catch (cause) {
      item.saveStatus = 'failed'
      item.saveError = normalizeDrinkLogError(cause, '記録の保存に失敗しました。')
      return null
    }
  }

  const retrySave = (item: DrinkLogBatchItem) => {
    if (item.saveStatus === 'saving' || item.saveStatus === 'saved') return Promise.resolve(item.createdLog)
    item.saveStatus = 'saving'
    item.saveError = ''
    return saveWithLimit(() => saveItem(item))
  }

  const savePending = async () => {
    const pending = items.value.filter(item => (
      item.phase === 'ready' && ['idle', 'failed'].includes(item.saveStatus)
    ))
    const results = await Promise.all(pending.map(item => retrySave(item)))
    return results.filter((log): log is DrinkLog => Boolean(log))
  }

  const isProcessing = computed(() => items.value.some(item => !['ready', 'failed'].includes(item.phase)))
  const isSaving = computed(() => items.value.some(item => item.saveStatus === 'saving'))
  const allSaved = computed(() => items.value.length > 0 && items.value.every(item => item.saveStatus === 'saved'))
  const savedLogs = computed(() => items.value.flatMap(item => item.createdLog ? [item.createdLog] : []))

  return {
    items,
    isProcessing,
    isSaving,
    allSaved,
    savedLogs,
    processFiles,
    retryProcessing,
    savePending,
    retrySave,
    reset,
  }
}
