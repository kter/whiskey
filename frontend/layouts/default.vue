<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'
import { watch, onMounted, nextTick } from 'vue'

const { isAuthenticated, user, signOut, refreshAuthState, getDisplayName } = useAuth()

const handleSignOut = async () => {
  try {
    console.log('Layout: Starting sign out process')
    await signOut()
    console.log('Layout: Sign out completed, redirecting to login')
    
    // サインアウト後にログインページにリダイレクト
    await navigateTo('/login')
  } catch (error) {
    console.error('Layout: Sign out error:', error)
    
    // エラーが発生してもログインページにリダイレクト
    await navigateTo('/login')
  }
}

// コンポーネントマウント時に認証状態を確認
onMounted(async () => {
  console.log('Layout mounted, refreshing auth state')
  await refreshAuthState()
})

// 認証状態の変更を監視（デバッグ用）
watch(isAuthenticated, (newValue, oldValue) => {
  console.log('Auth state changed in layout:', { from: oldValue, to: newValue })
  // 状態変更時に強制的に再描画
  nextTick(() => {
    console.log('Layout re-rendered after auth state change')
  })
})

watch(user, (newValue, oldValue) => {
  console.log('User changed in layout:', { from: oldValue, to: newValue })
})

// 定期的に認証状態をチェック（開発環境でのデバッグ用）
if (process.client && process.env.NODE_ENV === 'development') {
  setInterval(async () => {
    await refreshAuthState()
  }, 5000) // 5秒ごとにチェック
}
</script>

<template>
  <div>
    <!-- ナビゲーションバー -->
    <nav class="bg-stone-900 shadow-lg border-b border-amber-800">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-16">
          <div class="flex">
            <NuxtLink to="/" class="flex-shrink-0 flex items-center">
              <span class="text-xl font-bold text-amber-200">Whiskey Log</span>
            </NuxtLink>
            <div class="hidden sm:ml-6 sm:flex sm:space-x-8">
              <NuxtLink
                to="/reviews"
                class="inline-flex items-center px-1 pt-1 text-amber-100 hover:text-amber-300 transition-colors"
              >
                レビュー一覧
              </NuxtLink>
              <NuxtLink
                to="/ranking"
                class="inline-flex items-center px-1 pt-1 text-amber-100 hover:text-amber-300 transition-colors"
              >
                ランキング
              </NuxtLink>
            </div>
          </div>
          <div class="flex items-center">
            <!-- デバッグ情報 （開発環境でのみ表示） -->
            <div v-if="$config.public.environment === 'local'" class="mr-4 text-xs text-gray-400">
              Auth: {{ isAuthenticated ? 'Yes' : 'No' }} | User: {{ user?.username || 'None' }}
            </div>
            
            <!-- 認証済みユーザー向けボタン -->
            <div v-if="isAuthenticated" class="flex items-center space-x-3">
              <span class="text-amber-200 text-sm">
                こんにちは、{{ getDisplayName() }}さん
              </span>
              <NuxtLink
                to="/profile"
                class="inline-flex items-center px-3 py-1.5 border border-amber-700 text-xs font-medium rounded-md text-amber-100 bg-stone-700 hover:bg-stone-600 transition-colors"
              >
                プロフィール
              </NuxtLink>
              <button
                @click="handleSignOut"
                class="inline-flex items-center px-4 py-2 border border-red-800 text-sm font-medium rounded-md text-red-200 bg-red-900 hover:bg-red-800 transition-colors"
              >
                ログアウト
              </button>
            </div>
            
            <!-- 未認証ユーザー向けボタン -->
            <div v-else class="flex items-center">
              <NuxtLink
                to="/signup"
                class="inline-flex items-center px-4 py-2 border border-blue-700 text-sm font-medium rounded-md text-blue-100 bg-blue-800 hover:bg-blue-700 transition-colors mr-2"
              >
                サインアップ
              </NuxtLink>
              <NuxtLink
                to="/login"
                class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
              >
                ログイン
              </NuxtLink>
            </div>
          </div>
        </div>
      </div>
    </nav>

    <!-- メインコンテンツ -->
    <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
      <slot />
    </main>
  </div>
</template> 