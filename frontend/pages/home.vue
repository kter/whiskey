<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated } = useAuth()
</script>

<template>
  <div class="text-center">
    <h1 class="text-4xl font-bold text-gray-900 mb-8">
      Welcome to Whiskey Log
    </h1>
    
    <div class="max-w-2xl mx-auto">
      <p class="text-xl text-gray-600 mb-8">
        あなたのウイスキー体験を記録し、共有しましょう
      </p>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <template v-if="isAuthenticated">
          <NuxtLink
            to="/reviews/new"
            class="inline-flex items-center justify-center px-6 py-4 border border-transparent text-lg font-medium rounded-lg text-white bg-indigo-600 hover:bg-indigo-700"
          >
            新しいレビューを書く
          </NuxtLink>
          <NuxtLink
            to="/reviews"
            class="inline-flex items-center justify-center px-6 py-4 border border-transparent text-lg font-medium rounded-lg text-indigo-700 bg-indigo-100 hover:bg-indigo-200"
          >
            レビュー一覧を見る
          </NuxtLink>
        </template>
        <template v-else>
          <NuxtLink
            to="/login"
            class="inline-flex items-center justify-center px-6 py-4 border border-transparent text-lg font-medium rounded-lg text-white bg-indigo-600 hover:bg-indigo-700"
          >
            ログインして始める
          </NuxtLink>
          <NuxtLink
            to="/ranking"
            class="inline-flex items-center justify-center px-6 py-4 border border-transparent text-lg font-medium rounded-lg text-indigo-700 bg-indigo-100 hover:bg-indigo-200"
          >
            ランキングを見る
          </NuxtLink>
        </template>
      </div>
    </div>
  </div>
</template> 