import { ref } from 'vue'
import { signIn, signOut, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword } from '@aws-amplify/auth'

export const useAuth = () => {
  const isAuthenticated = ref(false)
  const user = ref(null)
  const loading = ref(true)

  // 認証状態の初期化
  const initialize = async () => {
    try {
      loading.value = true
      const currentUser = await getCurrentUser()
      const attributes = await fetchUserAttributes()
      user.value = { ...currentUser, attributes }
      isAuthenticated.value = true
    } catch (err) {
      user.value = null
      isAuthenticated.value = false
    } finally {
      loading.value = false
    }
  }

  // サインイン
  const handleSignIn = async (username: string, password: string) => {
    try {
      const result = await signIn({ username, password })
      isAuthenticated.value = true
      return result
    } catch (err) {
      throw new Error('ログインに失敗しました')
    }
  }

  // サインアウト
  const handleSignOut = async () => {
    try {
      await signOut()
      isAuthenticated.value = false
      user.value = null
    } catch (err) {
      throw new Error('ログアウトに失敗しました')
    }
  }

  // パスワードリセット
  const handleResetPassword = async (username: string) => {
    try {
      await resetPassword({ username })
    } catch (err) {
      throw new Error('パスワードリセットに失敗しました')
    }
  }

  // パスワードリセットの確認
  const handleConfirmResetPassword = async (
    username: string,
    code: string,
    newPassword: string
  ) => {
    try {
      await confirmResetPassword({ username, confirmationCode: code, newPassword })
    } catch (err) {
      throw new Error('パスワードの更新に失敗しました')
    }
  }

  return {
    isAuthenticated,
    user,
    loading,
    initialize,
    signIn: handleSignIn,
    signOut: handleSignOut,
    resetPassword: handleResetPassword,
    confirmResetPassword: handleConfirmResetPassword
  }
} 