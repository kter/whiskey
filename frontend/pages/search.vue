<script setup lang="ts">
import { ref, computed } from 'vue'
import { useWhiskeySearch, type WhiskeySuggestion, type SearchFilters } from '~/composables/useWhiskeySearch'
import WhiskeySearchInput from '~/components/WhiskeySearchInput.vue'

const {
  searchFilters,
  advancedResults,
  isAdvancedSearching,
  advancedSearchError,
  performAdvancedSearch,
  clearAdvancedSearch,
  isMobile
} = useWhiskeySearch()

const searchPerformed = ref(false)
const selectedResult = ref<WhiskeySuggestion | null>(null)

// 検索実行
const handleSearch = async () => {
  try {
    searchPerformed.value = true
    await performAdvancedSearch(searchFilters.value)
  } catch (error) {
    console.error('Search error:', error)
  }
}

// 検索フィルターのリセット
const resetSearch = () => {
  clearAdvancedSearch()
  searchPerformed.value = false
  selectedResult.value = null
}

// 検索可能かどうか
const canSearch = computed(() => {
  return searchFilters.value.name || 
         searchFilters.value.distillery || 
         searchFilters.value.region || 
         searchFilters.value.type
})

// 結果の詳細表示
const showResultDetail = (result: WhiskeySuggestion) => {
  selectedResult.value = result
}

const closeResultDetail = () => {
  selectedResult.value = null
}

// レビュー作成用の選択
const selectForReview = (result: WhiskeySuggestion) => {
  const whiskeyName = result.name_ja || result.name_en
  const distillery = result.distillery_ja || result.distillery_en
  
  // レビュー作成ページにクエリパラメータで渡す
  navigateTo({
    path: '/reviews/new',
    query: {
      whiskey_name: whiskeyName,
      distillery: distillery
    }
  })
}
</script>

