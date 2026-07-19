<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import { useWhiskeys } from '~/composables/useWhiskeys'
import { SERVING_STYLES, type Review, type ReviewUpdateInput, type ServingStyle } from '~/types/whiskey'

const route = useRoute()
const router = useRouter()
const { fetchReview, updateReview, loading } = useWhiskeys()
const { currentUserId, waitForAuthReady } = useAuth()
const originalReview = ref<Review | null>(null)
const form = ref<ReviewUpdateInput>({ notes: '', rating: 3, serving_style: 'NEAT', date: '', is_public: false })
const error = ref('')
const styleLabels: Record<ServingStyle, string> = { NEAT: 'ストレート', ROCKS: 'ロック', WATER: '水割り・トワイスアップ', SODA: 'ハイボール', COCKTAIL: 'カクテル' }

onMounted(async () => {
  try {
    await waitForAuthReady()
    const data = await fetchReview(String(route.params.id))
    if (data.user_id && data.user_id !== currentUserId.value) {
      await router.push('/reviews')
      return
    }
    originalReview.value = data
    form.value = {
      notes: data.notes || '',
      rating: data.rating,
      serving_style: data.serving_style,
      date: data.date,
      is_public: data.is_public,
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'レビューの取得に失敗しました。'
  }
})

const handleSave = async () => {
  error.value = ''
  try {
    await updateReview(String(route.params.id), form.value)
    await router.push(`/reviews/${route.params.id}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'レビューの更新に失敗しました。'
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <NuxtLink :to="`/reviews/${route.params.id}`" class="text-sm text-amber-300 hover:text-amber-100">← レビュー詳細に戻る</NuxtLink>
    <h1 class="text-3xl font-semibold text-amber-200 my-6">レビュー編集</h1>
    <div v-if="loading && !originalReview" class="text-center text-amber-300">読み込み中...</div>
    <form v-else-if="originalReview" class="space-y-6 bg-stone-800 p-6 rounded-lg border border-amber-700" @submit.prevent="handleSave">
      <div>
        <label class="block text-sm font-medium text-amber-200">ウイスキー名</label>
        <div class="mt-1 rounded-md border border-stone-600 bg-stone-700 px-3 py-2 text-amber-100">{{ originalReview.whiskey_name || originalReview.whiskey_id }}</div>
        <p class="mt-1 text-xs text-amber-400">銘柄は変更できません。変更する場合は、このレビューを削除して新しく作成してください。</p>
      </div>
      <div>
        <label class="block text-sm font-medium text-amber-200">評価 *</label>
        <button v-for="score in 5" :key="score" type="button" class="p-1 text-2xl" :class="score <= form.rating ? 'text-amber-400' : 'text-stone-500'" @click="form.rating = score">★</button>
      </div>
      <fieldset>
        <legend class="text-sm font-medium text-amber-200">飲み方 *</legend>
        <div class="mt-2 flex flex-wrap gap-2">
          <label v-for="style in SERVING_STYLES" :key="style" class="cursor-pointer px-3 py-1.5 rounded-full text-sm border" :class="form.serving_style === style ? 'bg-amber-700 text-amber-100 border-amber-500' : 'bg-stone-600 text-amber-300 border-stone-500'">
            <input v-model="form.serving_style" class="sr-only" type="radio" name="serving-style" :value="style" />{{ styleLabels[style] }}
          </label>
        </div>
      </fieldset>
      <div><label for="edit-date" class="block text-sm font-medium text-amber-200">日付 *</label><input id="edit-date" v-model="form.date" type="date" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" /></div>
      <div><label for="edit-notes" class="block text-sm font-medium text-amber-200">ノート</label><textarea id="edit-notes" v-model="form.notes" rows="4" class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100"></textarea></div>
      <label class="flex items-center gap-3 text-amber-200"><input v-model="form.is_public" type="checkbox" />このレビューを公開する</label>
      <p v-if="error" role="alert" class="text-red-300 bg-red-900/50 p-3 rounded-md">{{ error }}</p>
      <div class="flex justify-end gap-3"><NuxtLink :to="`/reviews/${route.params.id}`" class="py-2 px-4 rounded-md text-amber-200 bg-stone-700">キャンセル</NuxtLink><button type="submit" :disabled="loading" class="py-2 px-4 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50">更新</button></div>
    </form>
    <p v-else-if="error" class="text-red-300">{{ error }}</p>
  </div>
</template>
