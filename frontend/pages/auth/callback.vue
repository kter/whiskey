<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated, refreshAuthState } = useAuth()
const error = ref('')

onMounted(async () => {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await refreshAuthState()
    if (isAuthenticated.value) {
      await navigateTo('/logs')
      return
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  error.value = '認証を完了できませんでした。ログイン画面からもう一度お試しください。'
})
</script>

<template>
  <div class="min-h-[50vh] flex items-center justify-center px-4">
    <div class="text-center">
      <p v-if="!error" class="text-amber-200">認証を確認しています...</p>
      <div v-else>
        <p class="text-red-300 mb-4">{{ error }}</p>
        <NuxtLink to="/login" class="text-amber-400 hover:text-amber-300">ログインへ戻る</NuxtLink>
      </div>
    </div>
  </div>
</template>
