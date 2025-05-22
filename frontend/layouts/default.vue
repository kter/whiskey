<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated, signOut } = useAuth()

const handleSignOut = async () => {
  await signOut()
  navigateTo('/login')
}
</script>

<template>
  <div>
    <!-- ナビゲーションバー -->
    <nav class="bg-white shadow">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-16">
          <div class="flex">
            <NuxtLink to="/" class="flex-shrink-0 flex items-center">
              <span class="text-xl font-bold text-gray-800">Whiskey Log</span>
            </NuxtLink>
            <div class="hidden sm:ml-6 sm:flex sm:space-x-8">
              <NuxtLink
                to="/reviews"
                class="inline-flex items-center px-1 pt-1 text-gray-500 hover:text-gray-700"
              >
                レビュー一覧
              </NuxtLink>
              <NuxtLink
                to="/ranking"
                class="inline-flex items-center px-1 pt-1 text-gray-500 hover:text-gray-700"
              >
                ランキング
              </NuxtLink>
              <NuxtLink
                to="/stats"
                class="inline-flex items-center px-1 pt-1 text-gray-500 hover:text-gray-700"
              >
                統計
              </NuxtLink>
            </div>
          </div>
          <div class="flex items-center">
            <template v-if="isAuthenticated">
              <button
                @click="handleSignOut"
                class="ml-3 inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700"
              >
                ログアウト
              </button>
            </template>
            <template v-else>
              <NuxtLink
                to="/login"
                class="ml-3 inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
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