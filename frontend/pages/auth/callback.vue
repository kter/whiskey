<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { initialize, refreshAuthState, isAuthenticated } = useAuth()
const loading = ref(true)
const error = ref('')

// ページマウント時に認証状態を確認
onMounted(async () => {
  try {
    console.log('OAuth callback page mounted')
    console.log('Current URL:', window.location.href)
    console.log('URL params:', new URLSearchParams(window.location.search).toString())
    
    // OAuth認証処理後の待機時間を延長
    console.log('Waiting for OAuth processing to complete...')
    await new Promise(resolve => setTimeout(resolve, 3000))
    
    // 複数回のリトライで認証状態を確認
    let retryCount = 0
    const maxRetries = 5
    
    while (retryCount < maxRetries) {
      console.log(`Attempt ${retryCount + 1}/${maxRetries}: Checking auth state`)
      
      // 認証状態を更新
      await refreshAuthState()
      
      if (isAuthenticated.value) {
        console.log('Authentication successful!')
        break
      }
      
      retryCount++
      if (retryCount < maxRetries) {
        console.log(`Auth not ready yet, waiting 2 seconds before retry...`)
        await new Promise(resolve => setTimeout(resolve, 2000))
      }
    }
    
    // 最終的な認証状態を確認
    if (isAuthenticated.value) {
      console.log('OAuth authentication successful, redirecting to home')
      
      // 成功メッセージを短時間表示してからリダイレクト
      await new Promise(resolve => setTimeout(resolve, 1000))
      
      // ホームページにリダイレクト
      await navigateTo('/')
    } else {
      console.log('OAuth authentication failed after all retries')
      error.value = '認証に失敗しました。ブラウザを更新して再度お試しください。'
    }
  } catch (err: any) {
    console.error('OAuth callback error:', err)
    error.value = err.message || '認証処理中にエラーが発生しました。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="min-h-[calc(100vh-4rem)] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8 text-center">
      <!-- ローディング状態 -->
      <div v-if="loading">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-amber-200 mx-auto mb-4"></div>
        <h2 class="text-2xl font-bold text-amber-200">認証を確認中...</h2>
        <p class="text-amber-100 text-sm mt-2">
          Googleアカウントでの認証を処理しています
        </p>
        <p class="text-amber-300 text-xs mt-4">
          この処理には数秒かかる場合があります
        </p>
      </div>

      <!-- エラー状態 -->
      <div v-else-if="error">
        <div class="text-red-400 mb-4">
          <svg class="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.992-.833-2.732 0L3.732 15c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <h2 class="text-2xl font-bold text-red-400">認証エラー</h2>
        <p class="text-red-300 text-sm mt-2 mb-4">
          {{ error }}
        </p>
        <div class="space-y-3">
          <NuxtLink
            to="/login"
            class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
          >
            ログインページに戻る
          </NuxtLink>
          <button
            @click="window.location.reload()"
            class="block mx-auto text-amber-300 hover:text-amber-200 text-sm"
          >
            ページを更新する
          </button>
        </div>
      </div>

      <!-- 成功状態（リダイレクト前の短時間表示） -->
      <div v-else>
        <div class="text-green-400 mb-4">
          <svg class="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 class="text-2xl font-bold text-green-400">認証成功</h2>
        <p class="text-green-300 text-sm mt-2">
          ホームページにリダイレクト中...
        </p>
      </div>
    </div>
  </div>
</template> 