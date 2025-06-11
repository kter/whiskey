<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useWhiskeySearch, type WhiskeySuggestion } from '~/composables/useWhiskeySearch'

const props = defineProps<{
  placeholder?: string
  modelValue?: string
  disabled?: boolean
  showDistillery?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'select': [selection: { name: string; distillery: string }]
}>()

const {
  searchQuery,
  searchResults,
  isSearching,
  showSuggestions,
  isMobile,
  selectSuggestion,
  hideSuggestions,
  showSuggestionsIfHasResults,
  formatSuggestionDisplay,
  formatSuggestionSecondaryText
} = useWhiskeySearch()

const inputRef = ref<HTMLInputElement>()
const containerRef = ref<HTMLDivElement>()

// 外部からの値同期
watch(() => props.modelValue, (newValue) => {
  if (newValue !== searchQuery.value) {
    searchQuery.value = newValue || ''
  }
})

// 内部値の変更を外部に送信
watch(searchQuery, (newValue) => {
  emit('update:modelValue', newValue)
})

// 検索候補の選択
const handleSelectSuggestion = (suggestion: WhiskeySuggestion) => {
  const selection = selectSuggestion(suggestion)
  emit('select', selection)
  
  // フォーカスを外す（モバイルでキーボードを閉じる）
  if (inputRef.value) {
    inputRef.value.blur()
  }
}

// フォーカス処理
const handleFocus = () => {
  showSuggestionsIfHasResults()
}

const handleBlur = () => {
  hideSuggestions()
}

// 外部クリック検知（モバイル対応）
const handleClickOutside = (event: Event) => {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    hideSuggestions()
  }
}

// キーボード操作（上下矢印キー、Enter、ESC）
const selectedIndex = ref(-1)

const handleKeydown = (event: KeyboardEvent) => {
  if (!showSuggestions.value || searchResults.value.length === 0) {
    return
  }
  
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      selectedIndex.value = Math.min(selectedIndex.value + 1, searchResults.value.length - 1)
      break
      
    case 'ArrowUp':
      event.preventDefault()
      selectedIndex.value = Math.max(selectedIndex.value - 1, -1)
      break
      
    case 'Enter':
      event.preventDefault()
      if (selectedIndex.value >= 0 && selectedIndex.value < searchResults.value.length) {
        handleSelectSuggestion(searchResults.value[selectedIndex.value])
      }
      break
      
    case 'Escape':
      hideSuggestions()
      selectedIndex.value = -1
      if (inputRef.value) {
        inputRef.value.blur()
      }
      break
  }
}

// 検索結果変更時にselectedIndexをリセット
watch(searchResults, () => {
  selectedIndex.value = -1
})

// マウント時にクリックイベントリスナーを追加
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div ref="containerRef" class="relative w-full">
    <!-- 検索入力フィールド -->
    <div class="relative">
      <input
        ref="inputRef"
        v-model="searchQuery"
        type="text"
        :placeholder="placeholder || 'ウイスキー名や蒸留所名で検索...'"
        :disabled="disabled"
        class="w-full px-4 py-3 pr-12 text-amber-100 bg-stone-700 border border-amber-700 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 placeholder-amber-400 transition-colors"
        :class="{
          'text-lg': isMobile,
          'opacity-50 cursor-not-allowed': disabled
        }"
        autocomplete="off"
        @focus="handleFocus"
        @blur="handleBlur"
        @keydown="handleKeydown"
      >
      
      <!-- ローディングインジケーター -->
      <div 
        v-if="isSearching" 
        class="absolute right-3 top-1/2 transform -translate-y-1/2"
      >
        <div class="animate-spin rounded-full h-5 w-5 border-2 border-amber-500 border-t-transparent"></div>
      </div>
      
      <!-- 検索アイコン -->
      <div 
        v-else
        class="absolute right-3 top-1/2 transform -translate-y-1/2 text-amber-400"
      >
        <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m21 21-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
        </svg>
      </div>
    </div>
    
    <!-- 検索候補ドロップダウン -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="transform scale-95 opacity-0"
      enter-to-class="transform scale-100 opacity-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="transform scale-100 opacity-100"
      leave-to-class="transform scale-95 opacity-0"
    >
      <div
        v-if="showSuggestions && searchResults.length > 0"
        class="absolute z-50 w-full mt-1 bg-stone-800 border border-amber-700 rounded-lg shadow-lg max-h-80 overflow-y-auto"
        :class="{
          'max-h-60': isMobile
        }"
      >
        <div class="py-1">
          <button
            v-for="(suggestion, index) in searchResults"
            :key="suggestion.id"
            type="button"
            class="w-full px-4 py-3 text-left hover:bg-stone-700 focus:bg-stone-700 focus:outline-none transition-colors border-b border-stone-700 last:border-b-0"
            :class="{
              'bg-stone-700': index === selectedIndex,
              'py-4': isMobile
            }"
            @click="handleSelectSuggestion(suggestion)"
            @mouseenter="selectedIndex = index"
          >
            <div class="flex flex-col">
              <!-- メイン表示名 -->
              <div class="font-medium text-amber-100">
                {{ formatSuggestionDisplay(suggestion) }}
              </div>
              
              <!-- 追加情報 -->
              <div 
                v-if="formatSuggestionSecondaryText(suggestion)"
                class="text-sm text-amber-300 mt-1"
              >
                {{ formatSuggestionSecondaryText(suggestion) }}
              </div>
              
              <!-- 蒸留所名（別途表示する場合） -->
              <div 
                v-if="showDistillery && suggestion.distillery_ja && suggestion.distillery_ja !== suggestion.name_ja"
                class="text-sm text-amber-400 mt-1"
              >
                蒸留所: {{ suggestion.distillery_ja }}
              </div>
              
              <!-- 説明（短縮版） -->
              <div 
                v-if="suggestion.description && suggestion.description.length > 0"
                class="text-xs text-amber-500 mt-1 line-clamp-2"
              >
                {{ suggestion.description }}
              </div>
            </div>
          </button>
        </div>
        
        <!-- 検索結果数表示 -->
        <div class="px-4 py-2 text-xs text-amber-400 border-t border-stone-700 bg-stone-900">
          {{ searchResults.length }}件の候補
        </div>
      </div>
    </Transition>
    
    <!-- 検索候補なしメッセージ -->
    <div
      v-if="showSuggestions && searchQuery.length > 0 && searchResults.length === 0 && !isSearching"
      class="absolute z-50 w-full mt-1 bg-stone-800 border border-amber-700 rounded-lg shadow-lg"
    >
      <div class="px-4 py-3 text-amber-400 text-center">
        「{{ searchQuery }}」に一致する候補が見つかりません
      </div>
    </div>
  </div>
</template>

<style scoped>
/* line-clamp-2 のカスタムスタイル（Tailwind CSS v3.0+ で利用可能） */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* フォーカス時の入力フィールドハイライト */
input:focus {
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.1);
}

/* モバイル用のタッチターゲット最適化 */
@media (max-width: 768px) {
  button {
    min-height: 44px; /* iOS推奨のタッチターゲットサイズ */
  }
}
</style>