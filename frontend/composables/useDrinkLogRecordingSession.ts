import { computed, ref } from 'vue'
import { ApiError } from '~/composables/useApi'
import {
  buildDrinkLogPayload,
  candidateIndexAfterBrandEdit,
  useDrinkLogs,
  type DrinkLog,
  type DrinkLogAnalysis,
  type DrinkLogCandidate,
  type PlaceCandidate,
} from '~/composables/useDrinkLogs'
import { SERVING_STYLES, type ServingStyle } from '~/types/whiskey'
import { readExifCapturedAt } from '~/utils/exifCapturedAt'
import { readExifGps, type Coordinates } from '~/utils/exifLocation'
import { normalizeDrinkLogError } from '~/utils/drinkLogs'
import { ImageTooLargeError, resizeImage } from '~/utils/imageResize'

export const MAX_RECORDING_SESSION_SIZE = 10
export const RECORDING_PROCESS_CONCURRENCY = 2
export const RECORDING_SAVE_CONCURRENCY = 1

export type RecordingProcessingPhase = 'queued' | 'resizing' | 'uploading' | 'analyzing' | 'ready' | 'failed'
export type RecordingSaveStatus = 'idle' | 'saving' | 'saved' | 'failed'

export interface RecordingSessionItem {
  id: string
  file: File
  capturedAt: string | null
  phase: RecordingProcessingPhase
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
  saveStatus: RecordingSaveStatus
  saveError: string
  createdLog: DrinkLog | null
}

