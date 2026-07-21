<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { buildDrinkLogPayload, candidateIndexAfterBrandEdit, useDrinkLogs, type DrinkLogCandidate, type PlaceCandidate } from '~/composables/useDrinkLogs'
import { useGeolocation } from '~/composables/useGeolocation'
import { SERVING_STYLES, type ServingStyle } from '~/types/whiskey'
import { HeicUnsupportedError, ImageTooLargeError, resizeImage } from '~/utils/imageResize'

type ProcessingPhase = 'idle' | 'resizing' | 'uploading' | 'analyzing' | 'ready'

const { getUploadUrl, uploadToS3, analyze, createLog, searchPlaces, upsertLog } = useDrinkLogs()
const { disclosure, requesting: requestingLocation, requestPosition } = useGeolocation()

const phase = ref<ProcessingPhase>('idle')
const uploadProgress = ref(0)
const previewUrl = ref('')
const analysisId = ref('')
const candidates = ref<DrinkLogCandidate[]>([])
const candidateSelection = ref('')
const selectedCandidateIndex = ref<number | null>(null)
const brandText = ref('')
const servingStyle = ref<ServingStyle | ''>('')
const places = ref<PlaceCandidate[]>([])
const selectedPlaceId = ref('')
const storeName = ref('')
const rating = ref<number | null>(null)
const notes = ref('')
const pageError = ref('')
const placeError = ref('')
const saving = ref(false)

const styleLabels: Record<ServingStyle, string> = {
  NEAT: 'ストレート',
  ROCKS: 'ロック',
  WATER: '水割り・トワイスアップ',
  SODA: 'ハイボール',
  COCKTAIL: 'カクテル',
}

const isProcessing = computed(() => ['resizing', 'uploading', 'analyzing'].includes(phase.value))
const canSave = computed(() => Boolean(analysisId.value && brandText.value.trim()) && !saving.value)
const selectedPlace = computed(() => places.value.find(place => place.place_id === selectedPlaceId.value) || null)

const replacePreview = (url: string) => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = url
}

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

const errorMessage = (cause: unknown, fallback: string) => cause instanceof Error && cause.message
  ? cause.message
  : fallback

const selectCandidate = (index: number) => {
  const candidate = candidates.value[index]
  if (!candidate) return
  selectedCandidateIndex.value = index
  candidateSelection.value = String(index)
  brandText.value = candidate.brand_text
}

const handleCandidateSelection = () => {
  if (candidateSelection.value === '') {
    selectedCandidateIndex.value = null
    return
  }
  selectCandidate(Number(candidateSelection.value))
}

const handleBrandInput = () => {
  const reconciledIndex = candidateIndexAfterBrandEdit(candidates.value, selectedCandidateIndex.value, brandText.value)
  if (reconciledIndex === null) {
    selectedCandidateIndex.value = null
    candidateSelection.value = ''
  }
}

const handleFileSelection = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  pageError.value = ''
  analysisId.value = ''
  candidates.value = []
  candidateSelection.value = ''
  selectedCandidateIndex.value = null
  brandText.value = ''
  servingStyle.value = ''
  uploadProgress.value = 0
  phase.value = 'resizing'

  try {
    const resized = await resizeImage(file)
    replacePreview(URL.createObjectURL(resized.blob))
    phase.value = 'uploading'
    const upload = await getUploadUrl(resized.contentType)
    await uploadToS3(upload.upload_url, upload.fields, resized.blob, progress => {
      uploadProgress.value = progress
    })

    phase.value = 'analyzing'
    const result = await analyze(upload.s3_key)
    analysisId.value = result.analysis_id
    candidates.value = result.candidates || []
    if (candidates.value.length) selectCandidate(0)
    else brandText.value = ''
    if (result.serving_style && SERVING_STYLES.includes(result.serving_style as ServingStyle)) {
      servingStyle.value = result.serving_style as ServingStyle
    }
    phase.value = 'ready'
  } catch (cause) {
    phase.value = 'idle'
    if (cause instanceof HeicUnsupportedError) {
      pageError.value = 'HEIC/HEIF形式には対応していません。JPEGで撮影または選択してください。'
    } else if (cause instanceof ImageTooLargeError) {
      pageError.value = '画像を3.5MB以下にできませんでした。別の画像を選択してください。'
    } else {
      pageError.value = errorMessage(cause, '画像の準備または解析に失敗しました。')
    }
  } finally {
    input.value = ''
  }
}

