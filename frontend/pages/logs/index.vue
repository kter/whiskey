<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type ComponentPublicInstance } from 'vue'
import { mergeDrinkLogs, sortDrinkLogs, useDrinkLogs, type DrinkLog } from '~/composables/useDrinkLogs'
import { useAuth } from '~/composables/useAuth'
import { useVisiblePlaceResolver } from '~/composables/useVisiblePlaceResolver'
import { formatLocalLogTime, groupDrinkLogsByLocalDate, servingStyleLabel } from '~/utils/drinkLogs'

const PAGE_SIZE = 20
const route = useRoute()
const router = useRouter()
const { currentUserId, waitForAuthReady } = useAuth()
const { logs, listLogs, upsertLogs } = useDrinkLogs()
const { resolvedPlaces, register: registerPlace } = useVisiblePlaceResolver()

const visibleLogs = ref<DrinkLog[]>([])
const nextToken = ref<string | null>(null)
const initialLoading = ref(true)
const loadingMore = ref(false)
const pageError = ref('')
const brandInput = ref(typeof route.query.brand === 'string' ? route.query.brand : '')
const storeInput = ref(typeof route.query.store === 'string' ? route.query.store : '')
const activeBrand = ref(brandInput.value.trim())
const activeStore = ref(storeInput.value.trim())
const sentinel = ref<HTMLElement | null>(null)
let sentinelObserver: IntersectionObserver | null = null
let requestGeneration = 0

const groups = computed(() => groupDrinkLogsByLocalDate(visibleLogs.value))
const hasFilters = computed(() => Boolean(activeBrand.value || activeStore.value))

const errorMessage = (cause: unknown, fallback: string) => cause instanceof Error && cause.message
  ? cause.message
  : fallback

const loadLogs = async (append = false) => {
  if (append && (!nextToken.value || loadingMore.value)) return
  const generation = append ? requestGeneration : ++requestGeneration
  if (append) loadingMore.value = true
  else {
    initialLoading.value = true
    loadingMore.value = false
  }
  pageError.value = ''

  try {
    const response = await listLogs({
      limit: PAGE_SIZE,
      ...(append ? { next_token: nextToken.value } : {}),
      ...(activeBrand.value ? { brand: activeBrand.value } : {}),
      ...(activeStore.value ? { store: activeStore.value } : {}),
    })
    if (generation !== requestGeneration) return
    upsertLogs(response.results)
    if (append) {
      visibleLogs.value = mergeDrinkLogs(visibleLogs.value, response.results)
    } else if (hasFilters.value) {
      visibleLogs.value = sortDrinkLogs(response.results)
    } else {
      visibleLogs.value = mergeDrinkLogs(logs.value, response.results)
    }
    nextToken.value = response.next_token
  } catch (cause) {
    if (generation === requestGeneration) pageError.value = errorMessage(cause, '記録一覧の取得に失敗しました。')
  } finally {
    if (generation === requestGeneration) {
      initialLoading.value = false
      loadingMore.value = false
    }
  }
}

const applyFilters = async () => {
  activeBrand.value = brandInput.value.trim()
  activeStore.value = storeInput.value.trim()
  nextToken.value = null
  visibleLogs.value = []
  await router.replace({
    query: {
      ...(activeBrand.value ? { brand: activeBrand.value } : {}),
      ...(activeStore.value ? { store: activeStore.value } : {}),
    },
  })
  await loadLogs()
}

const removeFilter = async (filter: 'brand' | 'store') => {
  if (filter === 'brand') brandInput.value = ''
  else storeInput.value = ''
  await applyFilters()
}

const registerStore = (target: Element | ComponentPublicInstance | null, log: DrinkLog) => {
  registerPlace(target, log)
}

const updateVisibleLog = (refreshed: DrinkLog) => {
  visibleLogs.value = mergeDrinkLogs(visibleLogs.value, [refreshed])
}

onMounted(async () => {
  sentinelObserver = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) void loadLogs(true)
  }, { rootMargin: '320px 0px' })
  if (sentinel.value) sentinelObserver?.observe(sentinel.value)

  await waitForAuthReady()
  if (!currentUserId.value) {
    await navigateTo('/login')
    return
  }
  await loadLogs()
})

