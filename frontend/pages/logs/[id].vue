<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '~/composables/useApi'
import {
  buildUpdateDrinkLogPayload,
  useDrinkLogs,
  type DrinkLog,
  type DrinkLogEditValues,
} from '~/composables/useDrinkLogs'
import { useAuth } from '~/composables/useAuth'
import { needsPlaceResolution, useVisiblePlaceResolver } from '~/composables/useVisiblePlaceResolver'
import { SERVING_STYLES, type ServingStyle } from '~/types/whiskey'
import { formatLocalLogDate, formatLocalLogTime, servingStyleLabel } from '~/utils/drinkLogs'

const route = useRoute()
const router = useRouter()
const logId = computed(() => String(route.params.id || ''))
const { currentUserId, waitForAuthReady } = useAuth()
const { getLog, updateLog, deleteLog, upsertLog, removeLog } = useDrinkLogs()
const { resolvedPlaces, enqueue: enqueuePlaces } = useVisiblePlaceResolver()

const log = ref<DrinkLog | null>(null)
const initialLoading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const loadError = ref('')
const actionError = ref('')
const editing = ref(false)
const showDeleteConfirmation = ref(false)
const lightbox = reactive({
  open: false,
  src: '',
  alt: '',
})
const form = reactive<DrinkLogEditValues>({
  brandText: '',
  servingStyle: 'NEAT',
  storeName: '',
  placeId: undefined,
  notes: '',
  rating: null,
})

const styleLabels: Record<ServingStyle, string> = {
  NEAT: 'ストレート',
  ROCKS: 'ロック',
  WATER: '水割り・トワイスアップ',
  SODA: 'ハイボール',
  COCKTAIL: 'カクテル',
}

const isOwner = computed(() => Boolean(log.value && currentUserId.value && log.value.user_id === currentUserId.value))
const brandSourceLabels: Record<string, string> = { ai: 'AI候補', manual: '手入力', matched: '銘柄データ一致' }
const brandSourceLabel = computed(() => brandSourceLabels[log.value?.brand_source || ''] || '不明')

const errorMessage = (cause: unknown, fallback: string) => cause instanceof Error && cause.message
  ? cause.message
  : fallback

const copyLogToForm = (record: DrinkLog) => {
  form.brandText = record.brand_text
  form.storeName = record.store.name
  form.placeId = record.store.place_id
  form.servingStyle = record.serving_style || 'NEAT'
  form.rating = record.rating || null
  form.notes = record.notes || ''
}

/**
 * Resolve straight away rather than waiting to scroll the row into view. This
 * page shows exactly one record, so deferring saves no Places call, and the
 * viewport trigger never fires at all while the tab is hidden.
 */
const resolveStore = (record: DrinkLog) => {
  if (!needsPlaceResolution(record)) return
  enqueuePlaces([{ log_id: record.id, place_id: record.store.place_id as string }])
}

const handleRefreshedImage = (refreshed: DrinkLog) => {
  log.value = refreshed
}

const openLightbox = () => {
  if (!log.value?.image_url) return
  lightbox.src = log.value.image_url
  lightbox.alt = `${log.value.brand_text}の記録写真`
  lightbox.open = true
}

const startEditing = () => {
  if (!log.value) return
  copyLogToForm(log.value)
  actionError.value = ''
  editing.value = true
}

const cancelEditing = () => {
  editing.value = false
  actionError.value = ''
}

const saveChanges = async () => {
  if (!log.value || !form.brandText.trim()) {
    actionError.value = '銘柄名を入力してください。'
    return
  }
  saving.value = true
  actionError.value = ''
  try {
    const updated = await updateLog(log.value.id, buildUpdateDrinkLogPayload(form))
    log.value = updated
    upsertLog(updated)
    editing.value = false
  } catch (cause) {
    actionError.value = errorMessage(cause, '記録の更新に失敗しました。')
  } finally {
    saving.value = false
  }
}

