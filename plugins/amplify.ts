import { Amplify } from 'aws-amplify'
import { defineNuxtPlugin, useRuntimeConfig } from '#app'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()

  Amplify.configure({
    Auth: {
      region: config.public.aws.region,
      userPoolId: config.public.aws.userPoolId,
      userPoolWebClientId: config.public.aws.userPoolWebClientId,
    }
  })
}) 