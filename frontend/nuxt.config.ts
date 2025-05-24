// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss'],
  typescript: {
    strict: true
  },
  nitro: {
    compatibilityDate: '2025-05-22'
  },
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
      
      // 後方互換性のため残す
      apiBase: process.env.NUXT_PUBLIC_API_BASE || process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
      awsRegion: process.env.NUXT_PUBLIC_AWS_REGION || process.env.NUXT_PUBLIC_REGION || 'ap-northeast-1',
      cognitoUserPoolId: process.env.NUXT_PUBLIC_COGNITO_USER_POOL_ID || process.env.NUXT_PUBLIC_USER_POOL_ID || 'ap-northeast-1_xxxxxxxx',
      cognitoClientId: process.env.NUXT_PUBLIC_COGNITO_CLIENT_ID || process.env.NUXT_PUBLIC_USER_POOL_CLIENT_ID || 'xxxxxxxxxxxxxxxxxxxxxxxxxx',
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