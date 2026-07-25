if (process.env.NUXT_PUBLIC_MOCK_AUTH === '1' && process.env.NODE_ENV !== 'development') {
  throw new Error('NUXT_PUBLIC_MOCK_AUTH=1 is only allowed for the development server')
}

export default defineNuxtConfig({
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss'],
  typescript: {
    strict: true
  },
  // S3静的サイトホスティング用のSSG設定
  nitro: {
    compatibilityDate: '2025-05-22',
    prerender: {
      // Dynamic SPA routes are also emitted so static hosting has an explicit route artifact.
      routes: ['/', '/logs', '/logs/[id]'],
      crawlLinks: true // リンクを自動で辿って生成
    }
  },
  // 静的サイト生成モード
  ssr: false, // SPAモード
  runtimeConfig: {
    public: {
      // API設定（CDKのGitHub Actionsと統一）
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',

      // AWS & Cognito設定（CDKのOutputsと統一）
      userPoolId: process.env.NUXT_PUBLIC_USER_POOL_ID || 'ap-northeast-1_xxxxxxxx',
      userPoolClientId: process.env.NUXT_PUBLIC_USER_POOL_CLIENT_ID || 'xxxxxxxxxxxxxxxxxxxxxxxxxx',
      region: process.env.NUXT_PUBLIC_REGION || 'ap-northeast-1',
      imagesBucket: process.env.NUXT_PUBLIC_IMAGES_BUCKET || 'whiskey-images-dev',
      environment: process.env.NUXT_PUBLIC_ENVIRONMENT || 'local',
      cognitoDomain: process.env.NUXT_PUBLIC_COGNITO_DOMAIN || '',
      // Nuxt may coerce environment overrides to numbers or booleans at runtime.
      googleAuthEnabled: process.env.NUXT_PUBLIC_GOOGLE_AUTH_ENABLED || '0',
      mockAuth: process.env.NUXT_PUBLIC_MOCK_AUTH || '0',

      // 後方互換性のため残す
      apiBase: process.env.NUXT_PUBLIC_API_BASE || process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
      awsRegion: process.env.NUXT_PUBLIC_AWS_REGION || process.env.NUXT_PUBLIC_REGION || 'ap-northeast-1',
      cognitoUserPoolId: process.env.NUXT_PUBLIC_COGNITO_USER_POOL_ID || process.env.NUXT_PUBLIC_USER_POOL_ID || 'ap-northeast-1_xxxxxxxx',
      cognitoClientId: process.env.NUXT_PUBLIC_COGNITO_CLIENT_ID || process.env.NUXT_PUBLIC_USER_POOL_CLIENT_ID || 'xxxxxxxxxxxxxxxxxxxxxxxxxx'
    }
  },
  app: {
    head: {
      title: 'Whiskey Log',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { key: 'description', name: 'description', content: 'ウイスキー記録アプリ' }
      ]
    }
  }
})
