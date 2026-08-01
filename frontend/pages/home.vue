<script setup lang="ts">
import { useAuth } from '~/composables/useAuth'

const { isAuthenticated } = useAuth()
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-10 text-center">
    <p class="mb-3 text-sm font-medium tracking-[0.2em] text-amber-400">
      写真ではじめるテイスティング記録
    </p>
    <h1 class="mb-6 text-4xl font-bold text-amber-200 sm:text-5xl">
      今日の一杯を記録
    </h1>
    <p class="mx-auto mb-10 max-w-2xl text-lg leading-8 text-amber-100">
      写真から銘柄と飲み方を見つけ、店名やメモと一緒に残せます。
      あなたの一杯を、あとから振り返れるタイムラインへ。
    </p>

    <div class="mx-auto grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
      <template v-if="isAuthenticated">
        <NuxtLink
          to="/logs/new"
          class="inline-flex items-center justify-center rounded-lg border border-amber-600 bg-amber-800 px-6 py-4 text-lg font-medium text-amber-100 shadow-lg transition-colors hover:bg-amber-700"
        >
          今日の一杯を記録
        </NuxtLink>
        <NuxtLink
          to="/logs"
          class="inline-flex items-center justify-center rounded-lg border border-stone-600 bg-stone-700 px-6 py-4 text-lg font-medium text-amber-200 shadow-lg transition-colors hover:bg-stone-600"
        >
          これまでの記録を見る
        </NuxtLink>
      </template>
      <template v-else>
        <NuxtLink
          to="/login"
          class="inline-flex items-center justify-center rounded-lg border border-amber-600 bg-amber-800 px-6 py-4 text-lg font-medium text-amber-100 shadow-lg transition-colors hover:bg-amber-700"
        >
          ログインして記録する
        </NuxtLink>
        <NuxtLink
          to="/search"
          class="inline-flex items-center justify-center rounded-lg border border-stone-600 bg-stone-700 px-6 py-4 text-lg font-medium text-amber-200 shadow-lg transition-colors hover:bg-stone-600"
        >
          ウイスキーを検索
        </NuxtLink>
      </template>
    </div>
  </div>
</template>
