import { ref, readonly } from 'vue'
import { signIn, signOut, signUp, confirmSignUp, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword, signInWithRedirect, type AuthUser } from '@aws-amplify/auth'

// グローバルな認証状態（シングルトンパターン）
const isAuthenticated = ref(false)
const user = ref<AuthUser | null>(null)
const loading = ref(false)

export const useAuth = () => {
  const config = useRuntimeConfig()

  // 認証状態の初期化
  const initialize = async () => {
    try {
      loading.value = true
      console.log('Initializing auth state...')
      const currentUser = await getCurrentUser()
      console.log('Current user:', currentUser)
      
      if (currentUser) {
        user.value = currentUser
        isAuthenticated.value = true
        console.log('User authenticated successfully')
      } else {
        console.log('No authenticated user found')
        isAuthenticated.value = false
        user.value = null
      }
    } catch (error) {
      console.log('No authenticated user:', error)
      isAuthenticated.value = false
      user.value = null
    } finally {
      loading.value = false
    }
  }

  // 強制的に認証状態を更新
  const refreshAuthState = async () => {
    console.log('Refreshing auth state...')
    await initialize()
  }

  // アクセストークン取得（エラーハンドリング改善）
  const getToken = async (): Promise<string> => {
    try {
      const currentUser = await getCurrentUser()
      // 現在は開発中なので簡単なトークンを返す
      if (currentUser) {
        return 'development-token'
      }
      throw new Error('User not authenticated')
    } catch (error) {
      console.error('Error getting token:', error)
      throw error
    }
  }

  // 認証状態に関係なくトークンを取得（optional）
  const getTokenSafely = async (): Promise<string | null> => {
    try {
      return await getToken()
    } catch (error: any) {
      console.log('Token not available:', error.message)
      return null
    }
  }

  // サインイン
  const handleSignIn = async (username: string, password: string) => {
    try {
      loading.value = true
      const { isSignedIn, nextStep } = await signIn({ username, password })
      
      if (isSignedIn) {
        const currentUser = await getCurrentUser()
        user.value = currentUser
        isAuthenticated.value = true
      }
      
      return { isSignedIn, nextStep }
    } catch (error) {
      console.error('Sign in error:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // サインアウト
  const handleSignOut = async () => {
    try {
      loading.value = true
      await signOut()
      isAuthenticated.value = false
      user.value = null
      console.log('User signed out successfully')
    } catch (error) {
      console.error('Sign out error:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // サインアップ
  const handleSignUp = async (email: string, password: string) => {
    try {
      loading.value = true
      const { isSignUpComplete, userId, nextStep } = await signUp({
        username: email,
        password,
        options: {
          userAttributes: {
            email,
          },
        },
      })
      
      return { isSignUpComplete, userId, nextStep }
    } catch (error) {
      console.error('Sign up error:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // メール確認コードの検証
  const handleConfirmSignUp = async (email: string, confirmationCode: string) => {
    try {
      loading.value = true
      const { isSignUpComplete, nextStep } = await confirmSignUp({
        username: email,
        confirmationCode,
      })

      return { isSignUpComplete, nextStep }
    } catch (error) {
      console.error('Confirm sign up error:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // パスワードリセット
  const handleResetPassword = async (username: string) => {
    try {
      const output = await resetPassword({ username })
      return output
    } catch (error) {
      console.error('Reset password error:', error)
      throw error
    }
  }

  // パスワードリセットの確認
  const handleConfirmResetPassword = async (
    username: string,
    confirmationCode: string,
    newPassword: string
  ) => {
    try {
      await confirmResetPassword({
        username,
        confirmationCode,
        newPassword
      })
    } catch (error) {
      console.error('Confirm reset password error:', error)
      throw error
    }
  }

  // Google認証
  const handleGoogleSignIn = async () => {
    try {
      loading.value = true
      console.log('Starting Google sign in...')
      await signInWithRedirect({ provider: { custom: 'Google' } })
    } catch (error: any) {
      console.error('Google sign in error:', error)
      
      // エラーの詳細情報をログに出力
      if (error.message) {
        console.error('Error message:', error.message)
      }
      if (error.code) {
        console.error('Error code:', error.code)
      }
      
      // ユーザーフレンドリーなエラーメッセージを作成
      let userMessage = 'Google認証に失敗しました。'
      if (error.message && error.message.includes('redirect')) {
        userMessage = 'リダイレクトの設定に問題があります。管理者にお問い合わせください。'
      }
      
      throw new Error(userMessage)
    } finally {
      loading.value = false
    }
  }

  return {
    // 読み取り専用の状態を返す
    isAuthenticated: readonly(isAuthenticated),
    user: readonly(user),
    loading: readonly(loading),
    initialize,
    refreshAuthState,
    getToken,
    getTokenSafely,
    signIn: handleSignIn,
    signOut: handleSignOut,
    signUp: handleSignUp,
    confirmSignUp: handleConfirmSignUp,
    resetPassword: handleResetPassword,
    confirmResetPassword: handleConfirmResetPassword,
    googleSignIn: handleGoogleSignIn
  }
} 