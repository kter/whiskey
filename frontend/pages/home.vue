<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated } = useAuth()
</script>

<template>
  <div class="text-center">
    <div class="text-8xl mb-6">🥃</div>
    <h1 class="text-5xl font-bold text-amber-200 mb-8">
      Welcome to Whiskey Log
    </h1>
    
    <div class="max-w-2xl mx-auto">
      <p class="text-xl text-amber-100 mb-8">
        あなたのウイスキー体験を記録し、共有しましょう
      </p>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <template v-if="isAuthenticated">
          <NuxtLink
            to="/reviews/new"
            class="inline-flex items-center justify-center px-6 py-4 border border-amber-700 text-lg font-medium rounded-lg text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors shadow-lg"
          >
            ✍️ 新しいレビューを書く
          </NuxtLink>
          <NuxtLink
            to="/reviews"
            class="inline-flex items-center justify-center px-6 py-4 border border-stone-600 text-lg font-medium rounded-lg text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors shadow-lg"
          >
            📝 レビュー一覧を見る
          </NuxtLink>
        </template>
        <template v-else>
          <NuxtLink
            to="/login"
            class="inline-flex items-center justify-center px-6 py-4 border border-amber-700 text-lg font-medium rounded-lg text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors shadow-lg"
          >
            🔓 ログインして始める
          </NuxtLink>
          <NuxtLink
            to="/ranking"
            class="inline-flex items-center justify-center px-6 py-4 border border-stone-600 text-lg font-medium rounded-lg text-amber-200 bg-stone-700 hover:bg-stone-600 transition-colors shadow-lg"
          >
            🏆 ランキングを見る
          </NuxtLink>
        </template>
      </div>
    </div>
  </div>
</template> 