<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '~/composables/useAuth'

const { googleSignIn, loading } = useAuth()
const error = ref('')

// Googleサインイン処理
const handleGoogleSignIn = async () => {
  try {
    error.value = ''
    await googleSignIn()
  } catch (err: any) {
    console.error('Google sign in error:', err)
    error.value = err.message || 'Google認証に失敗しました'
  }
}
</script>

<template>
  <div class="min-h-[calc(100vh-4rem)] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
      <!-- ヘッダー -->
      <div class="text-center">
        <h2 class="mt-6 text-center text-3xl font-extrabold text-amber-200">
          ウイスキーログへようこそ
        </h2>
        <p class="mt-2 text-amber-100 text-sm">
          Googleアカウントでサインインして始めましょう
        </p>
      </div>

      <!-- Google サインイン -->
      <div class="mt-8">
        <!-- エラーメッセージ -->
        <div v-if="error" class="mb-4 text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm text-center">
          {{ error }}
        </div>

        <!-- Googleサインインボタン -->
        <button
          @click="handleGoogleSignIn"
          :disabled="loading"
          class="w-full flex justify-center items-center py-4 px-6 border border-gray-600 text-lg font-medium rounded-lg text-gray-100 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
        >
          <svg class="w-6 h-6 mr-3" viewBox="0 0 24 24">
            <path fill="#4285f4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34a853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#fbbc05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#ea4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          <span v-if="loading" class="text-gray-700">認証中...</span>
          <span v-else class="text-gray-700">Googleでサインイン</span>
        </button>

        <!-- 既にアカウントをお持ちの場合 -->
        <div class="mt-6 text-center">
          <p class="text-sm text-amber-200">
            既にアカウントをお持ちですか？
            <NuxtLink to="/login" class="font-medium text-amber-400 hover:text-amber-300 transition-colors">
              ログイン
            </NuxtLink>
          </p>
        </div>

        <!-- プライバシー情報 -->
        <div class="mt-8 text-center">
          <p class="text-xs text-amber-300 max-w-sm mx-auto">
            Googleでサインインすることで、メールアドレスやプロフィール情報を安全に管理できます。
            個人情報は適切に保護されます。
          </p>
        </div>
      </div>
    </div>
  </div>
</template> 