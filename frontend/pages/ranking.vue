<script setup lang="ts">
import { ref } from 'vue'
import type { RankingItem } from '~/types/whiskey'
import { useWhiskeys } from '~/composables/useWhiskeys'

const { fetchRanking } = useWhiskeys()
const rankings = ref<RankingItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// 初期データ取得
onMounted(async () => {
  try {
    loading.value = true
    rankings.value = await fetchRanking()
  } catch (err) {
    error.value = 'ランキングの取得に失敗しました。'
    console.error(err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">
      人気ウイスキーランキング
    </h1>

    <!-- ローディング -->
    <div v-if="loading" class="mt-6 text-center">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-amber-500 border-t-transparent"></div>
    </div>

    <!-- エラー -->
    <div v-else-if="error" class="mt-6 bg-red-900/50 p-4 rounded-md border border-red-800">
      <div class="text-red-300">
        {{ error }}
      </div>
    </div>

    <!-- ランキング一覧 -->
    <div v-else class="mt-6">
      <div class="bg-stone-800 shadow-lg overflow-hidden sm:rounded-lg border border-amber-700">
        <ul role="list" class="divide-y divide-amber-700">
          <li
            v-for="(item, index) in rankings"
            :key="item.name"
            class="px-4 py-4 sm:px-6 hover:bg-stone-700 transition-colors"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center">
                <div
                  :class="[
                    index < 3 ? 'bg-amber-600 text-amber-100' : 'bg-stone-600 text-stone-200',
                    'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold'
                  ]"
                >
                  {{ index + 1 }}
                </div>
                <div class="ml-4">
                  <div class="text-sm font-medium text-amber-200">
                    {{ item.name }}
                  </div>
                  <div class="text-xs text-amber-100 mt-1">
                    {{ item.distillery }}
                  </div>
                  <div class="flex items-center mt-1">
                    <div class="flex">
                      <template v-for="i in 5" :key="i">
                        <svg
                          :class="[
                            i <= Math.round(item.avg_rating)
                              ? 'text-amber-400'
                              : 'text-stone-500',
                            'h-4 w-4 flex-shrink-0'
                          ]"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                        </svg>
                      </template>
                    </div>
                    <span class="ml-2 text-sm text-amber-300">
                      {{ item.avg_rating.toFixed(1) }} ({{ item.review_count }}件のレビュー)
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template> 