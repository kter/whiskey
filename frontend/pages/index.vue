<template>
  <div class="container mx-auto p-4">
    <h1 class="text-2xl font-bold mb-4">ウイスキー一覧</h1>
    <div v-if="error" class="text-red-500 mb-4">
      {{ error }}
    </div>
    <div v-else-if="loading" class="text-gray-500 mb-4">
      読み込み中...
    </div>
    <div v-else>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div v-for="whiskey in whiskeys" :key="whiskey.id" class="border p-4 rounded-lg">
          <h2 class="text-xl font-semibold">{{ whiskey.name }}</h2>
          <p class="text-gray-600">{{ whiskey.distillery }}</p>
          <p class="text-sm mt-2">
            評価: {{ whiskey.avg_rating?.toFixed(1) || '未評価' }}
            ({{ whiskey.review_count || 0 }}件)
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