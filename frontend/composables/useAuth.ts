import { ref } from 'vue'
import { signIn, signOut, signUp, confirmSignUp, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword, type AuthUser } from '@aws-amplify/auth'

export const useAuth = () => {
  const isAuthenticated = ref(false)
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)
  const config = useRuntimeConfig()

  // 認証状態の初期化
  const initialize = async () => {
    try {
      loading.value = true
      const currentUser = await getCurrentUser()
      if (currentUser) {
        user.value = currentUser
        isAuthenticated.value = true
      }
    } catch (error) {
      console.log('No authenticated user')
      isAuthenticated.value = false
      user.value = null
    } finally {
      loading.value = false
    }
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
    } catch (error) {
      console.error('Sign out error:', error)
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

  // Google認証 
  const handleGoogleSignIn = async () => {
    try {
      loading.value = true
      const { isSignedIn, nextStep } = await signIn({
        username: '', // Google認証では不要
        password: '', // Google認証では不要
        options: {
          authFlowType: 'CUSTOM_WITH_SRP', // Google OAuth flow
        }
      })

      if (isSignedIn) {
        const currentUser = await getCurrentUser()
        user.value = currentUser
        isAuthenticated.value = true
      }

      return { isSignedIn, nextStep }
    } catch (error) {
      console.error('Google sign in error:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  return {
    isAuthenticated,
    user,
    loading,
    initialize,
    getToken,
    getTokenSafely,
    signIn: handleSignIn,
    signOut: handleSignOut,
    signUp: handleSignUp,
    confirmSignUp: handleConfirmSignUp,
    googleSignIn: handleGoogleSignIn,
    resetPassword: handleResetPassword,
    confirmResetPassword: handleConfirmResetPassword
  }
} 