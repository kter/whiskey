<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { RankingItem } from '~/types/whiskey'
import { useWhiskeys } from '~/composables/useWhiskeys'

const { fetchRanking } = useWhiskeys()
const rankings = ref<RankingItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// ページネーション状態
const currentPage = ref(1)
const pageSize = ref(20)
const pagination = ref({
  page: 1,
  limit: 20,
  total_items: 0,
  total_pages: 0,
  has_next: false,
  has_prev: false
})

// ランキングデータの取得
const loadRankings = async (page: number = 1) => {
  try {
    loading.value = true
    error.value = null
    
    const data = await fetchRanking({ page, limit: pageSize.value })
    
    // レスポンス形式の判定
    if (Array.isArray(data)) {
      // 旧形式（後方互換性）
      rankings.value = data
    } else {
      // 新形式（ページネーション情報付き）
      rankings.value = data.rankings
      pagination.value = data.pagination
      currentPage.value = data.pagination.page
    }
  } catch (err) {
    error.value = 'ランキングの取得に失敗しました。'
    console.error(err)
  } finally {
    loading.value = false
  }
}

// ページ変更
const changePage = (page: number) => {
  if (page >= 1 && page <= pagination.value.total_pages) {
    loadRankings(page)
  }
}

// ページ番号の生成（最大5ページ表示）
const getPageNumbers = () => {
  const total = pagination.value.total_pages
  const current = currentPage.value
  const pages: (number | string)[] = []
  
  if (total <= 7) {
    // 総ページ数が7以下の場合は全て表示
    for (let i = 1; i <= total; i++) {
      pages.push(i)
    }
  } else {
    // 最初のページ
    pages.push(1)
    
    if (current > 4) {
      pages.push('...')
    }
    
    // 現在のページ周辺
    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)
    
    for (let i = start; i <= end; i++) {
      pages.push(i)
    }
    
    if (current < total - 3) {
      pages.push('...')
    }
    
    // 最後のページ
    if (total > 1) {
      pages.push(total)
    }
  }
  
  return pages
}

// 初期データ取得
onMounted(() => {
  loadRankings(1)
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
      <!-- ページ情報表示 -->
      <div v-if="pagination.total_items > 0" class="mb-4 text-amber-300 text-sm">
        {{ pagination.total_items }}件中 {{ ((currentPage - 1) * pageSize) + 1 }}〜{{ Math.min(currentPage * pageSize, pagination.total_items) }}件を表示
      </div>

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
                    ((currentPage - 1) * pageSize + index) < 3 ? 'bg-amber-600 text-amber-100' : 'bg-stone-600 text-stone-200',
                    'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold'
                  ]"
                >
                  {{ (currentPage - 1) * pageSize + index + 1 }}
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

      <!-- ページネーション -->
      <div v-if="pagination.total_pages > 1" class="mt-6">
        <nav class="flex items-center justify-between px-4 py-3 bg-stone-800 border border-amber-700 rounded-lg">
          <div class="flex flex-1 justify-between sm:hidden">
            <!-- モバイル用ナビゲーション -->
            <button
              @click="changePage(currentPage - 1)"
              :disabled="!pagination.has_prev"
              :class="[
                pagination.has_prev
                  ? 'bg-amber-600 text-amber-100 hover:bg-amber-500'
                  : 'bg-stone-600 text-stone-400 cursor-not-allowed',
                'relative inline-flex items-center px-4 py-2 text-sm font-medium rounded-md'
              ]"
            >
              前へ
            </button>
            <span class="text-amber-300 px-4 py-2 text-sm">
              {{ currentPage }} / {{ pagination.total_pages }}
            </span>
            <button
              @click="changePage(currentPage + 1)"
              :disabled="!pagination.has_next"
              :class="[
                pagination.has_next
                  ? 'bg-amber-600 text-amber-100 hover:bg-amber-500'
                  : 'bg-stone-600 text-stone-400 cursor-not-allowed',
                'relative inline-flex items-center px-4 py-2 text-sm font-medium rounded-md'
              ]"
            >
              次へ
            </button>
          </div>

          <div class="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
            <div>
              <p class="text-sm text-amber-300">
                ページ <span class="font-medium">{{ currentPage }}</span> / <span class="font-medium">{{ pagination.total_pages }}</span>
              </p>
            </div>
            <div>
              <nav class="isolate inline-flex -space-x-px rounded-md shadow-sm">
                <!-- 前へボタン -->
                <button
                  @click="changePage(currentPage - 1)"
                  :disabled="!pagination.has_prev"
                  :class="[
                    pagination.has_prev
                      ? 'bg-amber-600 text-amber-100 hover:bg-amber-500'
                      : 'bg-stone-600 text-stone-400 cursor-not-allowed',
                    'relative inline-flex items-center rounded-l-md px-2 py-2 text-sm font-medium ring-1 ring-inset ring-amber-700'
                  ]"
                >
                  ←
                </button>

                <!-- ページ番号 -->
                <template v-for="page in getPageNumbers()" :key="page">
                  <button
                    v-if="page !== '...'"
                    @click="changePage(Number(page))"
                    :class="[
                      page === currentPage
                        ? 'bg-amber-600 text-amber-100'
                        : 'bg-stone-700 text-amber-300 hover:bg-stone-600',
                      'relative inline-flex items-center px-4 py-2 text-sm font-medium ring-1 ring-inset ring-amber-700'
                    ]"
                  >
                    {{ page }}
                  </button>
                  <span
                    v-else
                    class="relative inline-flex items-center px-4 py-2 text-sm font-medium text-amber-300 ring-1 ring-inset ring-amber-700 bg-stone-700"
                  >
                    ...
                  </span>
                </template>

                <!-- 次へボタン -->
                <button
                  @click="changePage(currentPage + 1)"
                  :disabled="!pagination.has_next"
                  :class="[
                    pagination.has_next
                      ? 'bg-amber-600 text-amber-100 hover:bg-amber-500'
                      : 'bg-stone-600 text-stone-400 cursor-not-allowed',
                    'relative inline-flex items-center rounded-r-md px-2 py-2 text-sm font-medium ring-1 ring-inset ring-amber-700'
                  ]"
                >
                  →
                </button>
              </nav>
            </div>
          </div>
        </nav>
      </div>
    </div>
  </div>
</template> 