export interface RecordingSessionDependencies {
  readExifCapturedAt: typeof readExifCapturedAt
  readExifGps: typeof readExifGps
  resizeImage: typeof resizeImage
  getUploadUrl: ReturnType<typeof useDrinkLogs>['getUploadUrl']
  uploadToS3: ReturnType<typeof useDrinkLogs>['uploadToS3']
  analyze: ReturnType<typeof useDrinkLogs>['analyze']
  createLog: ReturnType<typeof useDrinkLogs>['createLog']
  searchPlaces: ReturnType<typeof useDrinkLogs>['searchPlaces']
  upsertLogs: ReturnType<typeof useDrinkLogs>['upsertLogs']
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

const copyStoreToPendingItems = (items: RecordingSessionItem[], source: RecordingSessionItem) => {
  items.forEach(item => {
    if (item === source || item.saveStatus === 'saved') return
    item.storeName = source.storeName
    item.placeId = source.placeId
  })
}

const clearPendingItemPlaceIds = (items: RecordingSessionItem[]) => {
  items.forEach(item => {
    if (item.saveStatus !== 'saved') item.placeId = ''
  })
}

const isPlaceSelectedForPendingItems = (items: RecordingSessionItem[], placeId: string): boolean => {
  const pendingItems = items.filter(item => item.saveStatus !== 'saved')
  return pendingItems.length > 0 && pendingItems.every(item => item.placeId === placeId)
}

const setPlaceOnPendingItems = (items: RecordingSessionItem[], placeId: string): void => {
  items.forEach(item => {
    if (item.saveStatus !== 'saved') item.placeId = placeId
  })
}

/** True for the one create failure a retry with the same payload can never clear. */
const isDatetimeRejection = (cause: unknown) => {
  if (!(cause instanceof ApiError) || cause.status !== 400) return false
  const fields = (cause.details as { fields?: unknown } | undefined)?.fields
  return Boolean(fields && typeof fields === 'object' && 'datetime' in fields)
}

const processingError = (cause: unknown) => {
  if (cause instanceof ImageTooLargeError) return '画像を3.5MB以下にできませんでした。別の画像を選択してください。'
  return normalizeDrinkLogError(cause, '画像の準備または解析に失敗しました。')
}

const newItem = (file: File, id: string): RecordingSessionItem => ({
  id,
  file,
  capturedAt: null,
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

export const useDrinkLogRecordingSession = (provided?: RecordingSessionDependencies) => {
  const drinkLogs = provided ? null : useDrinkLogs()
  const dependencies: RecordingSessionDependencies = provided || {
    readExifCapturedAt,
    readExifGps,
    resizeImage,
    getUploadUrl: drinkLogs!.getUploadUrl,
    uploadToS3: drinkLogs!.uploadToS3,
    analyze: drinkLogs!.analyze,
    createLog: drinkLogs!.createLog,
    searchPlaces: drinkLogs!.searchPlaces,
    upsertLogs: drinkLogs!.upsertLogs,
  }
  const items = ref<RecordingSessionItem[]>([])
  const places = ref<PlaceCandidate[]>([])
  const pageError = ref('')
  const selectionNotice = ref('')
  const placeError = ref('')
  const placeNotice = ref('')
  const processWithLimit = createLimiter(RECORDING_PROCESS_CONCURRENCY)
  const saveWithLimit = createLimiter(RECORDING_SAVE_CONCURRENCY)
  let itemSequence = 0

  const revokePreview = (item: RecordingSessionItem) => {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    item.previewUrl = ''
  }

  const resetItems = () => {
    items.value.forEach(revokePreview)
    items.value = []
  }

  const reset = () => {
    resetItems()
    places.value = []
    pageError.value = ''
    selectionNotice.value = ''
    placeError.value = ''
    placeNotice.value = ''
  }

  const applyAnalysis = (item: RecordingSessionItem, analysis: DrinkLogAnalysis) => {
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

  const processItem = async (item: RecordingSessionItem) => {
    revokePreview(item)
    item.phase = 'resizing'
    item.capturedAt = null
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
      item.capturedAt = await dependencies.readExifCapturedAt(item.file)
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

  const enqueueProcessing = (item: RecordingSessionItem) => {
    item.phase = 'queued'
    item.error = ''
    return processWithLimit(() => processItem(item))
  }

  const retryProcessing = (item: RecordingSessionItem) => {
    // Guard against a same-frame double click: only a failed item may be re-queued.
    // The first click flips phase to 'queued', so a second synchronous call is a no-op
    // (prevents a duplicate upload and a leaked preview URL from re-processing).
    if (item.phase !== 'failed') return Promise.resolve()
    return enqueueProcessing(item)
  }

  const processFiles = async (files: File[]) => {
    resetItems()
    const accepted = files.slice(0, MAX_RECORDING_SESSION_SIZE)
    items.value = accepted.map(file => newItem(file, `drink-photo-${++itemSequence}`))
    await Promise.all(items.value.map(item => enqueueProcessing(item)))
    return { accepted: accepted.length, rejected: Math.max(0, files.length - accepted.length) }
  }

  const saveItem = async (item: RecordingSessionItem) => {
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
    const payloadFor = (capturedAt: string | null) => buildDrinkLogPayload({
      analysisId: item.analysisId,
      capturedAt,
      candidateIndex: item.selectedCandidateIndex,
      brandText: item.brandText,
      servingStyle: item.servingStyle,
      storeName: item.storeName,
      placeId: item.placeId,
      notes: item.notes,
      rating: item.rating,
    })
    try {
      let created: DrinkLog
      try {
        created = await dependencies.createLog(payloadFor(item.capturedAt))
      } catch (cause) {
        // The server bounds the capture time against its own clock, so a device
        // running fast enough gets a 400 the user could never resolve. Drop the
        // EXIF time once and let the server stamp the record instead.
        if (!isDatetimeRejection(cause)) throw cause
        item.capturedAt = null
        created = await dependencies.createLog(payloadFor(null))
      }
      item.createdLog = created
      item.saveStatus = 'saved'
      return created
    } catch (cause) {
      item.saveStatus = 'failed'
      item.saveError = normalizeDrinkLogError(cause, '記録の保存に失敗しました。')
      return null
    }
  }

  const retrySave = (item: RecordingSessionItem) => {
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

  const readyItems = computed(() => items.value.filter(item => item.phase === 'ready'))

  const selectCandidate = (item: RecordingSessionItem, index: number) => {
    const candidate = item.candidates[index]
    if (!candidate) return
    item.selectedCandidateIndex = index
    item.brandText = candidate.brand_text
  }

  const reconcileBrandEdit = (item: RecordingSessionItem) => {
    item.selectedCandidateIndex = candidateIndexAfterBrandEdit(
      item.candidates,
      item.selectedCandidateIndex,
      item.brandText,
    )
  }

  const selectedPlaceFor = (item: RecordingSessionItem) => (
    places.value.find(place => place.place_id === item.placeId) || null
  )

  const selectedPlaceAttributions = (item: RecordingSessionItem) => (
    selectedPlaceFor(item)?.attributions || []
  )

  const isSharedPlaceSelected = (placeId: string) => (
    isPlaceSelectedForPendingItems(items.value, placeId)
  )

  const toggleSharedPlace = (placeId: string) => {
    setPlaceOnPendingItems(items.value, isSharedPlaceSelected(placeId) ? '' : placeId)
  }

  const copyFirstStoreToAll = () => {
    const firstItem = readyItems.value[0]
    if (firstItem) copyStoreToPendingItems(readyItems.value, firstItem)
  }

  const searchNearbyPlaces = async (position: Coordinates, fromExif = false) => {
    placeError.value = ''
    placeNotice.value = ''
    try {
      places.value = await dependencies.searchPlaces(position.lat, position.lng)
      clearPendingItemPlaceIds(items.value)
      if (fromExif) placeNotice.value = '写真の位置情報から近くの店を検索しました。'
      if (!places.value.length) {
        placeError.value = '近くの店候補が見つかりませんでした。店名を手入力してください。'
      }
    } catch (cause) {
      places.value = []
      clearPendingItemPlaceIds(items.value)
      placeError.value = normalizeDrinkLogError(
        cause,
        '近くの店を検索できませんでした。店名は手入力できます。',
      )
    }
  }

  const selectFiles = async (files: File[]) => {
    if (!files.length) return
    pageError.value = ''
    selectionNotice.value = files.length > MAX_RECORDING_SESSION_SIZE
      ? `一度に登録できるのは${MAX_RECORDING_SESSION_SIZE}枚までです`
      : ''
    placeNotice.value = ''

    let exifCoordinates: Coordinates | null = null
    for (const file of files.slice(0, MAX_RECORDING_SESSION_SIZE)) {
      exifCoordinates = await dependencies.readExifGps(file)
      if (exifCoordinates) break
    }
    const processing = processFiles(files)
    await Promise.all([
      processing,
      exifCoordinates ? searchNearbyPlaces(exifCoordinates, true) : Promise.resolve(),
    ])
    return processing
  }

  const findNearbyPlaces = async (requestPosition: () => Promise<Coordinates | null>) => {
    placeError.value = ''
    placeNotice.value = ''
    const position = await requestPosition()
    if (!position) {
      places.value = []
      clearPendingItemPlaceIds(items.value)
      placeError.value = '位置情報を取得できませんでした。店名を手入力して記録できます。'
      return
    }
    await searchNearbyPlaces(position)
  }

  const retryItemProcessing = async (item: RecordingSessionItem) => {
    pageError.value = ''
    await retryProcessing(item)
  }

  const updateFailureSummary = () => {
    const processingFailures = items.value.filter(item => item.phase === 'failed').length
    const saveFailures = items.value.filter(item => (
      item.phase === 'ready' && item.saveStatus === 'failed'
    )).length
    const failures = processingFailures + saveFailures
    pageError.value = failures
      ? `${failures}件の処理または保存に失敗しました。失敗した項目を確認して再試行してください。`
      : ''
  }

  const finishSave = (created: DrinkLog[]) => {
    if (created.length) dependencies.upsertLogs(created)
    if (!allSaved.value) updateFailureSummary()
    return allSaved.value
  }

  const saveAll = async () => {
    pageError.value = ''
    return finishSave(await savePending())
  }

  const retryItemSave = async (item: RecordingSessionItem) => {
    pageError.value = ''
    const created = await retrySave(item)
    return finishSave(created ? [created] : [])
  }

  const isProcessing = computed(() => items.value.some(item => !['ready', 'failed'].includes(item.phase)))
  const isSaving = computed(() => items.value.some(item => item.saveStatus === 'saving'))
  const allSaved = computed(() => items.value.length > 0 && items.value.every(item => item.saveStatus === 'saved'))
  const canSave = computed(() => (
    items.value.some(item => item.phase === 'ready' && item.saveStatus !== 'saved')
    && !isProcessing.value
    && !isSaving.value
  ))

  return {
    items,
    places,
    pageError,
    selectionNotice,
    placeError,
    placeNotice,
    readyItems,
    isProcessing,
    isSaving,
    allSaved,
    canSave,
    selectFiles,
    retryItemProcessing,
    selectCandidate,
    reconcileBrandEdit,
    selectedPlaceFor,
    selectedPlaceAttributions,
    isSharedPlaceSelected,
    toggleSharedPlace,
    copyFirstStoreToAll,
    findNearbyPlaces,
    saveAll,
    retryItemSave,
    reset,
  }
}
