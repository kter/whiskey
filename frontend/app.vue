<!-- app.vue -->
<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'
import { useRouter } from 'vue-router'

const { initialize, refreshAuthState, isAuthenticated } = useAuth()

// アプリ起動時に認証状態を確認
onMounted(async () => {
  console.log('App mounted, initializing auth state')
  await initialize()
  
  // 初期化後、さらに認証状態をチェック（OAuth認証後のため）
  if (process.client && window.location.pathname === '/auth/callback') {
    console.log('OAuth callback detected, refreshing auth state')
    setTimeout(async () => {
      await refreshAuthState()
    }, 2000)
  }
})

// ルート変更時にも認証状態を確認
const router = useRouter()
router.afterEach(async (to, from) => {
  // OAuth コールバック以外のページに移動した場合、認証状態を更新
  if (to.path !== '/auth/callback' && from.path === '/auth/callback') {
    console.log('Navigated from OAuth callback, refreshing auth state')
    await refreshAuthState()
    
    // さらに確実にするため、少し待ってからもう一度更新
    setTimeout(async () => {
      await refreshAuthState()
      console.log('Final auth state refresh completed')
    }, 1000)
  }
  
  // 認証が必要なページでの状態確認
  if (to.path === '/reviews' || to.path.startsWith('/reviews')) {
    await refreshAuthState()
  }
})

// 認証状態の変更を監視（デバッグ用）
watch(() => isAuthenticated.value, (newValue) => {
  console.log('Auth state changed in app.vue:', newValue)
})
</script>

<template>
  <div class="min-h-screen bg-amber-950">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template> 