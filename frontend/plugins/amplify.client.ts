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
                'https://dev.whiskeybar.site/',
                'https://www.dev.whiskeybar.site/',
                'http://localhost:3000/',
                `${currentUrl}/auth/callback`
              ],
              redirectSignOut: [
                'https://dev.whiskeybar.site/',
                'https://www.dev.whiskeybar.site/',
                'http://localhost:3000/',
                `${currentUrl}/`
              ],
              responseType: 'code' as const
            },
            email: true,
          },
        },
      },
    })
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
    })

    // Promise rejection エラーも処理
    window.addEventListener('unhandledrejection', (event) => {
      if (event.reason && event.reason.toString().includes('content.js')) {
        event.preventDefault()
        return false
      }
    })
  }
}) 