<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import { useWhiskeys } from '~/composables/useWhiskeys'
import type { Review } from '~/types/whiskey'

const { reviews, nextToken, loading, error, fetchReviews, deleteReview } = useWhiskeys()
const { isAuthenticated, currentUserId, waitForAuthReady } = useAuth()
const showDeleteModal = ref(false)
const targetReviewId = ref<string | null>(null)

onMounted(async () => {
  await waitForAuthReady()
  if (isAuthenticated.value) await fetchReviews({ limit: 10 })
})

const loadMore = () => nextToken.value && fetchReviews({ limit: 10, next_token: nextToken.value }, true)
const isOwner = (review: Review) => Boolean(currentUserId.value && review.user_id === currentUserId.value)
const requestDelete = (id: string) => {
  targetReviewId.value = id
  showDeleteModal.value = true
}
const confirmDelete = async () => {
  if (!targetReviewId.value) return
  try {
    await deleteReview(targetReviewId.value)
    await fetchReviews({ limit: 10 })
    showDeleteModal.value = false
    targetReviewId.value = null
  } catch {
    // The composable exposes the normalized error in `error`.
  }
}
</script>

<template>
  <div>
    <div class="sm:flex sm:items-center">
      <h1 class="flex-1 text-3xl font-semibold text-amber-200 mb-6">レビュー一覧</h1>
      <NuxtLink v-if="isAuthenticated" to="/reviews/new" class="px-4 py-2 rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700">新規レビュー</NuxtLink>
    </div>

    <div v-if="loading && reviews.length === 0" class="mt-6 text-center text-amber-300">読み込み中...</div>
    <div v-else-if="!isAuthenticated" class="mt-6 text-center text-amber-300">
      <p>レビューを表示するにはログインが必要です。</p>
      <NuxtLink to="/login" class="mt-4 inline-flex px-4 py-2 rounded-md text-amber-100 bg-amber-800">ログイン</NuxtLink>
    </div>
    <div v-else class="mt-6">
      <p v-if="error" role="alert" class="mb-4 text-red-300 bg-red-900/50 p-4 rounded-md border border-red-800">{{ error }}</p>
      <p v-if="reviews.length === 0 && !loading" class="text-center text-amber-300">レビューがありません</p>
      <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <article v-for="review in reviews" :key="review.id" class="bg-stone-800 shadow-lg rounded-lg border border-amber-700 p-4">
          <h2 class="text-lg font-medium text-amber-200">{{ review.whiskey_name || review.whiskey_id }}</h2>
          <p v-if="review.whiskey_distillery" class="mt-1 text-sm text-amber-100">{{ review.whiskey_distillery }}</p>
          <p class="mt-2 text-amber-300"><span class="text-amber-400">{{ '★'.repeat(review.rating) }}</span>{{ '☆'.repeat(5 - review.rating) }} · {{ review.date }}</p>
          <div class="mt-2 flex gap-2"><span class="px-2.5 py-0.5 rounded-full text-xs bg-amber-800 text-amber-200">{{ review.serving_style }}</span><span class="px-2.5 py-0.5 rounded-full text-xs bg-stone-700 text-amber-200">{{ review.is_public ? '公開' : '非公開' }}</span></div>
          <p v-if="review.notes" class="mt-3 text-sm text-amber-100 line-clamp-3">{{ review.notes }}</p>
          <div class="mt-4 flex justify-end gap-2">
            <NuxtLink :to="`/reviews/${review.id}`" class="px-3 py-1.5 border border-amber-600 rounded-md text-amber-200 bg-stone-700">詳細</NuxtLink>
            <NuxtLink v-if="isOwner(review)" :to="`/reviews/${review.id}/edit`" class="px-3 py-1.5 border border-amber-600 rounded-md text-amber-200 bg-stone-700">編集</NuxtLink>
            <button v-if="isOwner(review)" class="px-3 py-1.5 border border-red-800 rounded-md text-red-200 bg-red-900" @click="requestDelete(review.id)">削除</button>
          </div>
        </article>
      </div>
      <div v-if="nextToken" class="mt-8 text-center"><button :disabled="loading" class="px-5 py-2 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50" @click="loadMore">{{ loading ? '読み込み中...' : 'さらに読み込む' }}</button></div>
    </div>

    <div v-if="showDeleteModal" class="fixed inset-0 z-10 flex items-center justify-center bg-black/75 px-4" role="dialog" aria-modal="true">
      <div class="max-w-md w-full bg-stone-800 rounded-lg p-6 border border-amber-700">
        <h2 class="text-lg font-medium text-amber-200">レビューを削除</h2>
        <p class="mt-2 text-sm text-amber-100">この操作は取り消せません。削除してもよろしいですか？</p>
        <div class="mt-5 flex justify-end gap-3"><button class="px-4 py-2 bg-stone-700 text-amber-200 rounded-md" @click="showDeleteModal = false">キャンセル</button><button class="px-4 py-2 bg-red-900 text-red-200 rounded-md" @click="confirmDelete">削除</button></div>
      </div>
    </div>
  </div>
</template>
