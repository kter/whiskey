<template>
  <div>
    <div class="mb-6">
      <NuxtLink 
        to="/reviews" 
        class="inline-flex items-center text-sm text-amber-300 hover:text-amber-100 transition-colors"
      >
        ← レビュー一覧に戻る
      </NuxtLink>
    </div>

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

    <!-- レビュー詳細 -->
    <div v-else-if="review" class="bg-stone-800 shadow-lg rounded-lg overflow-hidden border border-amber-700">
      <!-- 画像 -->
      <div v-if="review.image_url" class="aspect-w-3 aspect-h-2">
        <img
          :src="review.image_url"
          :alt="review.whiskey_name"
          class="w-full h-64 object-cover"
        >
      </div>
      
      <div class="p-6">
        <!-- ウイスキー情報 -->
        <div class="mb-6">
          <h1 class="text-3xl font-bold text-amber-200 mb-2">
            {{ review.whiskey_name || 'Unknown Whiskey' }}
          </h1>
          <p v-if="review.whiskey_distillery" class="text-lg text-amber-100">
            {{ review.whiskey_distillery }}
          </p>
        </div>

        <!-- 評価と日付 -->
        <div class="mb-6 flex items-center justify-between">
          <div class="flex items-center">
            <div class="flex items-center mr-4">
              <template v-for="i in 5" :key="i">
                <svg
                  :class="[
                    i <= review.rating ? 'text-amber-400' : 'text-stone-500',
                    'h-6 w-6 flex-shrink-0'
                  ]"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                </svg>
              </template>
            </div>
            <span class="text-lg text-amber-300">
              {{ review.rating }} / 5
            </span>
          </div>
          <div class="text-amber-300">
            {{ formatDate(review.date) }}
          </div>
        </div>

        <!-- 飲み方 -->
        <div v-if="review.serving_style" class="mb-6">
          <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-amber-800 text-amber-200 border border-amber-600">
            {{ review.serving_style }}
          </span>
        </div>

        <!-- ノート -->
        <div v-if="review.notes" class="mb-6">
          <h3 class="text-lg font-medium text-amber-200 mb-2">
            テイスティングノート
          </h3>
          <p class="text-amber-100 whitespace-pre-wrap">
            {{ review.notes }}
          </p>
        </div>

        <!-- アクションボタン -->
        <div class="flex justify-between items-center">
          <NuxtLink
            to="/reviews"
            class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-stone-700 hover:bg-stone-600 transition-colors"
          >
            一覧に戻る
          </NuxtLink>
          
          <div v-if="isOwner" class="flex space-x-3">
            <NuxtLink
              :to="`/reviews/${review.id}/edit`"
              class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
            >
              編集
            </NuxtLink>
            <button
              @click="handleDeleteClick"
              class="inline-flex items-center px-4 py-2 border border-red-800 text-sm font-medium rounded-md text-red-200 bg-red-900 hover:bg-red-800 transition-colors"
            >
              削除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- レビューが見つからない場合 -->
    <div v-else class="bg-stone-800 shadow-lg rounded-lg p-6 border border-amber-700">
      <h1 class="text-2xl font-bold text-amber-200 mb-4">
        レビューが見つかりません
      </h1>
      <NuxtLink
        to="/reviews"
        class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
      >
        一覧に戻る
      </NuxtLink>
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

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import type { Review } from '~/types/whiskey'
import { useAuth } from '~/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { getToken, user } = useAuth()
const config = useRuntimeConfig()

const review = ref<Review | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const showDeleteModal = ref(false)

// 現在のユーザーがレビューの所有者かチェック
const isOwner = computed(() => {
  return user.value && review.value && review.value.user_id === user.value.sub
})

// レビュー詳細を取得
const fetchReview = async () => {
  try {
    loading.value = true
    error.value = null

    const token = await getToken()
    const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/${route.params.id}/`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })

    if (!response.ok) {
      if (response.status === 404) {
        error.value = 'レビューが見つかりません'
      } else {
        error.value = 'レビューの取得に失敗しました'
      }
      return
    }

    review.value = await response.json()
  } catch (err) {
    error.value = 'レビューの取得に失敗しました'
    console.error('Fetch Review Error:', err)
  } finally {
    loading.value = false
  }
}

// レビューを削除
const handleDeleteClick = () => {
  showDeleteModal.value = true
}

const handleDeleteConfirm = async () => {
  try {
    loading.value = true
    const token = await getToken()
    const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/${route.params.id}/`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`
      }
    })

    if (!response.ok) {
      throw new Error('削除に失敗しました')
    }

    router.push('/reviews')
  } catch (err) {
    error.value = '削除に失敗しました'
    console.error('Delete Error:', err)
  } finally {
    loading.value = false
    showDeleteModal.value = false
  }
}

// 日付をフォーマット
const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  })
}

// 初期データ取得
onMounted(async () => {
  await fetchReview()
})
</script> 