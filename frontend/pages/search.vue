<script setup lang="ts">
import { computed, ref } from 'vue'
import { useWhiskeySearch, type WhiskeySuggestion } from '~/composables/useWhiskeySearch'

const {
  searchFilters,
  advancedResults,
  advancedNextToken,
  isAdvancedSearching,
  advancedSearchError,
  performAdvancedSearch,
  loadMoreAdvancedResults,
  clearAdvancedSearch,
} = useWhiskeySearch()
const searchPerformed = ref(false)
const selectedResult = ref<WhiskeySuggestion | null>(null)
const canSearch = computed(() => Boolean(searchFilters.value.name.trim()))

const handleSearch = async () => {
  searchPerformed.value = true
  try { await performAdvancedSearch(searchFilters.value) } catch { /* normalized state is displayed below */ }
}
const resetSearch = () => {
  clearAdvancedSearch()
  searchPerformed.value = false
  selectedResult.value = null
}
</script>

<template>
  <div class="max-w-5xl mx-auto">
    <h1 class="text-3xl font-semibold text-amber-200 mb-2">ウイスキー検索</h1>
    <p class="text-amber-300 mb-6">名前を日本語または英語で検索できます。</p>
    <form class="bg-stone-800 p-6 rounded-lg border border-amber-700 flex flex-col sm:flex-row gap-3" @submit.prevent="handleSearch">
      <input v-model="searchFilters.name" type="search" class="flex-1 px-3 py-2 text-amber-100 bg-stone-700 border border-amber-700 rounded-md" placeholder="例: 山崎、Macallan" />
      <button type="submit" :disabled="!canSearch || isAdvancedSearching" class="px-5 py-2 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50">検索</button>
      <button type="button" class="px-5 py-2 rounded-md text-amber-200 bg-stone-700" @click="resetSearch">リセット</button>
    </form>

    <p v-if="advancedSearchError" role="alert" class="mt-6 p-4 bg-red-900/50 border border-red-800 rounded-lg text-red-300">{{ advancedSearchError }}</p>
    <p v-if="!searchPerformed" class="text-center py-12 text-amber-400">検索するウイスキー名を入力してください。</p>
    <p v-else-if="advancedResults.length === 0 && !isAdvancedSearching && !advancedNextToken" class="text-center py-12 text-amber-400">該当するウイスキーが見つかりませんでした。</p>
    <div v-else class="mt-6 space-y-4">
      <article v-for="result in advancedResults" :key="result.id" class="bg-stone-800 p-6 rounded-lg border border-amber-700">
        <div class="flex justify-between gap-4"><div><h2 class="text-lg font-medium text-amber-200">{{ result.name_ja || result.name_en || result.name }}</h2><p v-if="result.distillery" class="text-amber-300">{{ result.distillery }}</p><p class="text-sm text-amber-400">{{ [result.region, result.type].filter(Boolean).join(' • ') }}</p></div><button class="self-start px-3 py-1.5 rounded-md text-amber-200 bg-stone-700" @click="selectedResult = result">詳細</button></div>
      </article>
      <div v-if="advancedNextToken" class="text-center"><p v-if="advancedResults.length === 0" class="mb-3 text-amber-400">このページには結果がありません。続きを検索できます。</p><button :disabled="isAdvancedSearching" class="px-5 py-2 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50" @click="loadMoreAdvancedResults()">{{ isAdvancedSearching ? '読み込み中...' : 'さらに読み込む' }}</button></div>
    </div>

    <div v-if="selectedResult" class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 px-4" @click="selectedResult = null"><div class="max-w-lg w-full bg-stone-800 rounded-lg p-6 border border-amber-700" @click.stop><h2 class="text-xl text-amber-200">{{ selectedResult.name_ja || selectedResult.name_en || selectedResult.name }}</h2><p class="mt-2 text-amber-100">{{ selectedResult.description || '説明はありません。' }}</p><div class="mt-6 flex justify-end"><button class="px-4 py-2 bg-stone-700 text-amber-200 rounded-md" @click="selectedResult = null">閉じる</button></div></div></div>
  </div>
</template>
