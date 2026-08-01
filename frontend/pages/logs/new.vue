<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import {
  clearPendingItemPlaceIds,
  copyStoreToPendingItems,
  isPlaceSelectedForPendingItems,
  setPlaceOnPendingItems,
  useDrinkLogBatch,
  MAX_DRINK_LOG_BATCH_SIZE,
  type DrinkLogBatchItem,
} from '~/composables/useDrinkLogBatch'
import { candidateIndexAfterBrandEdit, useDrinkLogs, type PlaceCandidate } from '~/composables/useDrinkLogs'
import { useGeolocation } from '~/composables/useGeolocation'
import { SERVING_STYLES, type ServingStyle } from '~/types/whiskey'
import { readExifGps, type Coordinates } from '~/utils/exifLocation'

const { searchPlaces, upsertLogs } = useDrinkLogs()
const {
  items,
  isProcessing,
  isSaving,
  allSaved,
  processFiles,
  retryProcessing,
  savePending,
  retrySave,
  reset,
} = useDrinkLogBatch()
const { disclosure, requesting: requestingLocation, requestPosition } = useGeolocation()

const places = ref<PlaceCandidate[]>([])
const pageError = ref('')
const selectionNotice = ref('')
const placeError = ref('')
const placeNotice = ref('')
const lightbox = reactive({
  open: false,
  src: '',
  alt: '',
})

const styleLabels: Record<ServingStyle, string> = {
  NEAT: 'ストレート',
  ROCKS: 'ロック',
  WATER: '水割り・トワイスアップ',
  SODA: 'ハイボール',
  COCKTAIL: 'カクテル',
}

const processingLabels: Record<DrinkLogBatchItem['phase'], string> = {
  queued: '処理中',
  resizing: '処理中',
  uploading: '処理中',
  analyzing: '処理中',
  ready: '解析完了',
  failed: '失敗',
}

const readyItems = computed(() => items.value.filter(item => item.phase === 'ready'))
const canSave = computed(() => (
  items.value.some(item => item.phase === 'ready' && item.saveStatus !== 'saved')
  && !isProcessing.value
  && !isSaving.value
))

onBeforeUnmount(reset)

const errorMessage = (cause: unknown, fallback: string) => cause instanceof Error && cause.message
  ? cause.message
  : fallback

const selectCandidate = (item: DrinkLogBatchItem, index: number) => {
  const candidate = item.candidates[index]
  if (!candidate) return
  item.selectedCandidateIndex = index
  item.brandText = candidate.brand_text
}

const handleBrandInput = (item: DrinkLogBatchItem) => {
  const reconciledIndex = candidateIndexAfterBrandEdit(
    item.candidates,
    item.selectedCandidateIndex,
    item.brandText,
  )
  if (reconciledIndex === null) {
    item.selectedCandidateIndex = null
  }
}

const selectedPlaceFor = (item: DrinkLogBatchItem) => (
  places.value.find(place => place.place_id === item.placeId) || null
)
const selectedPlaceAttributions = (item: DrinkLogBatchItem) => selectedPlaceFor(item)?.attributions || []

const clearItemPlaceIds = () => clearPendingItemPlaceIds(items.value)

const isSharedPlaceSelected = (placeId: string) => isPlaceSelectedForPendingItems(items.value, placeId)

const toggleSharedPlace = (placeId: string) => {
  setPlaceOnPendingItems(items.value, isSharedPlaceSelected(placeId) ? '' : placeId)
}

const applyFirstStoreToAllCards = () => {
  const firstItem = readyItems.value[0]
  if (!firstItem) return
  copyStoreToPendingItems(readyItems.value, firstItem)
}

const handleFileSelection = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return

  pageError.value = ''
  selectionNotice.value = files.length > MAX_DRINK_LOG_BATCH_SIZE
    ? `一度に登録できるのは${MAX_DRINK_LOG_BATCH_SIZE}枚までです`
    : ''
  placeNotice.value = ''
  input.value = ''

  let exifCoordinates: Coordinates | null = null
  for (const file of files.slice(0, MAX_DRINK_LOG_BATCH_SIZE)) {
    exifCoordinates = await readExifGps(file)
    if (exifCoordinates) break
  }

  const processing = processFiles(files)
  const nearbySearch = exifCoordinates
    ? searchNearbyPlaces(exifCoordinates, true)
    : Promise.resolve()
  exifCoordinates = null
  await Promise.all([processing, nearbySearch])
}

