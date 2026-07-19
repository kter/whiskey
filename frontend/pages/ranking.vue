<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useWhiskeys } from '~/composables/useWhiskeys'
import type { RankingItem } from '~/types/whiskey'

const { fetchRanking } = useWhiskeys()
const rankings = ref<RankingItem[]>([])
const loading = ref(false)
const error = ref('')
const nextPage = ref<number | null>(1)

const loadMore = async () => {
  if (!nextPage.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await fetchRanking({ page: nextPage.value, limit: 20 })
    if (Array.isArray(data)) {
      rankings.value = [...rankings.value, ...data]
      nextPage.value = null
    } else {
      rankings.value = [...rankings.value, ...data.rankings]
      nextPage.value = data.pagination.has_next ? data.pagination.page + 1 : null
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'ランキングの取得に失敗しました。'
  } finally {
    loading.value = false
  }
}

onMounted(() => void loadMore())
</script>

<template>
  <div>
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">人気ウイスキーランキング</h1>
    <p v-if="error" role="alert" class="mb-4 text-red-300 bg-red-900/50 p-4 rounded-md border border-red-800">{{ error }}</p>
    <div class="bg-stone-800 shadow-lg overflow-hidden sm:rounded-lg border border-amber-700">
      <ul class="divide-y divide-amber-700">
        <li v-for="(item, index) in rankings" :key="item.id" class="p-5 flex items-center gap-4">
          <span class="w-10 h-10 flex items-center justify-center rounded-full bg-amber-800 text-amber-100 font-bold">{{ index + 1 }}</span>
          <div class="flex-1"><h2 class="text-lg font-medium text-amber-200">{{ item.name }}</h2><p class="text-sm text-amber-300">{{ item.distillery }}</p></div>
          <div class="text-right text-amber-300"><div class="text-amber-400">★ {{ item.avg_rating.toFixed(1) }}</div><div class="text-xs">{{ item.review_count }}件</div></div>
        </li>
      </ul>
      <p v-if="!loading && rankings.length === 0" class="p-8 text-center text-amber-300">ランキングを集計中です。</p>
    </div>
    <div v-if="nextPage" class="mt-6 text-center"><button :disabled="loading" class="px-5 py-2 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50" @click="loadMore">{{ loading ? '読み込み中...' : 'さらに読み込む' }}</button></div>
  </div>
</template>
