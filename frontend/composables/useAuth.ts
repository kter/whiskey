import { ref, readonly, nextTick, type Ref } from 'vue'
import { signIn, signOut, signUp, confirmSignUp, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword, signInWithRedirect, type AuthUser, fetchAuthSession } from '@aws-amplify/auth'

// グローバルな認証状態
let globalAuthState: {
  isAuthenticated: Ref<boolean>
  user: Ref<AuthUser | null>
  loading: Ref<boolean>
} | null = null

// シングルトンパターンでグローバル状態を管理
const getGlobalAuthState = () => {
  if (!globalAuthState) {
    globalAuthState = {
      isAuthenticated: ref(false),
      user: ref<AuthUser | null>(null),
      loading: ref(false)
    }
  }
  return globalAuthState
}

export const useAuth = () => {
  const config = useRuntimeConfig()
  const { isAuthenticated, user, loading } = getGlobalAuthState()

  // 認証状態の初期化（より安全なアプローチ）
  const initialize = async () => {
    try {
      loading.value = true
      console.log('Initializing auth state...')
      
      // まずセッション状態を確認
      const session = await fetchAuthSession()
      console.log('Auth session:', { 
        tokens: !!session.tokens, 
        credentials: !!session.credentials 
      })
      
      if (session.tokens) {
        try {
          // セッションが有効な場合のみgetCurrentUserを呼び出し
          const currentUser = await getCurrentUser()
          console.log('Current user:', currentUser)
          
          user.value = currentUser
          isAuthenticated.value = true
          console.log('User authenticated successfully')
        } catch (userError) {
          console.log('Error getting user info:', userError)
          // セッションはあるがユーザー情報が取得できない場合
          isAuthenticated.value = false
          user.value = null
        }
      } else {
        console.log('No valid session found')
        isAuthenticated.value = false
        user.value = null
      }
    } catch (error) {
      console.log('No authenticated session:', error)
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
      const session = await fetchAuthSession()
      if (session.tokens?.accessToken) {
        return session.tokens.accessToken.toString()
      }
      throw new Error('No access token available')
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
        // サインイン成功後、少し待ってから状態を更新
        await new Promise(resolve => setTimeout(resolve, 500))
        await initialize() // initializeを使用して安全にチェック
        console.log('Sign in successful, auth state updated')
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
      console.log('Starting sign out process...')
      
      // OAuth認証でのサインアウトの場合、リダイレクトURIを指定
      await signOut({
        global: true // グローバルサインアウト（全てのデバイスからサインアウト）
      })
      
      // 状態をクリア
      isAuthenticated.value = false
      user.value = null
      console.log('User signed out successfully')
      
      // 少し待ってから状態を確実にクリア
      await nextTick()
      
      // ローカルストレージも手動でクリア
      if (process.client) {
        // Amplifyのトークンストレージをクリア
        try {
          localStorage.removeItem('aws-amplify-user')
          localStorage.removeItem('aws-amplify-federatedInfo')
          Object.keys(localStorage).forEach(key => {
            if (key.startsWith('CognitoIdentity') || key.startsWith('aws.cognito')) {
              localStorage.removeItem(key)
            }
          })
        } catch (e) {
          console.log('Error clearing localStorage:', e)
        }
      }
      
    } catch (error) {
      console.error('Sign out error:', error)
      
      // エラーが発生してもローカル状態はクリアする
      isAuthenticated.value = false
      user.value = null
      
      if (process.client) {
        try {
          localStorage.removeItem('aws-amplify-user')
          localStorage.removeItem('aws-amplify-federatedInfo')
        } catch (e) {
          console.log('Error clearing localStorage after error:', e)
        }
      }
      
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
    // リアクティブな状態を返す
    isAuthenticated,
    user,
    loading,
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