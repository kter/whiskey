<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { ReviewInput, ServingStyle, Review } from '~/types/whiskey'
import { useWhiskeys } from '~/composables/useWhiskeys'
import { useSuggestWhiskeys } from '~/composables/useSuggestWhiskeys'
import { useAuth } from '~/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { updateReview } = useWhiskeys()
const { suggestions, debouncedSearch } = useSuggestWhiskeys()
const { getToken, user } = useAuth()
const config = useRuntimeConfig()

const review = ref<ReviewInput>({
  whiskey_name: '',
  distillery: '',
  notes: '',
  rating: 3,
  style: [],
  date: new Date().toISOString().split('T')[0],
})

const originalReview = ref<Review | null>(null)
const loading = ref(false)
const error = ref('')
const showSuggestions = ref(false)

// 既存レビューを取得
const fetchReview = async () => {
  try {
    loading.value = true
    const token = await getToken()
    const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/${route.params.id}/`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })

    if (!response.ok) {
      throw new Error('レビューの取得に失敗しました')
    }

    const data = await response.json()
    originalReview.value = data
    
    // 編集権限チェック
    if (user.value && data.user_id !== user.value.sub) {
      router.push('/reviews')
      return
    }

    // フォームにデータを設定
    review.value = {
      whiskey_name: data.whiskey_name || '',
      distillery: data.whiskey_distillery || '',
      notes: data.notes || '',
      rating: data.rating,
      style: data.serving_style ? [mapBackendToFrontendStyle(data.serving_style)] : [],
      date: data.date,
      image_url: data.image_url
    }
  } catch (err) {
    error.value = 'レビューの取得に失敗しました'
    console.error(err)
  } finally {
    loading.value = false
  }
}

// バックエンドの値をフロントエンドの値にマッピング
const mapBackendToFrontendStyle = (backendStyle: string): ServingStyle => {
  const styleMap: Record<string, ServingStyle> = {
    'NEAT': 'Neat',
    'ROCKS': 'Rock',
    'WATER': 'Twice Up',
    'SODA': 'High Ball',
    'COCKTAIL': 'Cocktail'
  }
  return styleMap[backendStyle] || 'Neat'
}

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
    review.value.style = [style] // 一つだけ選択可能
  } else {
    review.value.style = []
  }
}

// レビュー更新
const handleSave = async () => {
  try {
    error.value = ''
    await updateReview(route.params.id as string, review.value)
    router.push(`/reviews/${route.params.id}`)
  } catch (err) {
    error.value = 'レビューの更新に失敗しました。'
    console.error(err)
  }
}

onMounted(async () => {
  await fetchReview()
})
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <div class="mb-6">
      <NuxtLink 
        :to="`/reviews/${route.params.id}`"
        class="inline-flex items-center text-sm text-amber-300 hover:text-amber-100 transition-colors"
      >
        ← レビュー詳細に戻る
      </NuxtLink>
    </div>

    <!-- ローディング -->
    <div v-if="loading" class="mt-6 text-center">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-amber-500 border-t-transparent"></div>
    </div>

    <!-- メインフォーム -->
    <div v-else>
      <h1 class="text-3xl font-semibold text-amber-200 mb-6">
        レビュー編集
      </h1>

      <form @submit.prevent="handleSave" class="mt-6 space-y-6 bg-stone-800 p-6 rounded-lg shadow-lg border border-amber-700">
        <!-- ウイスキー名 -->
        <div class="relative">
          <label for="whiskey_name" class="block text-sm font-medium text-amber-200">
            ウイスキー名 *
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
            蒸留所
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
            評価 *
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
            飲み方 *
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
            日付 *
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
            ノート
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

        <!-- ボタン -->
        <div class="flex justify-end space-x-3">
          <NuxtLink
            :to="`/reviews/${route.params.id}`"
            class="inline-flex justify-center py-2 px-4 border border-stone-600 shadow-sm text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors"
          >
            キャンセル
          </NuxtLink>
          <button
            type="submit"
            class="inline-flex justify-center py-2 px-4 border border-amber-700 shadow-sm text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors"
          >
            更新
          </button>
        </div>
      </form>
    </div>
  </div>
</template> 