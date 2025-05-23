<template>
  <div class="container mx-auto p-4">
    <h1 class="text-3xl font-bold mb-6 text-amber-200">🥃 ウイスキー一覧</h1>
    <div v-if="error" class="text-red-300 bg-red-900/50 p-4 rounded-lg mb-4 border border-red-800">
      {{ error }}
    </div>
    <div v-else-if="loading" class="text-amber-300 mb-4">
      読み込み中...
    </div>
    <div v-else>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div v-for="whiskey in whiskeys" :key="whiskey.id" class="bg-stone-800 border border-amber-700 p-6 rounded-lg shadow-lg hover:shadow-xl transition-all hover:border-amber-500">
          <h2 class="text-xl font-semibold text-amber-200 mb-2">{{ whiskey.name }}</h2>
          <p class="text-amber-100 mb-3">🏭 {{ whiskey.distillery }}</p>
          <p class="text-sm text-amber-300">
            ⭐ 評価: {{ whiskey.avg_rating?.toFixed(1) || '未評価' }}
            ({{ whiskey.review_count || 0 }}件のレビュー)
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const config = useRuntimeConfig()
const whiskeys = ref([])
const loading = ref(true)
const error = ref(null)

onMounted(async () => {
  try {
    const response = await fetch(`${config.public.apiBase}/api/whiskeys/ranking/`)
    if (!response.ok) {
      throw new Error('APIの呼び出しに失敗しました')
    }
    whiskeys.value = await response.json()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script> 