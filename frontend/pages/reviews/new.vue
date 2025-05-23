<script setup lang="ts">
import { ref } from 'vue'
import type { ReviewInput, ServingStyle } from '~/types/whiskey'
import { useWhiskeys } from '~/composables/useWhiskeys'
import { useSuggestWhiskeys } from '~/composables/useSuggestWhiskeys'

const { createReview } = useWhiskeys()
const { suggestions, debouncedSearch } = useSuggestWhiskeys()

const review = ref<ReviewInput>({
  whiskey_name: '',
  distillery: '',
  notes: '',
  rating: 3,
  style: [],
  date: new Date().toISOString().split('T')[0],
})

const error = ref('')
const showSuggestions = ref(false)

// サジェスト検索
const handleWhiskeyNameInput = (event: Event) => {
  const input = event.target as HTMLInputElement
  review.value.whiskey_name = input.value
  if (input.value.length >= 2) {
    debouncedSearch(input.value)
    showSuggestions.value = true
  } else {
    showSuggestions.value = false
  }
}

// サジェストアイテムの選択
const selectSuggestion = (name: string) => {
  review.value.whiskey_name = name
  showSuggestions.value = false
}

// 飲み方の選択
const servingStyles: ServingStyle[] = [
  'Neat',
  'Rock',
  'Twice Up',
  'High Ball',
  'On the Rocks',
  'Water',
  'Hot',
  'Cocktail'
]

const toggleStyle = (style: ServingStyle) => {
  const index = review.value.style.indexOf(style)
  if (index === -1) {
    review.value.style.push(style)
  } else {
    review.value.style.splice(index, 1)
  }
}

// レビュー送信
const handleSubmit = async () => {
  try {
    error.value = ''
    await createReview(review.value)
    navigateTo('/reviews')
  } catch (err) {
    error.value = 'レビューの作成に失敗しました。'
    console.error(err)
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">
      ✍️ 新規レビュー
    </h1>

    <form @submit.prevent="handleSubmit" class="mt-6 space-y-6 bg-stone-800 p-6 rounded-lg shadow-lg border border-amber-700">
      <!-- ウイスキー名 -->
      <div class="relative">
        <label for="whiskey_name" class="block text-sm font-medium text-amber-200">
          🥃 ウイスキー名 *
        </label>
        <input
          id="whiskey_name"
          type="text"
          required
          :value="review.whiskey_name"
          @input="handleWhiskeyNameInput"
          class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm placeholder-amber-400"
          placeholder="ウイスキー名を入力"
        >
        <!-- サジェスト -->
        <div
          v-if="showSuggestions && suggestions.length > 0"
          class="absolute z-10 mt-1 w-full bg-stone-700 shadow-lg rounded-md border border-amber-600"
        >
          <ul class="py-1">
            <li
              v-for="suggestion in suggestions"
              :key="suggestion"
              @click="selectSuggestion(suggestion)"
              class="px-3 py-2 hover:bg-stone-600 cursor-pointer text-amber-100"
            >
              {{ suggestion }}
            </li>
          </ul>
        </div>
      </div>

      <!-- 蒸留所 -->
      <div>
        <label for="distillery" class="block text-sm font-medium text-amber-200">
          🏭 蒸留所
        </label>
        <input
          id="distillery"
          v-model="review.distillery"
          type="text"
          class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm placeholder-amber-400"
          placeholder="蒸留所名を入力"
        >
      </div>

      <!-- 評価 -->
      <div>
        <label class="block text-sm font-medium text-amber-200">
          ⭐ 評価 *
        </label>
        <div class="mt-1 flex items-center">
          <div class="flex">
            <template v-for="i in 5" :key="i">
              <button
                type="button"
                @click="review.rating = i"
                class="p-1"
              >
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
              </button>
            </template>
          </div>
          <span class="ml-2 text-sm text-amber-300">
            {{ review.rating }} / 5
          </span>
        </div>
      </div>

      <!-- 飲み方 -->
      <div>
        <label class="block text-sm font-medium text-amber-200">
          🍹 飲み方 *
        </label>
        <div class="mt-2 flex flex-wrap gap-2">
          <button
            v-for="style in servingStyles"
            :key="style"
            type="button"
            @click="toggleStyle(style)"
            :class="[
              review.style.includes(style)
                ? 'bg-amber-700 text-amber-100 border-amber-500'
                : 'bg-stone-600 text-amber-300 border-stone-500',
              'inline-flex items-center px-3 py-1.5 rounded-full text-sm font-medium border transition-colors hover:bg-amber-600'
            ]"
          >
            {{ style }}
          </button>
        </div>
      </div>

      <!-- 日付 -->
      <div>
        <label for="date" class="block text-sm font-medium text-amber-200">
          📅 日付 *
        </label>
        <input
          id="date"
          v-model="review.date"
          type="date"
          required
          class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm"
        >
      </div>

      <!-- ノート -->
      <div>
        <label for="notes" class="block text-sm font-medium text-amber-200">
          📝 ノート
        </label>
        <textarea
          id="notes"
          v-model="review.notes"
          rows="4"
          class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm placeholder-amber-400"
          placeholder="テイスティングノートを記録してください..."
        ></textarea>
      </div>

      <!-- エラー -->
      <div v-if="error" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm">
        {{ error }}
      </div>

      <!-- 送信ボタン -->
      <div class="flex justify-end space-x-3">
        <NuxtLink
          to="/reviews"
          class="inline-flex justify-center py-2 px-4 border border-stone-600 shadow-sm text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors"
        >
          ❌ キャンセル
        </NuxtLink>
        <button
          type="submit"
          class="inline-flex justify-center py-2 px-4 border border-amber-700 shadow-sm text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors"
        >
          💾 保存
        </button>
      </div>
    </form>
  </div>
</template> 