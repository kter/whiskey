<script setup lang="ts">
import { ref } from 'vue'
import type { ReviewSearchParams } from '~/types/whiskey'
import { useWhiskeys } from '~/composables/useWhiskeys'

const { reviews, loading, error, totalCount, fetchReviews, deleteReview } = useWhiskeys()

// 検索パラメータ
const searchParams = ref<ReviewSearchParams>({
  page: 1,
  per_page: 10,
})

// 初期データ取得
onMounted(async () => {
  await fetchReviews(searchParams.value)
})

// ページ変更
const handlePageChange = async (page: number) => {
  searchParams.value.page = page
  await fetchReviews(searchParams.value)
}

// 削除確認モーダル
const showDeleteModal = ref(false)
const targetReviewId = ref<number | null>(null)

const handleDeleteClick = (id: number) => {
  targetReviewId.value = id
  showDeleteModal.value = true
}

const handleDeleteConfirm = async () => {
  if (!targetReviewId.value) return
  
  try {
    await deleteReview(targetReviewId.value)
    showDeleteModal.value = false
    await fetchReviews(searchParams.value)
  } catch (err) {
    console.error('削除に失敗しました:', err)
  }
}
</script>

<template>
  <div>
    <div class="sm:flex sm:items-center">
      <div class="sm:flex-auto">
        <h1 class="text-3xl font-semibold text-amber-200 mb-6">レビュー一覧</h1>
      </div>
      <div class="mt-4 sm:mt-0 sm:ml-16 sm:flex-none">
        <NuxtLink
          to="/reviews/new"
          class="inline-flex items-center justify-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
        >
          新規レビュー
        </NuxtLink>
      </div>
    </div>

    <!-- ローディング -->
    <div v-if="loading" class="mt-6 text-center">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-amber-500 border-t-transparent"></div>
    </div>

    <!-- エラー -->
    <div v-else-if="error" class="mt-6 bg-red-900/50 p-4 rounded-md border border-red-800">
      <div class="text-red-300">
        エラーが発生しました。再度お試しください。
      </div>
    </div>

    <!-- レビュー一覧 -->
    <div v-else class="mt-6">
      <div v-if="!reviews || reviews.length === 0" class="text-center text-amber-300">
        レビューがありません
      </div>
      <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="review in reviews"
          :key="review.id"
          class="bg-stone-800 shadow-lg rounded-lg overflow-hidden border border-amber-700 hover:shadow-xl transition-all hover:border-amber-500"
        >
          <!-- レビューカード -->
          <div v-if="review.image_url" class="aspect-w-3 aspect-h-2">
            <img
              :src="review.image_url"
              :alt="review.whiskey_name"
              class="w-full h-48 object-cover"
            >
          </div>
          <div class="p-4">
            <h3 class="text-lg font-medium text-amber-200">
              {{ review.whiskey_name }}
            </h3>
            <p v-if="review.whiskey_distillery" class="mt-1 text-sm text-amber-100">
              {{ review.whiskey_distillery }}
            </p>
            <div class="mt-2 flex items-center">
              <div class="flex items-center">
                <template v-for="i in 5" :key="i">
                  <svg
                    :class="[
                      i <= review.rating ? 'text-amber-400' : 'text-stone-500',
                      'h-5 w-5 flex-shrink-0'
                    ]"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                  </svg>
                </template>
              </div>
              <span class="ml-2 text-sm text-amber-300">
                {{ review.date }}
              </span>
            </div>
            <div v-if="review.serving_style" class="mt-2 flex flex-wrap gap-2">
              <span
                class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-800 text-amber-200 border border-amber-600"
              >
                {{ review.serving_style }}
              </span>
            </div>
            <p v-if="review.notes" class="mt-2 text-sm text-amber-100 line-clamp-3">
              {{ review.notes }}
            </p>
            <div class="mt-4 flex justify-end space-x-2">
              <NuxtLink
                :to="`/reviews/${review.id}`"
                class="inline-flex items-center px-3 py-1.5 border border-amber-600 text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors"
              >
                詳細
              </NuxtLink>
              <NuxtLink
                :to="`/reviews/${review.id}/edit`"
                class="inline-flex items-center px-3 py-1.5 border border-amber-600 text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors"
              >
                編集
              </NuxtLink>
              <button
                @click="handleDeleteClick(review.id)"
                class="inline-flex items-center px-3 py-1.5 border border-red-800 text-sm font-medium rounded-md text-red-200 bg-red-900 hover:bg-red-800 transition-colors"
              >
                削除
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ページネーション -->
      <div v-if="totalCount > 0" class="mt-6 flex justify-center">
        <nav class="relative z-0 inline-flex rounded-md shadow-sm -space-x-px">
          <button
            v-for="page in Math.ceil(totalCount / searchParams.per_page)"
            :key="page"
            @click="handlePageChange(page)"
            :class="[
              page === searchParams.page
                ? 'z-10 bg-amber-800 border-amber-600 text-amber-100'
                : 'bg-stone-700 border-stone-600 text-amber-300 hover:bg-stone-600',
              'relative inline-flex items-center px-4 py-2 border text-sm font-medium transition-colors'
            ]"
          >
            {{ page }}
          </button>
        </nav>
      </div>
    </div>

    <!-- 削除確認モーダル -->
    <div
      v-if="showDeleteModal"
      class="fixed z-10 inset-0 overflow-y-auto"
      aria-labelledby="modal-title"
      role="dialog"
      aria-modal="true"
    >
      <div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
        <div
          class="fixed inset-0 bg-black bg-opacity-75 transition-opacity"
          aria-hidden="true"
          @click="showDeleteModal = false"
        ></div>

        <div class="relative inline-block align-bottom bg-stone-800 rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full sm:p-6 border border-amber-700">
          <div class="sm:flex sm:items-start">
            <div class="mt-3 text-center sm:mt-0 sm:text-left">
              <h3 class="text-lg leading-6 font-medium text-amber-200" id="modal-title">
                レビューを削除
              </h3>
              <div class="mt-2">
                <p class="text-sm text-amber-100">
                  このレビューを削除してもよろしいですか？この操作は取り消せません。
                </p>
              </div>
            </div>
          </div>
          <div class="mt-5 sm:mt-4 sm:flex sm:flex-row-reverse">
            <button
              type="button"
              class="w-full inline-flex justify-center rounded-md border border-red-800 shadow-sm px-4 py-2 bg-red-900 text-base font-medium text-red-200 hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 sm:ml-3 sm:w-auto sm:text-sm transition-colors"
              @click="handleDeleteConfirm"
            >
              削除
            </button>
            <button
              type="button"
              class="mt-3 w-full inline-flex justify-center rounded-md border border-stone-600 shadow-sm px-4 py-2 bg-stone-700 text-base font-medium text-amber-200 hover:bg-stone-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 sm:mt-0 sm:w-auto sm:text-sm transition-colors"
              @click="showDeleteModal = false"
            >
              キャンセル
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template> 