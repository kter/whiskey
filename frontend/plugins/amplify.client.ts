import { Amplify } from 'aws-amplify'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const origin = window.location.origin
  const domain = config.public.cognitoDomain.replace(/^https?:\/\//, '').replace(/\/+$/, '')
  const loginWith = config.public.googleAuthEnabled === '1' && domain
    ? {
        email: true,
        oauth: {
          domain,
          scopes: ['email', 'profile', 'openid'],
          redirectSignIn: [`${origin}/auth/callback`],
          redirectSignOut: [`${origin}/`],
          responseType: 'code' as const,
        },
      }
    : { email: true }

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.public.userPoolId,
        userPoolClientId: config.public.userPoolClientId,
        loginWith,
      },
    },
  })
})
