<template>
  <div class="container mx-auto p-4">
    <h1 class="text-3xl font-bold mb-6 text-amber-200">ウイスキー一覧</h1>
    <div v-if="error" class="text-red-300 bg-red-900/50 p-4 rounded-lg mb-4 border border-red-800">
      {{ error }}
    </div>
    <div v-else-if="loading" class="text-amber-300 mb-4">
      読み込み中...
    </div>
    <div v-else>
      <div v-if="whiskeys.length === 0" class="text-amber-300 text-center py-8">
        ウィスキーデータがありません
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div v-for="whiskey in whiskeys" :key="whiskey.id" class="bg-stone-800 border border-amber-700 p-6 rounded-lg shadow-lg hover:shadow-xl transition-all hover:border-amber-500">
          <h2 class="text-xl font-semibold text-amber-200 mb-2">{{ whiskey.name }}</h2>
          <p class="text-amber-100 mb-3">{{ whiskey.distillery }}</p>
          <p class="text-sm text-amber-300">
            評価: {{ whiskey.avg_rating?.toFixed(1) || '未評価' }}
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
    console.log('API Base URL:', config.public.apiBase)
    const apiUrl = `${config.public.apiBase}/api/whiskeys/ranking/`
    console.log('Fetching from:', apiUrl)
    
    const response = await fetch(apiUrl)
    console.log('Response status:', response.status)
    console.log('Response ok:', response.ok)
    
    if (!response.ok) {
      throw new Error(`APIの呼び出しに失敗しました (${response.status}: ${response.statusText})`)
    }
    
    const data = await response.json()
    console.log('Received data:', data)
    whiskeys.value = data
    
    if (data.length === 0) {
      console.log('No whiskeys found in the response')
    } else {
      console.log(`Loaded ${data.length} whiskeys`)
    }
  } catch (e) {
    console.error('API Error:', e)
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script> 