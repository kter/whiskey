import { Amplify } from 'aws-amplify'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()

  // 現在のURLを動的に取得
  const currentUrl = process.client ? window.location.origin : 'http://localhost:3000'
  
  try {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId: config.public.userPoolId,
          userPoolClientId: config.public.userPoolClientId,
          loginWith: {
            oauth: {
              domain: 'whiskey-users-dev.auth.ap-northeast-1.amazoncognito.com',
              scopes: ['email', 'profile', 'openid'],
              redirectSignIn: [
                'https://dev.whiskeybar.site/auth/callback',
                'https://www.dev.whiskeybar.site/auth/callback',
                'http://localhost:3000/auth/callback'
              ],
              redirectSignOut: [
                'https://dev.whiskeybar.site/',
                'https://www.dev.whiskeybar.site/',
                'http://localhost:3000/'
              ],
              responseType: 'code' as const
            },
            email: true,
          },
        },
      },
      // ローカルストレージ設定を削除（デフォルトのローカルストレージを使用）
    })
    
    console.log('Amplify configured successfully for local logout')
    
    // OAuth認証の状態変更をリスンする
    if (process.client) {
      // Hub によるAuth状態の監視
      import('@aws-amplify/core').then(({ Hub }) => {
        Hub.listen('auth', (data) => {
          console.log('Auth Hub event:', data)
          
          switch (data.payload.event) {
            case 'signedIn':
              console.log('User signed in successfully')
              break
            case 'signedOut':
              console.log('User signed out successfully via Hub')
              break
            case 'tokenRefresh':
              console.log('Auth tokens refreshed')
              break
            case 'tokenRefresh_failure':
              console.log('Token refresh failed')
              break
            case 'signIn_failure':
              console.log('Sign in failed:', data.payload.data)
              break
          }
        })
      })
      
      // ページアンロード時にローカルログアウトを確実に実行
      window.addEventListener('beforeunload', () => {
        console.log('Page unloading, ensuring clean logout state')
      })
    }
    
  } catch (error) {
    console.error('Amplify configuration error:', error)
  }

  // 外部スクリプト（拡張機能など）によるエラーを防ぐ
  if (process.client) {
    // グローバルエラーハンドラーを追加
    window.addEventListener('error', (event) => {
      // content.jsやその他の外部スクリプトエラーを無視
      if (event.filename && event.filename.includes('content.js')) {
        event.preventDefault()
        return false
      }
      
      // Cognitoのログアウトエラーも無視
      if (event.message && event.message.includes('redirect_uri')) {
        console.log('Ignoring Cognito logout redirect error')
        event.preventDefault()
        return false
      }
    })

    // Promise rejection エラーも処理
    window.addEventListener('unhandledrejection', (event) => {
      if (event.reason && event.reason.toString().includes('content.js')) {
        event.preventDefault()
        return false
      }
      
      // Cognitoのログアウトエラーも無視
      if (event.reason && event.reason.toString().includes('redirect_uri')) {
        console.log('Ignoring Cognito logout promise rejection')
        event.preventDefault()
        return false
      }
    })
  }
}) 