<!-- app.vue -->
<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { initialize } = useAuth()

// アプリ起動時に認証状態を確認
onMounted(async () => {
  await initialize()
})
</script>

<template>
  <div class="min-h-screen bg-gray-100">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template> 