const confirmDelete = async () => {
  if (!log.value) return
  deleting.value = true
  actionError.value = ''
  try {
    await deleteLog(log.value.id)
    removeLog(log.value.id)
    await router.push('/logs')
  } catch (cause) {
    actionError.value = errorMessage(cause, '記録の削除に失敗しました。')
    showDeleteConfirmation.value = false
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  try {
    await waitForAuthReady()
    if (!currentUserId.value) {
      await navigateTo('/login')
      return
    }
    const record = await getLog(logId.value)
    log.value = record
    upsertLog(record)
    copyLogToForm(record)
    resolveStore(record)
  } catch (cause) {
    loadError.value = cause instanceof ApiError && cause.status === 404
      ? '記録が見つかりません。削除されたか、表示する権限がありません。'
      : errorMessage(cause, '記録の取得に失敗しました。')
  } finally {
    initialLoading.value = false
  }
})
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 sm:px-0">
    <NuxtLink to="/logs" class="text-sm text-amber-300 hover:text-amber-100">← タイムラインに戻る</NuxtLink>

    <div v-if="initialLoading" class="mt-10 text-center text-amber-300" aria-live="polite">記録を読み込んでいます…</div>
    <div v-else-if="loadError" class="mt-8 rounded-lg border border-red-800 bg-red-900/40 p-6">
      <p role="alert" class="text-red-200">{{ loadError }}</p>
      <NuxtLink to="/logs" class="mt-4 inline-block text-sm text-amber-200 underline">タイムラインを確認する</NuxtLink>
    </div>

    <article v-else-if="log" class="mt-6 overflow-hidden rounded-lg border border-amber-800 bg-stone-800 shadow-xl">
      <button
        type="button"
        :disabled="!log.image_url"
        aria-label="写真を拡大表示"
        class="block w-full cursor-zoom-in disabled:cursor-default"
        @click="openLightbox"
      >
        <DrinkLogImage
          :log="log"
          :alt="`${log.brand_text}の記録写真`"
          image-class="max-h-[42rem] w-full bg-stone-950 object-contain"
          placeholder-class="flex min-h-72 w-full items-center justify-center bg-stone-950"
          @refreshed="handleRefreshedImage"
        />
      </button>

      <div class="p-5 sm:p-7">
        <template v-if="!editing">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p class="text-sm text-amber-400">{{ brandSourceLabel }}</p>
              <h1 class="mt-1 text-3xl font-semibold text-amber-100">{{ log.brand_text }}</h1>
            </div>
            <p v-if="log.rating" :aria-label="`評価 ${log.rating} / 5`" class="text-xl text-amber-400">{{ '★'.repeat(log.rating) }}<span class="text-stone-600">{{ '☆'.repeat(5 - log.rating) }}</span></p>
          </div>

          <dl class="mt-7 grid gap-5 sm:grid-cols-2">
            <div>
              <dt class="text-xs uppercase tracking-wide text-stone-400">日時</dt>
              <dd class="mt-1 text-amber-100"><time :datetime="log.datetime">{{ formatLocalLogDate(log.datetime) }} {{ formatLocalLogTime(log.datetime) }}</time></dd>
            </div>
            <div :data-log-id="log.id" :data-place-id="log.store.place_id || undefined">
              <dt class="text-xs uppercase tracking-wide text-stone-400">場所</dt>
              <dd class="mt-1 text-amber-100"><DrinkLogStoreDisplay :log="log" :resolved-place="resolvedPlaces[log.id]" /></dd>
            </div>
            <div>
              <dt class="text-xs uppercase tracking-wide text-stone-400">飲み方</dt>
              <dd class="mt-1 text-amber-100">{{ servingStyleLabel(log.serving_style) }}</dd>
            </div>
          </dl>

          <section class="mt-7">
            <h2 class="text-sm font-medium text-amber-200">ノート</h2>
            <p class="mt-2 whitespace-pre-wrap text-stone-200">{{ log.notes || 'ノートはありません。' }}</p>
          </section>

          <p v-if="actionError" role="alert" class="mt-6 rounded-md border border-red-800 bg-red-900/50 p-3 text-sm text-red-200">{{ actionError }}</p>
          <div v-if="isOwner" class="mt-7 flex justify-end gap-3">
            <button type="button" class="rounded-md border border-amber-700 bg-amber-800 px-4 py-2 text-amber-100 hover:bg-amber-700" @click="startEditing">編集</button>
            <button type="button" class="rounded-md border border-red-800 bg-red-950 px-4 py-2 text-red-200 hover:bg-red-900" @click="showDeleteConfirmation = true">削除</button>
          </div>
        </template>

        <form v-else class="space-y-6" @submit.prevent="saveChanges">
          <div>
            <label for="edit-brand" class="block text-sm font-medium text-amber-200">銘柄名 *</label>
            <input id="edit-brand" v-model="form.brandText" required maxlength="200" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
            <p class="mt-1 text-xs text-stone-400">保存すると手入力の銘柄として扱われます。</p>
          </div>
          <div>
            <label for="edit-store" class="block text-sm font-medium text-amber-200">店名</label>
            <input id="edit-store" v-model="form.storeName" maxlength="200" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
          </div>
          <fieldset>
            <legend class="text-sm font-medium text-amber-200">飲み方</legend>
            <div class="mt-2 flex flex-wrap gap-2">
              <label v-for="style in SERVING_STYLES" :key="style" class="cursor-pointer rounded-full border px-3 py-1.5 text-sm" :class="form.servingStyle === style ? 'border-amber-500 bg-amber-700 text-amber-100' : 'border-stone-500 bg-stone-700 text-stone-300'">
                <input v-model="form.servingStyle" class="sr-only" type="radio" name="edit-serving-style" :value="style" />{{ styleLabels[style] }}
              </label>
            </div>
          </fieldset>
          <div>
            <span class="block text-sm font-medium text-amber-200">評価</span>
            <div class="mt-1 flex items-center">
              <button v-for="score in 5" :key="score" type="button" :aria-label="`評価 ${score}`" class="p-1 text-2xl" :class="form.rating && score <= form.rating ? 'text-amber-400' : 'text-stone-500'" @click="form.rating = score">★</button>
              <span class="ml-2 text-sm text-stone-300">{{ form.rating ? `${form.rating} / 5` : '評価なし' }}</span>
            </div>
          </div>
          <div>
            <label for="edit-notes" class="block text-sm font-medium text-amber-200">ノート</label>
            <textarea id="edit-notes" v-model="form.notes" rows="5" maxlength="2000" class="mt-2 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100"></textarea>
          </div>
          <p v-if="actionError" role="alert" class="rounded-md border border-red-800 bg-red-900/50 p-3 text-sm text-red-200">{{ actionError }}</p>
          <div class="flex justify-end gap-3">
            <button type="button" :disabled="saving" class="rounded-md border border-stone-600 bg-stone-700 px-4 py-2 text-stone-200" @click="cancelEditing">キャンセル</button>
            <button type="submit" :disabled="saving || !form.brandText.trim()" class="rounded-md border border-amber-700 bg-amber-800 px-5 py-2 font-medium text-amber-100 disabled:opacity-50">{{ saving ? '保存中…' : '変更を保存' }}</button>
          </div>
        </form>
      </div>
    </article>

    <div v-if="showDeleteConfirmation" class="fixed inset-0 z-20 flex items-center justify-center bg-black/75 px-4" role="dialog" aria-modal="true" aria-labelledby="delete-log-title">
      <div class="w-full max-w-md rounded-lg border border-red-900 bg-stone-800 p-6 shadow-2xl">
        <h2 id="delete-log-title" class="text-lg font-semibold text-red-200">この記録を削除しますか？</h2>
        <p class="mt-2 text-sm text-stone-200">この操作は取り消せません。写真を含む記録が削除されます。</p>
        <div class="mt-6 flex justify-end gap-3">
          <button type="button" :disabled="deleting" class="rounded-md bg-stone-700 px-4 py-2 text-stone-200 disabled:opacity-50" @click="showDeleteConfirmation = false">キャンセル</button>
          <button type="button" :disabled="deleting" class="rounded-md bg-red-900 px-4 py-2 font-medium text-red-100 disabled:opacity-50" @click="confirmDelete">{{ deleting ? '削除中…' : '削除する' }}</button>
        </div>
      </div>
    </div>

    <ImageLightbox v-model:open="lightbox.open" :src="lightbox.src" :alt="lightbox.alt" />
  </div>
</template>