<template>
  <div class="max-w-6xl mx-auto">
    <div class="mb-6">
      <h1 class="text-3xl font-semibold text-amber-200 mb-2">
        ウイスキー検索
      </h1>
      <p class="text-amber-300">
        条件を指定してウイスキーを検索できます。見つけたウイスキーはレビュー作成時に簡単に選択できます。
      </p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- 検索フィルター -->
      <div class="lg:col-span-1">
        <div class="bg-stone-800 p-6 rounded-lg shadow-lg border border-amber-700 sticky top-6">
          <h2 class="text-xl font-medium text-amber-200 mb-4">検索条件</h2>
          
          <div class="space-y-4">
            <!-- ウイスキー名 -->
            <div>
              <label class="block text-sm font-medium text-amber-200 mb-2">
                ウイスキー名
              </label>
              <input
                v-model="searchFilters.name"
                type="text"
                class="w-full px-3 py-2 text-amber-100 bg-stone-700 border border-amber-700 rounded-md focus:ring-2 focus:ring-amber-500 focus:border-amber-500 placeholder-amber-400"
                placeholder="例: 山崎, マッカラン"
              >
            </div>

            <!-- 蒸留所名 -->
            <div>
              <label class="block text-sm font-medium text-amber-200 mb-2">
                蒸留所名
              </label>
              <input
                v-model="searchFilters.distillery"
                type="text"
                class="w-full px-3 py-2 text-amber-100 bg-stone-700 border border-amber-700 rounded-md focus:ring-2 focus:ring-amber-500 focus:border-amber-500 placeholder-amber-400"
                placeholder="例: サントリー, マッカラン"
              >
            </div>

            <!-- 地域 -->
            <div>
              <label class="block text-sm font-medium text-amber-200 mb-2">
                地域
              </label>
              <input
                v-model="searchFilters.region"
                type="text"
                class="w-full px-3 py-2 text-amber-100 bg-stone-700 border border-amber-700 rounded-md focus:ring-2 focus:ring-amber-500 focus:border-amber-500 placeholder-amber-400"
                placeholder="例: スペイサイド, ハイランド"
              >
            </div>

            <!-- タイプ -->
            <div>
              <label class="block text-sm font-medium text-amber-200 mb-2">
                タイプ
              </label>
              <input
                v-model="searchFilters.type"
                type="text"
                class="w-full px-3 py-2 text-amber-100 bg-stone-700 border border-amber-700 rounded-md focus:ring-2 focus:ring-amber-500 focus:border-amber-500 placeholder-amber-400"
                placeholder="例: シングルモルト, ブレンデッド"
              >
            </div>
          </div>

          <!-- 検索ボタン -->
          <div class="mt-6 space-y-3">
            <button
              @click="handleSearch"
              :disabled="!canSearch || isAdvancedSearching"
              class="w-full inline-flex justify-center items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span v-if="isAdvancedSearching" class="inline-flex items-center">
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                検索中...
              </span>
              <span v-else>検索実行</span>
            </button>

            <button
              @click="resetSearch"
              class="w-full inline-flex justify-center items-center px-4 py-2 border border-stone-600 text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors"
            >
              リセット
            </button>
          </div>

          <!-- 検索のヒント -->
          <div class="mt-6 p-4 bg-amber-900/20 border border-amber-800 rounded-lg">
            <h3 class="text-sm font-medium text-amber-200 mb-2">検索のヒント</h3>
            <ul class="text-xs text-amber-300 space-y-1">
              <li>• 一つ以上の条件を入力してください</li>
              <li>• 部分一致で検索できます</li>
              <li>• 日本語と英語どちらでも検索可能</li>
              <li>• 条件を組み合わせて絞り込めます</li>
            </ul>
          </div>
        </div>
      </div>

      <!-- 検索結果 -->
      <div class="lg:col-span-2">
        <!-- エラーメッセージ -->
        <div v-if="advancedSearchError" class="mb-6 p-4 bg-red-900/50 border border-red-800 rounded-lg">
          <p class="text-red-300">{{ advancedSearchError }}</p>
        </div>

        <!-- 検索前の状態 -->
        <div v-if="!searchPerformed" class="text-center py-12">
          <div class="text-amber-400 mb-4">
            <svg class="h-16 w-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
            </svg>
          </div>
          <h3 class="text-lg font-medium text-amber-200 mb-2">検索条件を入力してください</h3>
          <p class="text-amber-400">左側の検索フォームに条件を入力して「検索実行」ボタンを押してください。</p>
        </div>

        <!-- 検索結果なし -->
        <div v-else-if="advancedResults.length === 0 && !isAdvancedSearching" class="text-center py-12">
          <div class="text-amber-400 mb-4">
            <svg class="h-16 w-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M9.172 16.172a4 4 0 015.656 0M9 12h6m-6-4h6m2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
          <h3 class="text-lg font-medium text-amber-200 mb-2">該当するウイスキーが見つかりませんでした</h3>
          <p class="text-amber-400">検索条件を変更して再度お試しください。</p>
        </div>

        <!-- 検索結果一覧 -->
        <div v-else-if="advancedResults.length > 0">
          <div class="mb-4 flex justify-between items-center">
            <h2 class="text-xl font-medium text-amber-200">
              検索結果（{{ advancedResults.length }}件）
            </h2>
          </div>

          <div class="space-y-4">
            <div
              v-for="result in advancedResults"
              :key="result.id"
              class="bg-stone-800 p-6 rounded-lg shadow-lg border border-amber-700 hover:border-amber-500 transition-colors"
            >
              <div class="flex justify-between items-start">
                <div class="flex-1">
                  <!-- ウイスキー名 -->
                  <h3 class="text-lg font-medium text-amber-200 mb-2">
                    {{ result.name_ja || result.name_en }}
                  </h3>

                  <!-- 副タイトル -->
                  <div class="text-amber-300 mb-3">
                    <span v-if="result.distillery_ja || result.distillery_en">
                      蒸留所: {{ result.distillery_ja || result.distillery_en }}
                    </span>
                    <span v-if="(result.distillery_ja || result.distillery_en) && (result.region || result.type)">
                      &nbsp;•&nbsp;
                    </span>
                    <span v-if="result.region">
                      {{ result.region }}
                    </span>
                    <span v-if="result.region && result.type">
                      &nbsp;•&nbsp;
                    </span>
                    <span v-if="result.type">
                      {{ result.type }}
                    </span>
                  </div>

                  <!-- 説明 -->
                  <p v-if="result.description" class="text-amber-400 text-sm line-clamp-2">
                    {{ result.description }}
                  </p>

                  <!-- 英語名（日本語名がある場合） -->
                  <p v-if="result.name_ja && result.name_en && result.name_ja !== result.name_en" class="text-amber-500 text-sm mt-2">
                    英語名: {{ result.name_en }}
                  </p>
                </div>

                <!-- アクション -->
                <div class="ml-4 flex flex-col space-y-2">
                  <button
                    @click="selectForReview(result)"
                    class="inline-flex items-center px-3 py-1.5 border border-amber-700 text-xs font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
                  >
                    レビュー作成
                  </button>
                  <button
                    @click="showResultDetail(result)"
                    class="inline-flex items-center px-3 py-1.5 border border-stone-600 text-xs font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors"
                  >
                    詳細
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 詳細モーダル -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="transform opacity-0 scale-95"
      enter-to-class="transform opacity-100 scale-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="transform opacity-100 scale-100"
      leave-to-class="transform opacity-0 scale-95"
    >
      <div
        v-if="selectedResult"
        class="fixed inset-0 z-50 overflow-y-auto"
        @click="closeResultDetail"
      >
        <div class="flex items-center justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
          <div class="fixed inset-0 bg-black bg-opacity-75 transition-opacity"></div>

          <div
            class="inline-block align-bottom bg-stone-800 rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full border border-amber-700"
            @click.stop
          >
            <div class="p-6">
              <div class="flex justify-between items-start mb-4">
                <h3 class="text-lg font-medium text-amber-200">
                  ウイスキー詳細
                </h3>
                <button
                  @click="closeResultDetail"
                  class="text-amber-400 hover:text-amber-200 transition-colors"
                >
                  <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                  </svg>
                </button>
              </div>

              <div class="space-y-4">
                <div>
                  <h4 class="font-medium text-amber-200">名前</h4>
                  <p class="text-amber-100">{{ selectedResult.name_ja || selectedResult.name_en }}</p>
                  <p v-if="selectedResult.name_ja && selectedResult.name_en && selectedResult.name_ja !== selectedResult.name_en" class="text-amber-400 text-sm">
                    英語名: {{ selectedResult.name_en }}
                  </p>
                </div>

                <div v-if="selectedResult.distillery_ja || selectedResult.distillery_en">
                  <h4 class="font-medium text-amber-200">蒸留所</h4>
                  <p class="text-amber-100">{{ selectedResult.distillery_ja || selectedResult.distillery_en }}</p>
                </div>

                <div v-if="selectedResult.region">
                  <h4 class="font-medium text-amber-200">地域</h4>
                  <p class="text-amber-100">{{ selectedResult.region }}</p>
                </div>

                <div v-if="selectedResult.type">
                  <h4 class="font-medium text-amber-200">タイプ</h4>
                  <p class="text-amber-100">{{ selectedResult.type }}</p>
                </div>

                <div v-if="selectedResult.description">
                  <h4 class="font-medium text-amber-200">説明</h4>
                  <p class="text-amber-100">{{ selectedResult.description }}</p>
                </div>
              </div>

              <div class="mt-6 flex justify-end space-x-3">
                <button
                  @click="closeResultDetail"
                  class="inline-flex justify-center px-4 py-2 border border-stone-600 text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors"
                >
                  閉じる
                </button>
                <button
                  @click="selectForReview(selectedResult)"
                  class="inline-flex justify-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
                >
                  レビュー作成
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>