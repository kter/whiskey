<template>
  <div>
    <div class="mb-6">
      <NuxtLink 
        to="/reviews" 
        class="inline-flex items-center text-sm text-amber-300 hover:text-amber-100 transition-colors"
      >
        ← レビュー一覧に戻る
      </NuxtLink>
    </div>

    <div class="bg-stone-800 shadow-lg rounded-lg p-6 border border-amber-700">
      <h1 class="text-3xl font-bold text-amber-200 mb-4">
        📝 レビュー詳細
      </h1>
      
      <p class="text-amber-100 mb-6">
        このレビューの詳細ページです。現在開発中です。
      </p>
      
      <div class="flex space-x-3">
        <NuxtLink
          to="/reviews"
          class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
        >
          📋 一覧に戻る
        </NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 簡単なプレースホルダー実装
// 将来的にはAPIからレビューデータを取得
const route = useRoute()
</script> 