const handleProcessingRetry = async (item: DrinkLogBatchItem) => {
  pageError.value = ''
  await retryProcessing(item)
}

const searchNearbyPlaces = async (position: Coordinates, fromExif = false) => {
  placeError.value = ''
  placeNotice.value = ''

  try {
    places.value = await searchPlaces(position.lat, position.lng)
    clearItemPlaceIds()
    if (fromExif) placeNotice.value = '写真の位置情報から近くの店を検索しました。'
    if (!places.value.length) placeError.value = '近くの店候補が見つかりませんでした。店名を手入力してください。'
  } catch (cause) {
    places.value = []
    clearItemPlaceIds()
    placeError.value = errorMessage(cause, '近くの店を検索できませんでした。店名は手入力できます。')
  }
}

const findNearbyPlaces = async () => {
  placeError.value = ''
  placeNotice.value = ''
  const position = await requestPosition()
  if (!position) {
    places.value = []
    clearItemPlaceIds()
    placeError.value = '位置情報を取得できませんでした。店名を手入力して記録できます。'
    return
  }

  await searchNearbyPlaces(position)
}

const updateFailureSummary = () => {
  const processingFailures = items.value.filter(item => item.phase === 'failed').length
  const saveFailures = items.value.filter(item => item.phase === 'ready' && item.saveStatus === 'failed').length
  const failures = processingFailures + saveFailures
  pageError.value = failures
    ? `${failures}件の処理または保存に失敗しました。失敗した項目を確認して再試行してください。`
    : ''
}

const finishSave = async (created: Awaited<ReturnType<typeof savePending>>) => {
  if (created.length) upsertLogs(created)
  if (allSaved.value) await navigateTo('/logs')
  else updateFailureSummary()
}

const handleSubmit = async () => {
  pageError.value = ''
  await finishSave(await savePending())
}

const handleSaveRetry = async (item: DrinkLogBatchItem) => {
  pageError.value = ''
  const created = await retrySave(item)
  await finishSave(created ? [created] : [])
}

