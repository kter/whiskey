<script setup lang="ts">
import { onMounted } from 'vue'
import { useWhiskeys } from '~/composables/useWhiskeys'

const { whiskeys, nextToken, loading, error, fetchWhiskeyList } = useWhiskeys()
onMounted(() => void fetchWhiskeyList({ limit: 12 }))
const loadMore = () => nextToken.value && fetchWhiskeyList({ limit: 12, next_token: nextToken.value }, true)
</script>

<template>
  <div class="container mx-auto p-4">
    <h1 class="text-3xl font-bold mb-6 text-amber-200">ウイスキー一覧</h1>
    <p v-if="error" role="alert" class="text-red-300 bg-red-900/50 p-4 rounded-lg mb-4 border border-red-800">{{ error }}</p>
    <div v-if="loading && whiskeys.length === 0" class="text-amber-300 mb-4">読み込み中...</div>
    <p v-else-if="whiskeys.length === 0" class="text-amber-300 text-center py-8">ウイスキーデータがありません</p>
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <article v-for="whiskey in whiskeys" :key="whiskey.id" class="bg-stone-800 border border-amber-700 p-6 rounded-lg shadow-lg hover:border-amber-500">
        <h2 class="text-xl font-semibold text-amber-200 mb-2">{{ whiskey.name }}</h2>
        <p class="text-amber-100">{{ whiskey.distillery }}</p>
      </article>
    </div>
    <div v-if="nextToken" class="mt-8 text-center"><button :disabled="loading" class="px-5 py-2 rounded-md text-amber-100 bg-amber-800 disabled:opacity-50" @click="loadMore">{{ loading ? '読み込み中...' : 'さらに読み込む' }}</button></div>
  </div>
</template>
