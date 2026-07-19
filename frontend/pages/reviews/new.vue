<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import WhiskeySearchInput from '~/components/WhiskeySearchInput.vue'
import { useWhiskeys } from '~/composables/useWhiskeys'
import { SERVING_STYLES, type ReviewInput, type ServingStyle } from '~/types/whiskey'

const route = useRoute()
const { createReview, loading } = useWhiskeys()
const selectedName = ref(typeof route.query.whiskey_name === 'string' ? route.query.whiskey_name : '')
const whiskeyName = ref(selectedName.value)
const whiskeyDistillery = ref(typeof route.query.distillery === 'string' ? route.query.distillery : '')
const review = ref<ReviewInput>({
  whiskey_id: typeof route.query.whiskey_id === 'string' ? route.query.whiskey_id : '',
  notes: '',
  rating: 3,
  serving_style: 'NEAT',
  date: new Date().toISOString().slice(0, 10),
  is_public: false,
})
const error = ref('')
const styleLabels: Record<ServingStyle, string> = {
  NEAT: 'ストレート',
  ROCKS: 'ロック',
  WATER: '水割り・トワイスアップ',
  SODA: 'ハイボール',
  COCKTAIL: 'カクテル',
}

watch(whiskeyName, value => {
  if (value !== selectedName.value) review.value.whiskey_id = ''
})

const hasSelectedWhiskey = computed(() => Boolean(review.value.whiskey_id))

const handleWhiskeySelection = (selection: { id: string; name: string; distillery: string }) => {
  selectedName.value = selection.name
  whiskeyName.value = selection.name
  whiskeyDistillery.value = selection.distillery
  review.value.whiskey_id = selection.id
}

const handleSubmit = async () => {
  if (!hasSelectedWhiskey.value) {
    error.value = '検索候補からウイスキーを選択してください。'
    return
  }
  error.value = ''
  try {
    await createReview(review.value)
    await navigateTo('/reviews')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'レビューの作成に失敗しました。'
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">新規レビュー</h1>
    <form class="space-y-6 bg-stone-800 p-6 rounded-lg shadow-lg border border-amber-700" @submit.prevent="handleSubmit">
      <div>
        <label class="block text-sm font-medium text-amber-200 mb-2">ウイスキー名 *</label>
        <WhiskeySearchInput v-model="whiskeyName" placeholder="ウイスキー名で検索..." @select="handleWhiskeySelection" />
        <p :class="hasSelectedWhiskey ? 'text-green-300' : 'text-amber-400'" class="mt-2 text-xs">
          {{ hasSelectedWhiskey ? `選択済み${whiskeyDistillery ? `: ${whiskeyDistillery}` : ''}` : '入力後、必ず検索候補から銘柄を選択してください。' }}
        </p>
      </div>

      <div>
        <label class="block text-sm font-medium text-amber-200">評価 *</label>
        <div class="mt-1 flex items-center">
          <button v-for="score in 5" :key="score" type="button" class="p-1 text-2xl" :class="score <= review.rating ? 'text-amber-400' : 'text-stone-500'" @click="review.rating = score">★</button>
          <span class="ml-2 text-sm text-amber-300">{{ review.rating }} / 5</span>
        </div>
      </div>

      <fieldset>
        <legend class="block text-sm font-medium text-amber-200">飲み方 *</legend>
        <div class="mt-2 flex flex-wrap gap-2">
          <label v-for="style in SERVING_STYLES" :key="style" class="cursor-pointer px-3 py-1.5 rounded-full text-sm border" :class="review.serving_style === style ? 'bg-amber-700 text-amber-100 border-amber-500' : 'bg-stone-600 text-amber-300 border-stone-500'">
            <input v-model="review.serving_style" class="sr-only" type="radio" name="serving-style" :value="style" />
            {{ styleLabels[style] }}
          </label>
        </div>
      </fieldset>

      <div>
        <label for="review-date" class="block text-sm font-medium text-amber-200">日付 *</label>
        <input id="review-date" v-model="review.date" type="date" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
      </div>

      <div>
        <label for="review-notes" class="block text-sm font-medium text-amber-200">ノート</label>
        <textarea id="review-notes" v-model="review.notes" rows="4" class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" placeholder="テイスティングノートを記録してください..."></textarea>
      </div>

      <label class="flex items-center gap-3 text-amber-200">
        <input v-model="review.is_public" type="checkbox" class="rounded border-amber-700 bg-stone-700 text-amber-600" />
        このレビューを公開する
      </label>

      <p v-if="error" role="alert" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm">{{ error }}</p>
      <div class="flex justify-end space-x-3">
        <NuxtLink to="/reviews" class="py-2 px-4 border border-stone-600 rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600">キャンセル</NuxtLink>
        <button type="submit" :disabled="loading || !hasSelectedWhiskey" class="py-2 px-4 border border-amber-700 rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 disabled:opacity-50">保存</button>
      </div>
    </form>
  </div>
</template>