onBeforeUnmount(() => sentinelObserver?.disconnect())
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 sm:px-0">
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-amber-400">あなたの一杯</p>
        <h1 class="mt-1 text-3xl font-semibold text-amber-200">飲酒タイムライン</h1>
      </div>
      <NuxtLink to="/logs/new" class="rounded-md border border-amber-700 bg-amber-800 px-4 py-2 font-medium text-amber-100 hover:bg-amber-700">
        一杯を記録
      </NuxtLink>
    </header>

    <form class="mt-6 rounded-lg border border-stone-700 bg-stone-800 p-4" @submit.prevent="applyFilters">
      <div class="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label class="text-sm text-amber-200">
          銘柄で絞り込む
          <input v-model="brandInput" name="brand" type="search" placeholder="例: 山崎" class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400" />
        </label>
        <label class="text-sm text-amber-200">
          店名で絞り込む
          <input v-model="storeInput" name="store" type="search" placeholder="例: バー" class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400" />
        </label>
        <button type="submit" :disabled="initialLoading" class="rounded-md border border-amber-700 bg-stone-700 px-4 py-2 text-amber-100 hover:bg-stone-600 disabled:opacity-50">適用</button>
      </div>
      <div v-if="hasFilters" class="mt-3 flex flex-wrap gap-2" aria-label="適用中のフィルター">
        <button v-if="activeBrand" type="button" class="rounded-full border border-amber-600 bg-amber-950 px-3 py-1 text-xs text-amber-200" @click="removeFilter('brand')">
          銘柄: {{ activeBrand }} ×
        </button>
        <button v-if="activeStore" type="button" class="rounded-full border border-amber-600 bg-amber-950 px-3 py-1 text-xs text-amber-200" @click="removeFilter('store')">
          店: {{ activeStore }} ×
        </button>
      </div>
    </form>

    <p v-if="pageError" role="alert" class="mt-6 rounded-md border border-red-800 bg-red-900/50 p-4 text-red-200">{{ pageError }}</p>
    <div v-if="initialLoading && !visibleLogs.length" class="mt-10 text-center text-amber-300" aria-live="polite">記録を読み込んでいます…</div>

    <div v-else-if="!visibleLogs.length && !pageError" class="mt-10 rounded-lg border border-amber-800 bg-stone-800 p-8 text-center">
      <p class="text-lg text-amber-100">まだ記録がありません。最初の一杯を記録しましょう</p>
      <NuxtLink to="/logs/new" class="mt-5 inline-block rounded-md bg-amber-800 px-5 py-2 font-medium text-amber-100 hover:bg-amber-700">最初の一杯を記録</NuxtLink>
    </div>

    <div v-else class="mt-8 space-y-10">
      <section v-for="group in groups" :key="group.key" :aria-labelledby="`date-${group.key}`">
        <h2 :id="`date-${group.key}`" class="sticky top-0 z-[1] border-b border-amber-800 bg-stone-900/95 py-2 text-lg font-semibold text-amber-200 backdrop-blur">{{ group.label }}</h2>
        <ol class="mt-4 space-y-4">
          <li v-for="log in group.logs" :key="log.id">
            <article class="grid grid-cols-[7rem_1fr] gap-4 overflow-hidden rounded-lg border border-stone-700 bg-stone-800 p-3 shadow-md transition hover:border-amber-700 sm:grid-cols-[10rem_1fr]">
              <NuxtLink :to="`/logs/${encodeURIComponent(log.id)}`" :aria-label="`${log.brand_text}の詳細を見る`">
                <DrinkLogImage
                  :log="log"
                  :alt="`${log.brand_text}の記録写真`"
                  image-class="h-28 w-28 rounded-md bg-stone-900 object-cover sm:h-36 sm:w-40"
                  placeholder-class="flex h-28 w-28 items-center justify-center rounded-md bg-stone-900 sm:h-36 sm:w-40"
                  @refreshed="updateVisibleLog"
                />
              </NuxtLink>
              <div class="min-w-0 py-1">
                <div class="flex items-start justify-between gap-3">
                  <p class="text-sm text-stone-300"><time :datetime="log.datetime">{{ formatLocalLogTime(log.datetime) }}</time></p>
                  <p v-if="log.rating" :aria-label="`評価 ${log.rating} / 5`" class="shrink-0 text-amber-400">{{ '★'.repeat(log.rating) }}</p>
                </div>
                <h3 class="mt-2 truncate text-lg font-semibold text-amber-100">
                  <NuxtLink :to="`/logs/${encodeURIComponent(log.id)}`" class="hover:text-amber-300">{{ log.brand_text }}</NuxtLink>
                </h3>
                <div
                  :ref="target => registerStore(target, log)"
                  :data-log-id="log.id"
                  :data-place-id="log.store.place_id || undefined"
                  class="mt-2 text-sm text-stone-200"
                >
                  <DrinkLogStoreDisplay :log="log" :resolved-place="resolvedPlaces[log.id]" />
                </div>
                <p class="mt-2 inline-block rounded-full bg-stone-700 px-2.5 py-1 text-xs text-amber-200">{{ servingStyleLabel(log.serving_style) }}</p>
              </div>
            </article>
          </li>
        </ol>
      </section>
    </div>

    <div ref="sentinel" class="h-8" aria-hidden="true"></div>
    <p v-if="loadingMore" class="pb-4 text-center text-sm text-amber-300" aria-live="polite">続きを読み込んでいます…</p>
    <p v-else-if="visibleLogs.length && !nextToken" class="pb-4 text-center text-xs text-stone-500">すべての記録を表示しました</p>
  </div>
</template>
