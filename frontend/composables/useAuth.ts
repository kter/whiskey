import { ref } from 'vue'
import { signOut, getCurrentUser, fetchUserAttributes } from '@aws-amplify/auth'

export const useAuth = () => {
  const isAuthenticated = ref(false)
  const user = ref<any>(null)
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

  // Google認証（Cognito Hosted UIにリダイレクト）
  const handleGoogleSignIn = async () => {
    try {
      loading.value = true
      
      // Cognito Hosted UIのGoogle認証URLを構築
      const userPoolId = config.public.cognitoUserPoolId
      const clientId = config.public.cognitoClientId
      const region = config.public.cognitoRegion || 'ap-northeast-1'
      const domain = `whiskey-users-${config.public.environment || 'dev'}`
      const redirectUri = encodeURIComponent(window.location.origin + '/auth/callback')
      
      const cognitoAuthUrl = `https://${domain}.auth.${region}.amazoncognito.com/oauth2/authorize?` +
        `identity_provider=Google&` +
        `redirect_uri=${redirectUri}&` +
        `response_type=code&` +
        `client_id=${clientId}&` +
        `scope=email+profile+openid`

      // Cognito Hosted UIにリダイレクト
      window.location.href = cognitoAuthUrl
      
    } catch (error) {
      console.error('Google sign in error:', error)
      loading.value = false
      throw error
    }
  }

  return {
    isAuthenticated,
    user,
    loading,
    initialize,
    getToken,
    getTokenSafely,
    signOut: handleSignOut,
    googleSignIn: handleGoogleSignIn,
  }
} 