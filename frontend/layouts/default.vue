<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated, authReady, signOut, getDisplayName } = useAuth()

const handleSignOut = async () => {
  try {
    await signOut()
  } catch (error) {
    console.error('Amplify sign out failed; the local Cognito session was cleared.', error)
  }
  await navigateTo('/login')
}
</script>

<template>
  <div>
    <nav class="bg-stone-900 shadow-lg border-b border-amber-800">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-16">
          <div class="flex">
            <NuxtLink to="/" class="flex-shrink-0 flex items-center">
              <span class="text-xl font-bold text-amber-200">Whiskey Log</span>
            </NuxtLink>
            <div class="hidden sm:ml-6 sm:flex sm:space-x-8">
              <NuxtLink to="/reviews" class="inline-flex items-center px-1 pt-1 text-amber-100 hover:text-amber-300 transition-colors">
                レビュー一覧
              </NuxtLink>
              <NuxtLink to="/search" class="inline-flex items-center px-1 pt-1 text-amber-100 hover:text-amber-300 transition-colors">
                ウイスキー検索
              </NuxtLink>
              <NuxtLink to="/ranking" class="inline-flex items-center px-1 pt-1 text-amber-100 hover:text-amber-300 transition-colors">
                ランキング
              </NuxtLink>
            </div>
          </div>
          <div v-if="authReady" class="flex items-center">
            <div v-if="isAuthenticated" class="flex items-center space-x-3">
              <span class="hidden sm:inline text-amber-200 text-sm">こんにちは、{{ getDisplayName() }}さん</span>
              <NuxtLink to="/profile" class="px-3 py-1.5 border border-amber-700 text-xs font-medium rounded-md text-amber-100 bg-stone-700 hover:bg-stone-600">
                プロフィール
              </NuxtLink>
              <button class="px-4 py-2 border border-red-800 text-sm font-medium rounded-md text-red-200 bg-red-900 hover:bg-red-800" @click="handleSignOut">
                ログアウト
              </button>
            </div>
            <div v-else class="flex items-center">
              <NuxtLink to="/signup" class="px-4 py-2 border border-blue-700 text-sm font-medium rounded-md text-blue-100 bg-blue-800 hover:bg-blue-700 mr-2">
                サインアップ
              </NuxtLink>
              <NuxtLink to="/login" class="px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700">
                ログイン
              </NuxtLink>
            </div>
          </div>
        </div>
      </div>
    </nav>
    <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
      <slot />
    </main>
  </div>
</template>
