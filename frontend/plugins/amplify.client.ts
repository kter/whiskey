import { Amplify } from 'aws-amplify'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.public.userPoolId,
        userPoolClientId: config.public.userPoolClientId,
        loginWith: {
          email: true,
        },
      },
    },
  })
}) 