<template>
  <div>
    <div class="mb-6">
      <NuxtLink 
        to="/reviews" 
        class="inline-flex items-center text-sm text-gray-500 hover:text-gray-700"
      >
        ← レビュー一覧に戻る
      </NuxtLink>
    </div>

    <div class="bg-white shadow rounded-lg p-6">
      <h1 class="text-2xl font-bold text-gray-900 mb-4">
        レビュー詳細
      </h1>
      
      <p class="text-gray-600 mb-4">
        このレビューの詳細ページです。現在開発中です。
      </p>
      
      <div class="flex space-x-3">
        <NuxtLink
          to="/reviews"
          class="inline-flex items-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
        >
          一覧に戻る
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