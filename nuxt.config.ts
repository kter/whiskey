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
      apiBaseUrl: process.env.API_BASE_URL || 'http://localhost:8000',
      aws: {
        region: process.env.AWS_REGION || 'ap-northeast-1',
        userPoolId: process.env.AWS_USER_POOL_ID || '',
        userPoolWebClientId: process.env.AWS_USER_POOL_CLIENT_ID || '',
      }
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