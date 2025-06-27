import { ref, readonly, nextTick, type Ref } from 'vue'
import { signIn, signOut, signUp, confirmSignUp, getCurrentUser, fetchUserAttributes, resetPassword, confirmResetPassword, signInWithRedirect, type AuthUser, fetchAuthSession } from '@aws-amplify/auth'

// ユーザープロフィール型定義
export interface UserProfile {
  user_id: string
  nickname: string
  display_name?: string
  created_at: string
  updated_at: string
}

// グローバルな認証状態
let globalAuthState: {
  isAuthenticated: Ref<boolean>
  user: Ref<AuthUser | null>
  profile: Ref<UserProfile | null>
  loading: Ref<boolean>
  profileLoading: Ref<boolean>
} | null = null

// シングルトンパターンでグローバル状態を管理
const getGlobalAuthState = () => {
  if (!globalAuthState) {
    globalAuthState = {
      isAuthenticated: ref(false),
      user: ref<AuthUser | null>(null),
      profile: ref<UserProfile | null>(null),
      loading: ref(false),
      profileLoading: ref(false)
    }
  }
  return globalAuthState
}

export const useAuth = () => {
  const config = useRuntimeConfig()
  const { isAuthenticated, user, profile, loading, profileLoading } = getGlobalAuthState()

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
          
          // ユーザープロフィールも取得
          await fetchUserProfile()
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
      console.log('Starting local sign out process...')
      
      // ローカルのみでサインアウト（Cognitoのホストされたログアウトを回避）
      try {
        // まずローカルセッションをクリア
        if (process.client) {
          console.log('Clearing local storage...')
          // Amplifyのトークンストレージをクリア
          localStorage.removeItem('aws-amplify-user')
          localStorage.removeItem('aws-amplify-federatedInfo')
          Object.keys(localStorage).forEach(key => {
            if (key.startsWith('CognitoIdentity') || 
                key.startsWith('aws.cognito') || 
                key.startsWith('amplify-') ||
                key.includes('cognito')) {
              console.log('Removing localStorage key:', key)
              localStorage.removeItem(key)
            }
          })
          
          // SessionStorageもクリア
          Object.keys(sessionStorage).forEach(key => {
            if (key.startsWith('CognitoIdentity') || 
                key.startsWith('aws.cognito') || 
                key.startsWith('amplify-') ||
                key.includes('cognito')) {
              console.log('Removing sessionStorage key:', key)
              sessionStorage.removeItem(key)
            }
          })
        }
        
        // Amplifyのサインアウト（ローカルのみ）
        await signOut({ global: false }) // グローバルサインアウトを無効化
        
      } catch (signOutError) {
        console.log('Amplify signOut error (expected for OAuth):', signOutError)
        // OAuth認証の場合、signOut()でエラーが発生することがあるが、
        // ローカルストレージのクリアで実質的にログアウトは完了
      }
      
      // 状態をクリア
      isAuthenticated.value = false
      user.value = null
      profile.value = null
      console.log('Local sign out completed successfully')
      
      // 少し待ってから状態を確実にクリア
      await nextTick()
      
    } catch (error) {
      console.error('Sign out error:', error)
      
      // エラーが発生してもローカル状態はクリアする
      isAuthenticated.value = false
      user.value = null
      profile.value = null
      
      // ローカルストレージも強制的にクリア
      if (process.client) {
        try {
          localStorage.clear()
          sessionStorage.clear()
          console.log('Force cleared all storage due to error')
        } catch (e) {
          console.log('Error force clearing storage:', e)
        }
      }
      
      // エラーをログに残すが、ユーザーには成功として扱う
      console.log('Treated sign out as successful despite errors')
      
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

  // ユーザープロフィール管理機能
  const fetchUserProfile = async () => {
    try {
      profileLoading.value = true
      const token = await getToken()
      
      const response = await fetch(`${config.public.apiBaseUrl}/api/users/profile/get-or-create/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (!response.ok) {
        console.error('Failed to fetch user profile:', response.status)
        return
      }

      const profileData = await response.json()
      profile.value = profileData
      console.log('User profile loaded:', profileData)
    } catch (error) {
      console.error('Error fetching user profile:', error)
    } finally {
      profileLoading.value = false
    }
  }

  const updateUserProfile = async (nickname: string, displayName?: string) => {
    try {
      profileLoading.value = true
      const token = await getToken()
      
      const payload: any = { nickname }
      if (displayName !== undefined) {
        payload.display_name = displayName
      }

      const response = await fetch(`${config.public.apiBaseUrl}/api/users/profile/`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'プロフィールの更新に失敗しました')
      }

      const updatedProfile = await response.json()
      profile.value = updatedProfile
      console.log('Profile updated:', updatedProfile)
      return updatedProfile
    } catch (error) {
      console.error('Error updating user profile:', error)
      throw error
    } finally {
      profileLoading.value = false
    }
  }

  const getDisplayName = () => {
    if (profile.value?.nickname) {
      return profile.value.nickname
    }
    // プロフィールが読み込まれていない場合のフォールバック
    return '神秘的なウイスキー愛好家'
  }

  return {
    // リアクティブな状態を返す
    isAuthenticated,
    user,
    profile,
    loading,
    profileLoading,
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
    googleSignIn: handleGoogleSignIn,
    // プロフィール管理
    fetchUserProfile,
    updateUserProfile,
    getDisplayName
  }
} 