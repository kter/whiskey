import { ref } from 'vue'
import { Auth } from '@aws-amplify/auth'

export const useAuth = () => {
  const isAuthenticated = ref(false)
  const user = ref(null)
  const loading = ref(true)

  // 認証状態の初期化
  const initialize = async () => {
    try {
      loading.value = true
      const currentUser = await Auth.currentAuthenticatedUser()
      user.value = currentUser
      isAuthenticated.value = true
    } catch (err) {
      user.value = null
      isAuthenticated.value = false
    } finally {
      loading.value = false
    }
  }

  // サインイン
  const signIn = async (username: string, password: string) => {
    try {
      const user = await Auth.signIn(username, password)
      isAuthenticated.value = true
      return user
    } catch (err) {
      throw new Error('ログインに失敗しました')
    }
  }

  // サインアウト
  const signOut = async () => {
    try {
      await Auth.signOut()
      isAuthenticated.value = false
      user.value = null
    } catch (err) {
      throw new Error('ログアウトに失敗しました')
    }
  }

  // パスワードリセット
  const resetPassword = async (username: string) => {
    try {
      await Auth.forgotPassword(username)
    } catch (err) {
      throw new Error('パスワードリセットに失敗しました')
    }
  }

  // パスワードリセットの確認
  const confirmResetPassword = async (
    username: string,
    code: string,
    newPassword: string
  ) => {
    try {
      await Auth.forgotPasswordSubmit(username, code, newPassword)
    } catch (err) {
      throw new Error('パスワードの更新に失敗しました')
    }
  }

  return {
    isAuthenticated,
    user,
    loading,
    initialize,
    signIn,
    signOut,
    resetPassword,
    confirmResetPassword
  }
} 