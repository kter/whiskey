<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '~/composables/useAuth'

// フォームの状態
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const confirmationCode = ref('')
const error = ref('')
const success = ref('')
const step = ref<'signup' | 'confirm'>('signup')

// パスワードの要件チェック
const passwordRequirements = ref({
  length: false,
  lowercase: false,
  uppercase: false,
  number: false,
  special: false
})

// パスワード検証
const validatePassword = (pwd: string) => {
  passwordRequirements.value = {
    length: pwd.length >= 8,
    lowercase: /[a-z]/.test(pwd),
    uppercase: /[A-Z]/.test(pwd),
    number: /\d/.test(pwd),
    special: /[!@#$%^&*(),.?":{}|<>]/.test(pwd)
  }
}

// パスワードが要件を満たしているかチェック
const isPasswordValid = computed(() => {
  return Object.values(passwordRequirements.value).every(req => req)
})

const { signUp, confirmSignUp, loading } = useAuth()

// サインアップ処理
const handleSignUp = async () => {
  try {
    error.value = ''
    
    // バリデーション
    if (!email.value || !password.value || !confirmPassword.value) {
      error.value = '全ての項目を入力してください'
      return
    }
    
    if (!isPasswordValid.value) {
      error.value = 'パスワードが要件を満たしていません'
      return
    }
    
    if (password.value !== confirmPassword.value) {
      error.value = 'パスワードが一致しません'
      return
    }
    
    const result = await signUp(email.value, password.value)
    
    if (result.nextStep?.signUpStep === 'CONFIRM_SIGN_UP') {
      step.value = 'confirm'
      success.value = `${email.value} に確認コードを送信しました。`
    }
  } catch (err: any) {
    console.error('Sign up error:', err)
    if (err.name === 'UsernameExistsException') {
      error.value = 'このメールアドレスは既に登録されています'
    } else if (err.name === 'InvalidPasswordException') {
      error.value = 'パスワードが要件を満たしていません'
    } else {
      error.value = err.message || 'サインアップに失敗しました'
    }
  }
}

// メール確認処理
const handleConfirmSignUp = async () => {
  try {
    error.value = ''
    
    if (!confirmationCode.value) {
      error.value = '確認コードを入力してください'
      return
    }
    
    const result = await confirmSignUp(email.value, confirmationCode.value)
    
    if (result.isSignUpComplete) {
      success.value = 'アカウントが正常に作成されました！ログインページに移動します。'
      setTimeout(() => {
        navigateTo('/login')
      }, 2000)
    }
  } catch (err: any) {
    console.error('Confirm sign up error:', err)
    if (err.name === 'CodeMismatchException') {
      error.value = '確認コードが正しくありません'
    } else if (err.name === 'ExpiredCodeException') {
      error.value = '確認コードの有効期限が切れました。再度サインアップしてください。'
    } else {
      error.value = err.message || '確認に失敗しました'
    }
  }
}

// 確認コード再送信
const resendCode = async () => {
  try {
    await signUp(email.value, password.value)
    success.value = '確認コードを再送信しました'
    error.value = ''
  } catch (err: any) {
    error.value = '再送信に失敗しました'
  }
}

// パスワード入力時の検証
watch(password, (newPassword) => {
  validatePassword(newPassword)
})
</script>

<template>
  <div class="min-h-[calc(100vh-4rem)] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
      <!-- ヘッダー -->
      <div class="text-center">
        <h2 class="mt-6 text-center text-3xl font-extrabold text-amber-200">
          {{ step === 'signup' ? '新規登録' : 'メール確認' }}
        </h2>
        <p class="mt-2 text-amber-100 text-sm">
          {{ step === 'signup' ? 'ウイスキーログのアカウントを作成' : 'メールに送信された確認コードを入力' }}
        </p>
      </div>

      <!-- サインアップフォーム -->
      <div v-if="step === 'signup'">
        <form class="mt-8 space-y-6" @submit.prevent="handleSignUp">
          <div class="space-y-4">
            <!-- メールアドレス -->
            <div>
              <label for="email" class="block text-sm font-medium text-amber-200 mb-1">
                メールアドレス
              </label>
              <input
                id="email"
                v-model="email"
                name="email"
                type="email"
                required
                class="appearance-none relative block w-full px-3 py-2 border border-amber-700 placeholder-amber-400 text-amber-100 bg-stone-800 rounded-md focus:outline-none focus:ring-amber-500 focus:border-amber-500 focus:z-10 sm:text-sm"
                placeholder="your@example.com"
              >
            </div>

            <!-- パスワード -->
            <div>
              <label for="password" class="block text-sm font-medium text-amber-200 mb-1">
                パスワード
              </label>
              <input
                id="password"
                v-model="password"
                name="password"
                type="password"
                required
                class="appearance-none relative block w-full px-3 py-2 border border-amber-700 placeholder-amber-400 text-amber-100 bg-stone-800 rounded-md focus:outline-none focus:ring-amber-500 focus:border-amber-500 focus:z-10 sm:text-sm"
                placeholder="パスワード"
              >
              
              <!-- パスワード要件 -->
              <div v-if="password" class="mt-2 space-y-1">
                <div class="text-xs">
                  <div :class="passwordRequirements.length ? 'text-green-400' : 'text-red-400'">
                    ✓ 8文字以上
                  </div>
                  <div :class="passwordRequirements.lowercase ? 'text-green-400' : 'text-red-400'">
                    ✓ 小文字を含む
                  </div>
                  <div :class="passwordRequirements.uppercase ? 'text-green-400' : 'text-red-400'">
                    ✓ 大文字を含む
                  </div>
                  <div :class="passwordRequirements.number ? 'text-green-400' : 'text-red-400'">
                    ✓ 数字を含む
                  </div>
                  <div :class="passwordRequirements.special ? 'text-green-400' : 'text-red-400'">
                    ✓ 記号を含む
                  </div>
                </div>
              </div>
            </div>

            <!-- パスワード確認 -->
            <div>
              <label for="confirmPassword" class="block text-sm font-medium text-amber-200 mb-1">
                パスワード確認
              </label>
              <input
                id="confirmPassword"
                v-model="confirmPassword"
                name="confirmPassword"
                type="password"
                required
                class="appearance-none relative block w-full px-3 py-2 border border-amber-700 placeholder-amber-400 text-amber-100 bg-stone-800 rounded-md focus:outline-none focus:ring-amber-500 focus:border-amber-500 focus:z-10 sm:text-sm"
                placeholder="パスワードを再入力"
              >
              
              <!-- パスワード一致チェック -->
              <div v-if="confirmPassword" class="mt-1">
                <div v-if="password === confirmPassword" class="text-xs text-green-400">
                  ✓ パスワードが一致しています
                </div>
                <div v-else class="text-xs text-red-400">
                  ✗ パスワードが一致しません
                </div>
              </div>
            </div>
          </div>

          <!-- エラー・成功メッセージ -->
          <div v-if="error" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm text-center">
            {{ error }}
          </div>
          
          <div v-if="success" class="text-green-300 bg-green-900/50 p-3 rounded-md border border-green-800 text-sm text-center">
            {{ success }}
          </div>

          <!-- サインアップボタン -->
          <div>
            <button
              type="submit"
              :disabled="loading || !isPasswordValid"
              class="group relative w-full flex justify-center py-3 px-4 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span v-if="loading">登録中...</span>
              <span v-else>アカウントを作成</span>
            </button>
          </div>

          <!-- ログインリンク -->
          <div class="text-center">
            <p class="text-sm text-amber-200">
              既にアカウントをお持ちですか？
              <NuxtLink to="/login" class="font-medium text-amber-400 hover:text-amber-300 transition-colors">
                ログイン
              </NuxtLink>
            </p>
          </div>
        </form>
      </div>

      <!-- 確認コード入力フォーム -->
      <div v-else>
        <form class="mt-8 space-y-6" @submit.prevent="handleConfirmSignUp">
          <div class="space-y-4">
            <!-- 確認コード -->
            <div>
              <label for="confirmationCode" class="block text-sm font-medium text-amber-200 mb-1">
                確認コード
              </label>
              <input
                id="confirmationCode"
                v-model="confirmationCode"
                name="confirmationCode"
                type="text"
                required
                maxlength="6"
                class="appearance-none relative block w-full px-3 py-2 border border-amber-700 placeholder-amber-400 text-amber-100 bg-stone-800 rounded-md focus:outline-none focus:ring-amber-500 focus:border-amber-500 focus:z-10 sm:text-sm text-center tracking-widest"
                placeholder="123456"
              >
              <p class="mt-1 text-xs text-amber-300">
                {{ email }} に送信された6桁のコードを入力してください
              </p>
            </div>
          </div>

          <!-- エラー・成功メッセージ -->
          <div v-if="error" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm text-center">
            {{ error }}
          </div>
          
          <div v-if="success" class="text-green-300 bg-green-900/50 p-3 rounded-md border border-green-800 text-sm text-center">
            {{ success }}
          </div>

          <!-- 確認ボタン -->
          <div>
            <button
              type="submit"
              :disabled="loading"
              class="group relative w-full flex justify-center py-3 px-4 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span v-if="loading">確認中...</span>
              <span v-else>アカウントを確認</span>
            </button>
          </div>

          <!-- 再送信とサインアップに戻る -->
          <div class="flex flex-col space-y-2 text-center">
            <button
              type="button"
              @click="resendCode"
              class="text-sm text-amber-400 hover:text-amber-300 transition-colors"
            >
              確認コードを再送信
            </button>
            <button
              type="button"
              @click="step = 'signup'"
              class="text-sm text-amber-400 hover:text-amber-300 transition-colors"
            >
              サインアップに戻る
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template> 