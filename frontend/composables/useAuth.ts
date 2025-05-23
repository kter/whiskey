import { ref } from 'vue'
// import { signIn, signOut, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword } from '@aws-amplify/auth'

export const useAuth = () => {
  const isAuthenticated = ref(false)
  const user = ref(null)
  const loading = ref(false)

  // 認証状態の初期化
  const initialize = async () => {
    console.log('Auth initialize called (disabled for debugging)')
    loading.value = false
  }

  // トークン取得（ダミー実装）
  const getToken = async () => {
    console.log('getToken called (disabled for debugging)')
    return 'dummy-token'
  }

  // サインイン
  const handleSignIn = async (username: string, password: string) => {
    console.log('SignIn called (disabled for debugging)', username)
    isAuthenticated.value = true
    return { isSignedIn: true }
  }

  // サインアウト
  const handleSignOut = async () => {
    console.log('SignOut called (disabled for debugging)')
    isAuthenticated.value = false
    user.value = null
  }

  // パスワードリセット
  const handleResetPassword = async (username: string) => {
    console.log('Reset password called (disabled for debugging)', username)
  }

  // パスワードリセットの確認
  const handleConfirmResetPassword = async (
    username: string,
    code: string,
    newPassword: string
  ) => {
    console.log('Confirm reset password called (disabled for debugging)', username)
  }

  return {
    isAuthenticated,
    user,
    loading,
    initialize,
    getToken,
    signIn: handleSignIn,
    signOut: handleSignOut,
    resetPassword: handleResetPassword,
    confirmResetPassword: handleConfirmResetPassword
  }
} 