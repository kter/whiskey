<template>
  <div class="container mx-auto p-4">
    <h1 class="text-3xl font-bold mb-6 text-amber-200">ウイスキー一覧</h1>
    <div v-if="error" class="text-red-300 bg-red-900/50 p-4 rounded-lg mb-4 border border-red-800">
      {{ error }}
    </div>
    <div v-else-if="loading" class="text-amber-300 mb-4">
      読み込み中...
    </div>
    <div v-else>
      <div v-if="whiskeys.length === 0" class="text-amber-300 text-center py-8">
        ウィスキーデータがありません
      </div>
      <div v-else>
        <!-- ページ情報表示 -->
        <div v-if="pagination.total_items > 0" class="mb-4 text-amber-300 text-sm">
          {{ pagination.total_items }}件中 {{ ((currentPage - 1) * pageSize) + 1 }}〜{{ Math.min(currentPage * pageSize, pagination.total_items) }}件を表示
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div v-for="whiskey in whiskeys" :key="whiskey.id" class="bg-stone-800 border border-amber-700 p-6 rounded-lg shadow-lg hover:shadow-xl transition-all hover:border-amber-500">
            <h2 class="text-xl font-semibold text-amber-200 mb-2">{{ whiskey.name }}</h2>
            <p class="text-amber-100 mb-3">{{ whiskey.distillery }}</p>
            <p class="text-sm text-amber-300">
              評価: {{ whiskey.avg_rating?.toFixed(1) || '未評価' }}
              ({{ whiskey.review_count || 0 }}件のレビュー)
            </p>
          </div>
        </div>

        <!-- ページネーション -->
        <div v-if="pagination.total_pages > 1" class="mt-8">
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
  </div>
</template>

<script setup>
const config = useRuntimeConfig()
const whiskeys = ref([])
const loading = ref(false)
const error = ref(null)

// ページネーション状態
const currentPage = ref(1)
const pageSize = ref(12)
const pagination = ref({
  page: 1,
  limit: 12,
  total_items: 0,
  total_pages: 0,
  has_next: false,
  has_prev: false
})

// ウイスキーデータの取得
const loadWhiskeys = async (page = 1) => {
  try {
    loading.value = true
    error.value = null
    
    console.log('API Base URL:', config.public.apiBaseUrl)
    const apiUrl = `${config.public.apiBaseUrl}/api/whiskeys/ranking/?page=${page}&limit=${pageSize.value}`
    console.log('Fetching from:', apiUrl)
    
    const response = await fetch(apiUrl)
    console.log('Response status:', response.status)
    console.log('Response ok:', response.ok)
    
    if (!response.ok) {
      throw new Error(`APIの呼び出しに失敗しました (${response.status}: ${response.statusText})`)
    }
    
    const data = await response.json()
    console.log('Received data:', data)
    
    // レスポンス形式の判定
    if (Array.isArray(data)) {
      // 旧形式（後方互換性）
      whiskeys.value = data
    } else {
      // 新形式（ページネーション情報付き）
      whiskeys.value = data.rankings
      pagination.value = data.pagination
      currentPage.value = data.pagination.page
    }
    
    if (whiskeys.value.length === 0) {
      console.log('No whiskeys found in the response')
    } else {
      console.log(`Loaded ${whiskeys.value.length} whiskeys`)
    }
  } catch (e) {
    console.error('API Error:', e)
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// ページ変更
const changePage = (page) => {
  if (page >= 1 && page <= pagination.value.total_pages) {
    loadWhiskeys(page)
  }
}

// ページ番号の生成（最大5ページ表示）
const getPageNumbers = () => {
  const total = pagination.value.total_pages
  const current = currentPage.value
  const pages = []
  
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
  loadWhiskeys(1)
})
</script> 