<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import { isGoogleAuthEnabled } from '~/utils/googleAuth'

const config = useRuntimeConfig()
const { signUp, confirmSignUp, resendSignUpCode, googleSignIn, loading } = useAuth()
const mode = ref<'signup' | 'confirm'>('signup')
const email = ref('')
const password = ref('')
const confirmationCode = ref('')
const error = ref('')
const message = ref('')
const googleEnabled = computed(() => isGoogleAuthEnabled(config.public.googleAuthEnabled))

const handleSignUp = async () => {
  error.value = ''
  message.value = ''
  try {
    const result = await signUp(email.value, password.value)
    if (result.isSignUpComplete) await navigateTo('/login')
    else {
      mode.value = 'confirm'
      message.value = '確認コードを送信しました。'
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登録情報を確認できませんでした。'
  }
}

const handleConfirm = async () => {
  error.value = ''
  message.value = ''
  try {
    const result = await confirmSignUp(email.value, confirmationCode.value)
    if (result.isSignUpComplete) await navigateTo('/login')
    else message.value = '追加の確認操作が必要です。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登録情報を確認できませんでした。'
  }
}

const handleResend = async () => {
  error.value = ''
  message.value = ''
  try {
    await resendSignUpCode(email.value)
    message.value = '確認コードを再送しました。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登録情報を確認できませんでした。'
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
        <h1 class="text-3xl font-extrabold text-amber-200">{{ mode === 'signup' ? '新規登録' : 'メールアドレスの確認' }}</h1>
        <p class="mt-2 text-amber-100 text-sm">{{ mode === 'signup' ? 'メールアドレスでアカウントを作成します' : 'メールに届いた確認コードを入力してください' }}</p>
      </div>

      <form v-if="mode === 'signup'" class="space-y-5 bg-stone-800 p-6 rounded-lg border border-amber-700" @submit.prevent="handleSignUp">
        <div>
          <label for="signup-email" class="block text-sm font-medium text-amber-200">メールアドレス</label>
          <input id="signup-email" v-model="email" type="email" autocomplete="email" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
        </div>
        <div>
          <label for="signup-password" class="block text-sm font-medium text-amber-200">パスワード</label>
          <input id="signup-password" v-model="password" type="password" autocomplete="new-password" minlength="8" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
          <p class="mt-1 text-xs text-amber-400">8文字以上で入力してください。</p>
        </div>
        <button type="submit" :disabled="loading" class="w-full py-3 px-4 rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 disabled:opacity-50">
          {{ loading ? '登録中...' : 'メールで登録' }}
        </button>
        <button type="button" class="w-full text-sm text-amber-400 hover:text-amber-300" @click="mode = 'confirm'">
          すでに確認コードをお持ちの方
        </button>
      </form>

      <form v-else class="space-y-5 bg-stone-800 p-6 rounded-lg border border-amber-700" @submit.prevent="handleConfirm">
        <div>
          <label for="confirm-email" class="block text-sm font-medium text-amber-200">登録したメールアドレス</label>
          <input id="confirm-email" v-model="email" type="email" autocomplete="email" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
        </div>
        <div>
          <label for="confirmation-code" class="block text-sm font-medium text-amber-200">確認コード</label>
          <input id="confirmation-code" v-model="confirmationCode" inputmode="numeric" autocomplete="one-time-code" required class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100" />
        </div>
        <button type="submit" :disabled="loading" class="w-full py-3 px-4 rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 disabled:opacity-50">確認する</button>
        <div class="flex justify-between text-sm">
          <button type="button" class="text-amber-400 hover:text-amber-300" @click="handleResend">コードを再送</button>
          <button type="button" class="text-amber-400 hover:text-amber-300" @click="mode = 'signup'">登録へ戻る</button>
        </div>
      </form>

      <p v-if="error" role="alert" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm">{{ error }}</p>
      <p v-if="message" class="text-green-300 bg-green-900/50 p-3 rounded-md border border-green-800 text-sm">{{ message }}</p>

      <div v-if="googleEnabled" class="space-y-3">
        <div class="text-center text-sm text-amber-300">または</div>
        <button type="button" :disabled="loading" class="w-full py-3 px-4 rounded-lg text-stone-800 bg-white hover:bg-gray-50 disabled:opacity-50" @click="handleGoogleSignIn">Googleで登録</button>
      </div>

      <p class="text-center text-sm text-amber-200">すでにアカウントをお持ちですか？ <NuxtLink to="/login" class="text-amber-400 hover:text-amber-300">ログイン</NuxtLink></p>
    </div>
  </div>
</template>
