<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import { isGoogleAuthEnabled } from '~/utils/googleAuth'

const config = useRuntimeConfig()
const { signIn, googleSignIn, loading } = useAuth()
const email = ref('')
const password = ref('')
const error = ref('')
const googleEnabled = computed(() => isGoogleAuthEnabled(config.public.googleAuthEnabled))

const handleSignIn = async () => {
  error.value = ''
  try {
    const result = await signIn(email.value, password.value)
    if (result.isSignedIn) await navigateTo('/reviews')
    else error.value = '追加の認証操作が必要です。もう一度お試しください。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '認証情報を確認できませんでした。'
  }
}

const handleGoogleSignIn = async () => {
  error.value = ''
  try {
    await googleSignIn()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '認証情報を確認できませんでした。'
  }
}
</script>

<template>
  <div class="min-h-[calc(100vh-4rem)] flex items-center justify-center py-12 px-4">
    <div class="max-w-md w-full space-y-8">
      <div class="text-center">
        <h1 class="text-3xl font-extrabold text-amber-200">ログイン</h1>
        <p class="mt-2 text-amber-100 text-sm">メールアドレスとパスワードを入力してください</p>
      </div>

      <form class="space-y-5 bg-stone-800 p-6 rounded-lg border border-amber-700" @submit.prevent="handleSignIn">
        <div>
          <label for="login-email" class="block text-sm font-medium text-amber-200">メールアドレス</label>
          <input id="login-email" v-model="email" type="email" autocomplete="email" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
        </div>
        <div>
          <label for="login-password" class="block text-sm font-medium text-amber-200">パスワード</label>
          <input id="login-password" v-model="password" type="password" autocomplete="current-password" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
        </div>
        <p v-if="error" role="alert" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm">{{ error }}</p>
        <button type="submit" :disabled="loading" class="w-full py-3 px-4 rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 disabled:opacity-50">
          {{ loading ? '認証中...' : 'メールでログイン' }}
        </button>
      </form>

      <div v-if="googleEnabled" class="space-y-3">
        <div class="text-center text-sm text-amber-300">または</div>
        <button type="button" :disabled="loading" class="w-full py-3 px-4 rounded-lg text-stone-800 bg-white hover:bg-gray-50 disabled:opacity-50" @click="handleGoogleSignIn">
          Googleでログイン
        </button>
      </div>

      <p class="text-center text-sm text-amber-200">
        アカウントをお持ちでない方は
        <NuxtLink to="/signup" class="text-amber-400 hover:text-amber-300">新規登録</NuxtLink>
      </p>
    </div>
  </div>
</template>
