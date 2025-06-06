import { Amplify } from 'aws-amplify'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.public.userPoolId,
        userPoolClientId: config.public.userPoolClientId,
        loginWith: {
          oauth: {
            domain: 'whiskey-users-dev.auth.ap-northeast-1.amazoncognito.com',
            scopes: ['email', 'profile', 'openid'],
            redirectSignIn: ['https://dev.whiskeybar.site/', 'https://www.dev.whiskeybar.site/', 'http://localhost:3000/'],
            redirectSignOut: ['https://dev.whiskeybar.site/', 'https://www.dev.whiskeybar.site/', 'http://localhost:3000/'],
            responseType: 'code' as const
          },
          email: true,
        },
      },
    },
  })
}) 