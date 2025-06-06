<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'
import { watch } from 'vue'

const { isAuthenticated, user, signOut } = useAuth()

const handleSignOut = async () => {
  await signOut()
  navigateTo('/login')
}

// デバッグ用: 認証状態の監視
watch(isAuthenticated, (newValue) => {
  console.log('Auth state changed:', newValue)
})

watch(user, (newValue) => {
  console.log('User changed:', newValue)
})
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
              Auth: {{ isAuthenticated ? 'Yes' : 'No' }}
              <span v-if="user"> | User: {{ user.username || 'Unknown' }}</span>
            </div>
            
            <template v-if="isAuthenticated">
              <span class="mr-4 text-amber-200 text-sm">
                こんにちは、{{ user?.username || 'ユーザー' }}さん
              </span>
              <button
                @click="handleSignOut"
                class="ml-3 inline-flex items-center px-4 py-2 border border-red-800 text-sm font-medium rounded-md text-red-200 bg-red-900 hover:bg-red-800 transition-colors"
              >
                ログアウト
              </button>
            </template>
            <template v-else>
              <NuxtLink
                to="/signup"
                class="ml-3 inline-flex items-center px-4 py-2 border border-blue-700 text-sm font-medium rounded-md text-blue-100 bg-blue-800 hover:bg-blue-700 transition-colors"
              >
                サインイン
              </NuxtLink>
              <NuxtLink
                to="/login"
                class="ml-3 inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
              >
                ログイン
              </NuxtLink>
            </template>
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