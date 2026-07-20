<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import { useWhiskeys } from '~/composables/useWhiskeys'
import type { Review } from '~/types/whiskey'

const route = useRoute()
const router = useRouter()
const { currentUserId, waitForAuthReady } = useAuth()
const { fetchReview, deleteReview } = useWhiskeys()
const review = ref<Review | null>(null)
const loading = ref(false)
const error = ref('')
const showDeleteModal = ref(false)
const isOwner = computed(() => Boolean(review.value?.user_id && review.value.user_id === currentUserId.value))

onMounted(async () => {
  loading.value = true
  try {
    await waitForAuthReady()
    review.value = await fetchReview(String(route.params.id))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'レビューの取得に失敗しました。'
  } finally {
    loading.value = false
  }
})

const confirmDelete = async () => {
  loading.value = true
  try {
    await deleteReview(String(route.params.id))
    await router.push('/reviews')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'レビューの削除に失敗しました。'
  } finally {
    loading.value = false
    showDeleteModal.value = false
  }
}

const formatDate = (date: string) => new Date(date).toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric' })
</script>

<template>
  <div>
    <NuxtLink to="/reviews" class="text-sm text-amber-300 hover:text-amber-100">← レビュー一覧に戻る</NuxtLink>
    <div v-if="loading && !review" class="mt-6 text-center text-amber-300">読み込み中...</div>
    <p v-else-if="error" role="alert" class="mt-6 text-red-300 bg-red-900/50 p-4 rounded-md">{{ error }}</p>
    <article v-else-if="review" class="mt-6 bg-stone-800 shadow-lg rounded-lg border border-amber-700 p-6">
      <h1 class="text-3xl font-bold text-amber-200">{{ review.whiskey_name || review.whiskey_id }}</h1>
      <p v-if="review.whiskey_distillery" class="mt-1 text-lg text-amber-100">{{ review.whiskey_distillery }}</p>
      <div class="my-6 flex justify-between text-amber-300"><span class="text-amber-400 text-xl">{{ '★'.repeat(review.rating) }}{{ '☆'.repeat(5 - review.rating) }}</span><span>{{ formatDate(review.date) }}</span></div>
      <div class="mb-6 flex gap-2"><span class="px-3 py-1 rounded-full text-sm bg-amber-800 text-amber-200">{{ review.serving_style }}</span><span class="px-3 py-1 rounded-full text-sm bg-stone-700 text-amber-200">{{ review.is_public ? '公開' : '非公開' }}</span></div>
      <div v-if="review.notes" class="mb-6"><h2 class="text-lg font-medium text-amber-200 mb-2">テイスティングノート</h2><p class="text-amber-100 whitespace-pre-wrap">{{ review.notes }}</p></div>
      <div v-if="isOwner" class="flex justify-end gap-3"><NuxtLink :to="`/reviews/${review.id}/edit`" class="px-4 py-2 rounded-md text-amber-100 bg-amber-800">編集</NuxtLink><button class="px-4 py-2 rounded-md text-red-200 bg-red-900" @click="showDeleteModal = true">削除</button></div>
    </article>
    <div v-if="showDeleteModal" class="fixed inset-0 z-10 flex items-center justify-center bg-black/75 px-4" role="dialog" aria-modal="true"><div class="max-w-md w-full bg-stone-800 rounded-lg p-6 border border-amber-700"><h2 class="text-lg text-amber-200">レビューを削除</h2><p class="mt-2 text-amber-100">この操作は取り消せません。</p><div class="mt-5 flex justify-end gap-3"><button class="px-4 py-2 bg-stone-700 text-amber-200 rounded-md" @click="showDeleteModal = false">キャンセル</button><button class="px-4 py-2 bg-red-900 text-red-200 rounded-md" @click="confirmDelete">削除</button></div></div></div>
  </div>
</template>
