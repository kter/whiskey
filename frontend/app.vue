<!-- app.vue -->
<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'
import { useRouter } from 'vue-router'

const { initialize, refreshAuthState } = useAuth()

// アプリ起動時に認証状態を確認
onMounted(async () => {
  console.log('App mounted, initializing auth state')
  await initialize()
})

// ルート変更時にも認証状態を確認
const router = useRouter()
router.afterEach(async (to, from) => {
  // OAuth コールバック以外のページに移動した場合、認証状態を更新
  if (to.path !== '/auth/callback' && from.path === '/auth/callback') {
    console.log('Navigated from OAuth callback, refreshing auth state')
    await refreshAuthState()
  }
})
</script>

<template>
  <div class="min-h-screen bg-amber-950">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template> 