const findNearbyPlaces = async () => {
  placeError.value = ''
  const position = await requestPosition()
  if (!position) {
    places.value = []
    selectedPlaceId.value = ''
    placeError.value = '位置情報を取得できませんでした。店名を手入力して記録できます。'
    return
  }

  try {
    places.value = await searchPlaces(position.lat, position.lng)
    selectedPlaceId.value = ''
    if (!places.value.length) placeError.value = '近くの店候補が見つかりませんでした。店名を手入力してください。'
  } catch (cause) {
    places.value = []
    selectedPlaceId.value = ''
    placeError.value = errorMessage(cause, '近くの店を検索できませんでした。店名を手入力できます。')
  }
}

const attributionView = (attribution: unknown) => {
  if (typeof attribution === 'string') return { label: attribution, url: '' }
  if (!attribution || typeof attribution !== 'object') return { label: String(attribution), url: '' }
  const data = attribution as Record<string, unknown>
  const rawUrl = [data.uri, data.provider_uri, data.providerUri].find(value => typeof value === 'string')
  const labels = Object.entries(data)
    .filter(([key, value]) => !['uri', 'provider_uri', 'providerUri'].includes(key) && typeof value === 'string')
    .map(([, value]) => value as string)
  return {
    label: labels.join(' · ') || JSON.stringify(attribution),
    url: typeof rawUrl === 'string' && rawUrl.startsWith('https://') ? rawUrl : '',
  }
}