const openLightbox = (src: string, alt: string) => {
  if (!src) return
  lightbox.src = src
  lightbox.alt = alt
  lightbox.open = true
}
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 sm:px-0">
    <div class="mb-6">
      <p class="text-sm font-medium text-amber-400">写真ではじめるテイスティング記録</p>
      <h1 class="mt-1 text-3xl font-semibold text-amber-200">今日の一杯を記録</h1>
      <p class="mt-2 text-sm text-stone-300">写真1枚を1杯として、最大10枚をまとめて記録できます。AIの提案はすべて修正できます。</p>
    </div>

    <form class="space-y-6" @submit.prevent="handleSubmit">
      <section class="rounded-lg border border-amber-700 bg-stone-800 p-5 shadow-lg">
        <label for="drink-photo" class="block text-sm font-medium text-amber-200">ボトルやグラスの写真 *</label>
        <input
          id="drink-photo"
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
          multiple
          :disabled="isProcessing || isSaving"
          class="mt-3 block w-full text-sm text-stone-300 file:mr-4 file:rounded-md file:border-0 file:bg-amber-800 file:px-4 file:py-2 file:text-amber-100 hover:file:bg-amber-700 disabled:opacity-50"
          @change="handleFileSelection"
        />
        <p class="mt-2 text-xs text-stone-400">JPEG・PNG・WebP・HEIC/HEIF対応。一度に最大10枚まで選択できます。</p>
        <p v-if="selectionNotice" role="status" class="mt-3 rounded-md border border-amber-700 bg-amber-950/60 p-3 text-sm text-amber-200">{{ selectionNotice }}</p>

        <ul v-if="items.length" class="mt-4 space-y-3" aria-live="polite">
          <li v-for="(item, index) in items" :key="item.id" class="rounded-md border border-stone-600 bg-stone-700 p-3">
            <div class="flex items-start gap-3">
              <img v-if="item.previewUrl" :src="item.previewUrl" :alt="`${index + 1}枚目のプレビュー`" class="h-16 w-16 shrink-0 rounded bg-stone-900 object-cover" />
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-3">
                  <span class="truncate text-sm text-stone-200">{{ index + 1 }}. {{ item.file.name }}</span>
                  <span class="shrink-0 text-xs font-medium" :class="item.phase === 'failed' ? 'text-red-300' : item.phase === 'ready' ? 'text-emerald-300' : 'text-amber-300'">{{ processingLabels[item.phase] }}</span>
                </div>
                <div v-if="item.phase === 'uploading'" class="mt-2">
                  <div class="mb-1 flex justify-between text-xs text-amber-200"><span>アップロード中</span><span>{{ item.uploadProgress }}%</span></div>
                  <div class="h-2 overflow-hidden rounded-full bg-stone-600"><div class="h-full bg-amber-500 transition-all" :style="{ width: `${item.uploadProgress}%` }"></div></div>
                </div>
                <p v-if="item.error" class="mt-2 text-sm text-red-200">{{ item.error }}</p>
                <button v-if="item.phase === 'failed'" type="button" class="mt-2 rounded border border-red-700 px-3 py-1 text-xs text-red-200 hover:bg-red-950" @click="handleProcessingRetry(item)">この写真を再試行</button>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <section v-if="items.length" class="space-y-4 rounded-lg border border-amber-700 bg-stone-800 p-5 shadow-lg">
        <div class="flex items-center justify-between gap-4">
          <div>
            <h2 class="text-lg font-medium text-amber-200">店を探す</h2>
            <p class="mt-1 text-xs text-stone-400">近くの店を検索して選ぶと未保存の写真すべてに適用されます。写真ごとの変更もできます。</p>
          </div>
          <button type="button" :disabled="requestingLocation" class="rounded-md border border-amber-700 bg-stone-700 px-3 py-2 text-xs text-amber-100 hover:bg-stone-600 disabled:opacity-50" @click="findNearbyPlaces">
            {{ requestingLocation ? '位置情報を取得中…' : '近くの店を探す' }}
          </button>
        </div>
        <p class="rounded-md border border-blue-900 bg-blue-950/50 p-3 text-xs leading-relaxed text-blue-200">{{ disclosure }}</p>
        <p v-if="placeNotice" role="status" class="text-sm text-emerald-300">{{ placeNotice }}</p>
        <p v-if="placeError" role="status" class="text-sm text-amber-300">{{ placeError }}</p>

        <div v-if="places.length" class="space-y-2">
          <h3 id="nearby-places-label" class="text-sm font-medium text-amber-200">近くの店候補</h3>
          <div role="group" aria-labelledby="nearby-places-label" class="space-y-2">
            <div v-for="place in places" :key="place.place_id">
              <button
                type="button"
                :aria-pressed="isSharedPlaceSelected(place.place_id)"
                class="w-full rounded-md border p-3 text-left transition-colors"
                :class="isSharedPlaceSelected(place.place_id) ? 'border-amber-500 bg-amber-950/60' : 'border-stone-600 bg-stone-700 hover:border-amber-700 hover:bg-stone-600'"
                @click="toggleSharedPlace(place.place_id)"
              >
                <span class="block font-medium text-amber-100">{{ place.display_name }}</span>
                <span class="block text-xs text-stone-300">{{ place.formatted_address }}</span>
              </button>
              <GoogleAttributions :attributions="place.attributions" />
            </div>
          </div>
          <p class="text-xs text-stone-400">店を選ぶと未保存の写真すべてに適用されます。記録に残す店名は各カードで入力してください。</p>
        </div>

        <button v-if="readyItems.length >= 2" type="button" class="rounded-md border border-amber-700 bg-stone-700 px-3 py-2 text-xs text-amber-100 hover:bg-stone-600" @click="applyFirstStoreToAllCards">
          最初の一杯の店を全カードに適用
        </button>
      </section>

      <section v-for="item in items.filter(entry => entry.phase === 'ready')" :key="`card-${item.id}`" class="space-y-5 rounded-lg border border-amber-700 bg-stone-800 p-5 shadow-lg">
        <div class="flex items-start gap-4">
          <button
            type="button"
            aria-label="写真を拡大表示"
            class="h-28 w-28 shrink-0 cursor-zoom-in rounded-lg"
            @click="openLightbox(item.previewUrl, `${items.indexOf(item) + 1}杯目のテイスティング写真`)"
          >
            <img :src="item.previewUrl" :alt="`${items.indexOf(item) + 1}杯目のテイスティング写真`" class="h-28 w-28 rounded-lg bg-stone-900 object-cover" />
          </button>
          <div>
            <h2 class="text-lg font-medium text-amber-200">{{ items.indexOf(item) + 1 }}杯目の確認</h2>
            <p class="mt-1 text-xs text-stone-400">記録日時: 今（保存時刻）</p>
            <p v-if="item.saveStatus === 'saving'" class="mt-2 text-sm text-amber-300">保存中…</p>
            <p v-else-if="item.saveStatus === 'saved'" class="mt-2 text-sm text-emerald-300">保存完了</p>
            <p v-else-if="item.saveStatus === 'failed'" class="mt-2 text-sm text-red-200">保存失敗</p>
          </div>
        </div>

        <div v-if="item.candidates.length !== 1">
          <template v-if="item.candidates.length > 1">
            <p :id="`candidates-label-${item.id}`" class="block text-sm font-medium text-amber-200">AIが検出した銘柄</p>
            <div role="group" :aria-labelledby="`candidates-label-${item.id}`" class="mt-2 flex flex-wrap gap-2">
              <button
                v-for="(candidate, candidateIndex) in item.candidates"
                :key="`${candidate.brand_text}-${candidateIndex}`"
                type="button"
                :disabled="item.saveStatus === 'saved'"
                :aria-pressed="item.selectedCandidateIndex === candidateIndex"
                class="rounded-full border px-3 py-1.5 text-sm disabled:opacity-50"
                :class="item.selectedCandidateIndex === candidateIndex ? 'border-amber-500 bg-amber-700 text-amber-100' : 'border-stone-500 bg-stone-600 text-amber-300'"
                @click="selectCandidate(item, candidateIndex)"
              >
                {{ candidate.brand_text }}（{{ Math.round(candidate.confidence * 100) }}%）
              </button>
            </div>
          </template>
          <p v-if="item.candidates.length > 1" class="mt-2 rounded-md border border-amber-700 bg-amber-950/60 p-3 text-sm text-amber-200">
            複数のボトルを検出しました。記録する銘柄を選んでください。
          </p>
          <p v-if="!item.candidates.length" class="mt-2 rounded-md border border-amber-700 bg-amber-950/60 p-3 text-sm text-amber-200">
            銘柄候補を特定できませんでした。下の銘柄名を手入力してください。
          </p>
        </div>

        <div>
          <label :for="`brand-text-${item.id}`" class="block text-sm font-medium text-amber-200">銘柄名 *</label>
          <input :id="`brand-text-${item.id}`" v-model="item.brandText" :disabled="item.saveStatus === 'saved'" required type="text" maxlength="200" placeholder="例: アードベッグ 10年" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400 disabled:opacity-50" @input="handleBrandInput(item)" />
          <p v-if="item.candidates.length === 1 && item.candidates[0]" class="mt-1 text-xs text-stone-400">
            AIの読み取り: {{ item.candidates[0].brand_text }}（確度 {{ Math.round(item.candidates[0].confidence * 100) }}%・{{ item.candidates[0].match_source === 'catalog' ? 'カタログ一致' : 'AI読取' }}）
          </p>
          <p class="mt-1 text-xs text-stone-400">候補の文字を編集すると、手入力の銘柄として保存します。</p>
        </div>

        <fieldset :disabled="item.saveStatus === 'saved'">
          <legend class="block text-sm font-medium text-amber-200">飲み方</legend>
          <div class="mt-2 flex flex-wrap gap-2">
            <label v-for="style in SERVING_STYLES" :key="style" class="cursor-pointer rounded-full border px-3 py-1.5 text-sm" :class="item.servingStyle === style ? 'border-amber-500 bg-amber-700 text-amber-100' : 'border-stone-500 bg-stone-600 text-amber-300'">
              <input v-model="item.servingStyle" class="sr-only" type="radio" :name="`serving-style-${item.id}`" :value="style" />
              {{ styleLabels[style] }}
            </label>
          </div>
        </fieldset>

        <div>
          <div class="flex items-center justify-between">
            <span class="block text-sm font-medium text-amber-200">評価（任意）</span>
            <button v-if="item.rating && item.saveStatus !== 'saved'" type="button" class="text-xs text-stone-300 underline" @click="item.rating = null">評価を外す</button>
          </div>
          <div class="mt-1 flex items-center">
            <button v-for="score in 5" :key="score" type="button" :disabled="item.saveStatus === 'saved'" :aria-label="`評価 ${score}`" class="p-1 text-2xl disabled:opacity-50" :class="item.rating && score <= item.rating ? 'text-amber-400' : 'text-stone-500'" @click="item.rating = score">★</button>
            <span class="ml-2 text-sm text-amber-300">{{ item.rating ? `${item.rating} / 5` : '評価なし' }}</span>
          </div>
        </div>

        <div>
          <label v-if="places.length" :for="`place-${item.id}`" class="block text-sm font-medium text-amber-200">店（任意）</label>
          <select v-if="places.length" :id="`place-${item.id}`" v-model="item.placeId" :disabled="item.saveStatus === 'saved'" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 disabled:opacity-50">
            <option value="">店を選ばない</option>
            <option v-for="place in places" :key="place.place_id" :value="place.place_id" class="bg-stone-700 text-amber-100">{{ place.display_name }}</option>
          </select>
          <GoogleAttributions v-if="selectedPlaceFor(item)" :attributions="selectedPlaceAttributions(item)" />

          <label :for="`store-name-${item.id}`" class="mt-4 block text-sm font-medium text-amber-200">記録に残す店名（任意）</label>
          <input :id="`store-name-${item.id}`" v-model="item.storeName" :disabled="item.saveStatus === 'saved'" type="text" maxlength="200" placeholder="例: いつものバー" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400 disabled:opacity-50" />
          <p class="mt-1 text-xs text-stone-400">Googleの表示名は保存しません。選んだ店の place_id と、ここに入力した名前だけを保存します。</p>
        </div>

        <div>
          <label :for="`log-notes-${item.id}`" class="block text-sm font-medium text-amber-200">ノート（任意）</label>
          <textarea :id="`log-notes-${item.id}`" v-model="item.notes" :disabled="item.saveStatus === 'saved'" rows="4" maxlength="2000" placeholder="味わいや、そのときのことを記録…" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400 disabled:opacity-50"></textarea>
        </div>

        <div v-if="item.saveError" class="rounded-md border border-red-800 bg-red-900/50 p-3 text-sm text-red-200">
          <p>{{ item.saveError }}</p>
          <button type="button" :disabled="isSaving" class="mt-2 rounded border border-red-600 px-3 py-1 text-xs hover:bg-red-950 disabled:opacity-50" @click="handleSaveRetry(item)">この記録だけ再試行</button>
        </div>
      </section>

      <p v-if="pageError" role="alert" class="rounded-md border border-red-800 bg-red-900/50 p-3 text-sm text-red-200">{{ pageError }}</p>

      <div v-if="items.length" class="flex justify-end gap-3">
        <NuxtLink to="/logs" class="rounded-md border border-stone-600 bg-stone-700 px-4 py-2 text-amber-200 hover:bg-stone-600">キャンセル</NuxtLink>
        <button type="submit" :disabled="!canSave" class="rounded-md border border-amber-700 bg-amber-800 px-5 py-2 font-medium text-amber-100 hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50">
          {{ isSaving ? '保存中…' : items.length === 1 ? 'この一杯を記録' : `${items.length}杯をまとめて記録` }}
        </button>
      </div>
    </form>

    <ImageLightbox v-model:open="lightbox.open" :src="lightbox.src" :alt="lightbox.alt" />
  </div>
</template>