const handleSubmit = async () => {
  if (!analysisId.value || !brandText.value.trim()) {
    pageError.value = '銘柄名を入力してください。'
    return
  }

  pageError.value = ''
  saving.value = true
  try {
    const payload = buildDrinkLogPayload({
      analysisId: analysisId.value,
      candidateIndex: selectedCandidateIndex.value,
      brandText: brandText.value,
      servingStyle: servingStyle.value,
      storeName: storeName.value,
      placeId: selectedPlaceId.value,
      notes: notes.value,
      rating: rating.value,
    })
    const created = await createLog(payload)
    upsertLog(created)
    await navigateTo('/logs')
  } catch (cause) {
    pageError.value = errorMessage(cause, '記録の保存に失敗しました。')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-2xl px-4 sm:px-0">
    <div class="mb-6">
      <p class="text-sm font-medium text-amber-400">フォトファースト飲酒ログ</p>
      <h1 class="mt-1 text-3xl font-semibold text-amber-200">今日の一杯を記録</h1>
      <p class="mt-2 text-sm text-stone-300">写真から銘柄と飲み方を提案します。AIの提案はすべて修正できます。</p>
    </div>

    <form class="space-y-6" @submit.prevent="handleSubmit">
      <section class="rounded-lg border border-amber-700 bg-stone-800 p-5 shadow-lg">
        <label for="drink-photo" class="block text-sm font-medium text-amber-200">ボトルやグラスの写真 *</label>
        <input
          id="drink-photo"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          :disabled="isProcessing || saving"
          class="mt-3 block w-full text-sm text-stone-300 file:mr-4 file:rounded-md file:border-0 file:bg-amber-800 file:px-4 file:py-2 file:text-amber-100 hover:file:bg-amber-700 disabled:opacity-50"
          @change="handleFileSelection"
        />
        <p class="mt-2 text-xs text-stone-400">JPEG・PNG・WebP対応。HEIC/HEIFはJPEGへ変換してから選択してください。</p>

        <img v-if="previewUrl" :src="previewUrl" alt="選択した飲酒記録写真のプレビュー" class="mt-4 max-h-96 w-full rounded-lg bg-stone-900 object-contain" />

        <div v-if="phase === 'resizing' || phase === 'analyzing'" aria-live="polite" class="mt-4 rounded-md bg-stone-700 p-4">
          <div class="flex items-center gap-3 text-sm text-amber-100">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-amber-300 border-t-transparent"></span>
            {{ phase === 'resizing' ? '写真を準備しています…' : 'AIが銘柄と飲み方を解析しています…' }}
          </div>
          <div v-if="phase === 'analyzing'" class="mt-3 space-y-2" aria-hidden="true">
            <div class="h-4 w-2/3 animate-pulse rounded bg-stone-600"></div>
            <div class="h-4 w-1/2 animate-pulse rounded bg-stone-600"></div>
          </div>
        </div>

        <div v-if="phase === 'uploading'" class="mt-4" aria-live="polite">
          <div class="mb-1 flex justify-between text-xs text-amber-200"><span>アップロード中</span><span>{{ uploadProgress }}%</span></div>
          <div class="h-2 overflow-hidden rounded-full bg-stone-600"><div class="h-full bg-amber-500 transition-all" :style="{ width: `${uploadProgress}%` }"></div></div>
        </div>
      </section>

      <section v-if="previewUrl" class="space-y-6 rounded-lg border border-amber-700 bg-stone-800 p-5 shadow-lg">
        <div>
          <label for="brand-candidate" class="block text-sm font-medium text-amber-200">AIの銘柄候補</label>
          <select id="brand-candidate" v-model="candidateSelection" :disabled="phase !== 'ready' || !candidates.length" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 disabled:opacity-50" @change="handleCandidateSelection">
            <option value="">候補を使わず手入力</option>
            <option v-for="(candidate, index) in candidates" :key="`${candidate.brand_text}-${index}`" :value="String(index)">
              {{ candidate.brand_text }}（確度 {{ Math.round(candidate.confidence * 100) }}%）
            </option>
          </select>
          <p v-if="phase === 'ready' && !candidates.length" class="mt-2 rounded-md border border-amber-700 bg-amber-950/60 p-3 text-sm text-amber-200">
            銘柄候補を特定できませんでした。下の銘柄名を手入力してください。
          </p>
        </div>

        <div>
          <label for="brand-text" class="block text-sm font-medium text-amber-200">銘柄名 *</label>
          <input id="brand-text" v-model="brandText" required type="text" maxlength="200" placeholder="例: アードベッグ 10年" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400" @input="handleBrandInput" />
          <p class="mt-1 text-xs text-stone-400">候補の文字を編集すると、手入力の銘柄として保存します。</p>
        </div>

        <fieldset>
          <legend class="block text-sm font-medium text-amber-200">飲み方</legend>
          <div class="mt-2 flex flex-wrap gap-2">
            <label v-for="style in SERVING_STYLES" :key="style" class="cursor-pointer rounded-full border px-3 py-1.5 text-sm" :class="servingStyle === style ? 'border-amber-500 bg-amber-700 text-amber-100' : 'border-stone-500 bg-stone-600 text-amber-300'">
              <input v-model="servingStyle" class="sr-only" type="radio" name="serving-style" :value="style" />
              {{ styleLabels[style] }}
            </label>
          </div>
        </fieldset>

        <div>
          <div class="flex items-center justify-between gap-4">
            <h2 class="text-sm font-medium text-amber-200">飲んだ店</h2>
            <button type="button" :disabled="requestingLocation" class="rounded-md border border-amber-700 bg-stone-700 px-3 py-2 text-xs text-amber-100 hover:bg-stone-600 disabled:opacity-50" @click="findNearbyPlaces">
              {{ requestingLocation ? '位置情報を取得中…' : '近くの店を探す' }}
            </button>
          </div>
          <p class="mt-2 rounded-md border border-blue-900 bg-blue-950/50 p-3 text-xs leading-relaxed text-blue-200">{{ disclosure }}</p>
          <p v-if="placeError" role="status" class="mt-2 text-sm text-amber-300">{{ placeError }}</p>

          <div v-if="places.length" class="mt-3 space-y-2">
            <label v-for="place in places" :key="place.place_id" class="block cursor-pointer rounded-md border p-3" :class="selectedPlaceId === place.place_id ? 'border-amber-500 bg-amber-950/50' : 'border-stone-600 bg-stone-700'">
              <span class="flex gap-3">
                <input v-model="selectedPlaceId" type="radio" name="place" :value="place.place_id" class="mt-1 border-stone-500 bg-stone-800 text-amber-600" />
                <span class="min-w-0">
                  <span class="block font-medium text-amber-100">{{ place.display_name }}</span>
                  <span class="block text-xs text-stone-300">{{ place.formatted_address }}</span>
                </span>
              </span>
              <span class="mt-2 block border-t border-stone-600 pt-2 text-[11px] text-stone-300">
                <span translate="no" class="mr-2 whitespace-nowrap font-sans">Google Maps</span>
                <template v-for="(attribution, index) in place.attributions" :key="index">
                  <a v-if="attributionView(attribution).url" :href="attributionView(attribution).url" target="_blank" rel="noopener noreferrer" class="mr-2 underline">{{ attributionView(attribution).label }}</a>
                  <span v-else class="mr-2">{{ attributionView(attribution).label }}</span>
                </template>
              </span>
            </label>
            <button v-if="selectedPlace" type="button" class="text-xs text-stone-300 underline hover:text-amber-200" @click="selectedPlaceId = ''">店候補の選択を解除</button>
          </div>

          <label for="store-name" class="mt-4 block text-sm text-amber-200">記録に残す店名（任意・自由入力）</label>
          <input id="store-name" v-model="storeName" type="text" maxlength="200" placeholder="例: いつものバー" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400" />
          <p class="mt-1 text-xs text-stone-400">Googleの表示名は保存しません。選んだ店の place_id と、ここに入力した名前だけを保存します。</p>
        </div>

        <div>
          <div class="flex items-center justify-between">
            <label class="block text-sm font-medium text-amber-200">評価（任意）</label>
            <button v-if="rating" type="button" class="text-xs text-stone-300 underline" @click="rating = null">評価を外す</button>
          </div>
          <div class="mt-1 flex items-center">
            <button v-for="score in 5" :key="score" type="button" :aria-label="`評価 ${score}`" class="p-1 text-2xl" :class="rating && score <= rating ? 'text-amber-400' : 'text-stone-500'" @click="rating = score">★</button>
            <span class="ml-2 text-sm text-amber-300">{{ rating ? `${rating} / 5` : '評価なし' }}</span>
          </div>
        </div>

        <div>
          <label for="log-notes" class="block text-sm font-medium text-amber-200">ノート（任意）</label>
          <textarea id="log-notes" v-model="notes" rows="4" maxlength="2000" placeholder="味わいや、そのときのことを記録…" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400"></textarea>
        </div>

        <div class="rounded-md bg-stone-700 p-3 text-sm text-stone-200">
          <span class="font-medium text-amber-200">記録日時:</span> 今（保存時刻）
          <p class="mt-1 text-xs text-stone-400">この記録では日時を変更できません。</p>
        </div>
      </section>

      <p v-if="pageError" role="alert" class="rounded-md border border-red-800 bg-red-900/50 p-3 text-sm text-red-200">{{ pageError }}</p>

      <div v-if="previewUrl" class="flex justify-end gap-3">
        <NuxtLink to="/logs" class="rounded-md border border-stone-600 bg-stone-700 px-4 py-2 text-amber-200 hover:bg-stone-600">キャンセル</NuxtLink>
        <button type="submit" :disabled="!canSave" class="rounded-md border border-amber-700 bg-amber-800 px-5 py-2 font-medium text-amber-100 hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50">
          {{ saving ? '保存中…' : 'この一杯を記録' }}
        </button>
      </div>
    </form>
  </div>
</template>
