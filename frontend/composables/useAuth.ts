import { computed, readonly, ref, type Ref } from 'vue'
import {
  confirmResetPassword,
  confirmSignUp,
  fetchAuthSession,
  fetchUserAttributes,
  getCurrentUser,
  resendSignUpCode,
  resetPassword,
  signIn,
  signInWithRedirect,
  signOut,
  signUp,
  type AuthUser,
} from '@aws-amplify/auth'
import { isGoogleAuthEnabled } from '~/utils/googleAuth'

const USERNAME_SALT = 'whiskey-log-signup-username-v1'
const PENDING_SIGNUP_KEY = 'whiskey.pending-signup-username'
const GENERIC_AUTH_ERROR = '認証情報を確認できませんでした。入力内容を確認して、もう一度お試しください。'

export interface UserProfile {
  user_id: string
  nickname: string
  display_name?: string
  email?: string
  created_at?: string
  updated_at?: string
}

interface AuthState {
  isAuthenticated: Ref<boolean>
  user: Ref<AuthUser | null>
  profile: Ref<UserProfile | null>
  loading: Ref<boolean>
  profileLoading: Ref<boolean>
  authReady: Ref<boolean>
}

let state: AuthState | null = null
let initializationPromise: Promise<void> | null = null

const getState = (): AuthState => {
  if (!state) {
    state = {
      isAuthenticated: ref(false),
      user: ref<AuthUser | null>(null),
      profile: ref<UserProfile | null>(null),
      loading: ref(false),
      profileLoading: ref(false),
      authReady: ref(false),
    }
  }
  return state
}

export const normalizeEmail = (email: string) => email.trim().toLowerCase()

export const deriveUsername = async (email: string): Promise<string> => {
  const bytes = new TextEncoder().encode(`${USERNAME_SALT}:${normalizeEmail(email)}`)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  return `w${hex}`
}

const rememberPendingUsername = (email: string, username: string) => {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.setItem(PENDING_SIGNUP_KEY, JSON.stringify({ email: normalizeEmail(email), username }))
  }
}

const pendingUsernameFor = async (email: string) => {
  const normalizedEmail = normalizeEmail(email)
  if (typeof sessionStorage !== 'undefined') {
    const stored = sessionStorage.getItem(PENDING_SIGNUP_KEY)
    if (stored) {
      try {
        const pending: unknown = JSON.parse(stored)
        if (
          typeof pending === 'object'
          && pending !== null
          && 'email' in pending
          && pending.email === normalizedEmail
          && 'username' in pending
          && typeof pending.username === 'string'
        ) {
          return pending.username
        }
      } catch {
        // Legacy plain-string and malformed values are ignored.
      }
    }
  }
  return deriveUsername(normalizedEmail)
}

const forgetPendingUsername = () => {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.removeItem(PENDING_SIGNUP_KEY)
  }
}

const isCognitoStorageKey = (key: string) => {
  const normalized = key.toLowerCase()
  return normalized.startsWith('cognitoidentity')
    || normalized.startsWith('aws.cognito')
    || normalized.startsWith('amplify-')
    || normalized.includes('cognitoidentityserviceprovider')
}

const clearCognitoStorage = () => {
  if (typeof window === 'undefined') return
  for (const storage of [window.localStorage, window.sessionStorage]) {
    Object.keys(storage).filter(isCognitoStorageKey).forEach(key => storage.removeItem(key))
  }
}

const createAuth = (isDevelopment: boolean) => {
  const config = useRuntimeConfig()
  const authState = getState()
  const { isAuthenticated, user, profile, loading, profileLoading, authReady } = authState
  const mockAuth = isDevelopment && config.public.mockAuth === '1'

  const currentUserId = computed(() => user.value?.userId || profile.value?.user_id || null)

  const fetchUserProfile = async () => {
    if (!user.value) {
      profile.value = null
      return
    }
    profileLoading.value = true
    try {
      let attributes: Awaited<ReturnType<typeof fetchUserAttributes>> = {}
      try {
        attributes = mockAuth ? { email: 'local@example.com', sub: 'local-user' } : await fetchUserAttributes()
      } catch {
        // Authentication remains valid when optional profile attributes cannot be loaded.
      }
      profile.value = {
        user_id: user.value.userId || attributes.sub || '',
        email: attributes.email,
        nickname: attributes.nickname || attributes.given_name || 'ウイスキー愛好家',
        display_name: attributes.name || attributes.given_name,
      }
    } finally {
      profileLoading.value = false
    }
  }

  const initialize = async (): Promise<void> => {
    if (authReady.value) return
    if (initializationPromise) return initializationPromise

    initializationPromise = (async () => {
      loading.value = true
      try {
        if (mockAuth) {
          user.value = { userId: 'local-user', username: 'local-user' }
          isAuthenticated.value = true
          await fetchUserProfile()
          return
        }

        const session = await fetchAuthSession()
        if (!session.tokens?.idToken) throw new Error('No authenticated session')
        user.value = await getCurrentUser()
        isAuthenticated.value = true
        await fetchUserProfile()
      } catch {
        isAuthenticated.value = false
        user.value = null
        profile.value = null
      } finally {
        loading.value = false
        authReady.value = true
      }
    })()

    try {
      await initializationPromise
    } finally {
      initializationPromise = null
    }
  }

  const refreshAuthState = async () => {
    authReady.value = false
    await initialize()
  }

  const waitForAuthReady = async () => {
    await initialize()
  }

  const getToken = async (): Promise<string> => {
    if (mockAuth) return 'mock-id-token'
    const session = await fetchAuthSession()
    const token = session.tokens?.idToken
    if (!token) throw new Error('ID token is not available')
    return token.toString()
  }

  const getTokenSafely = async (): Promise<string | null> => {
    try {
      return await getToken()
    } catch {
      return null
    }
  }

  const handleSignIn = async (email: string, password: string) => {
    loading.value = true
    try {
      const result = await signIn({ username: normalizeEmail(email), password })
      if (result.isSignedIn) await refreshAuthState()
      return result
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    } finally {
      loading.value = false
    }
  }

  const handleSignOut = async () => {
    loading.value = true
    try {
      if (!mockAuth) await signOut()
    } catch (error) {
      clearCognitoStorage()
      throw error
    } finally {
      isAuthenticated.value = false
      user.value = null
      profile.value = null
      authReady.value = true
      loading.value = false
    }
  }

  const handleSignUp = async (email: string, password: string) => {
    loading.value = true
    try {
      const normalizedEmail = normalizeEmail(email)
      const username = await deriveUsername(normalizedEmail)
      const result = await signUp({
        username,
        password,
        options: { userAttributes: { email: normalizedEmail } },
      })
      if (!result.isSignUpComplete) rememberPendingUsername(normalizedEmail, username)
      return result
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    } finally {
      loading.value = false
    }
  }

  const handleConfirmSignUp = async (email: string, confirmationCode: string) => {
    loading.value = true
    try {
      const username = await pendingUsernameFor(email)
      const result = await confirmSignUp({ username, confirmationCode: confirmationCode.trim() })
      if (result.isSignUpComplete) forgetPendingUsername()
      return result
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    } finally {
      loading.value = false
    }
  }

  const handleResendSignUpCode = async (email: string) => {
    try {
      const username = await pendingUsernameFor(email)
      await resendSignUpCode({ username })
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    }
  }

  const handleResetPassword = async (email: string) => {
    try {
      return await resetPassword({ username: normalizeEmail(email) })
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    }
  }

  const handleConfirmResetPassword = async (email: string, confirmationCode: string, newPassword: string) => {
    try {
      await confirmResetPassword({
        username: normalizeEmail(email),
        confirmationCode: confirmationCode.trim(),
        newPassword,
      })
    } catch {
      throw new Error(GENERIC_AUTH_ERROR)
    }
  }

  const handleGoogleSignIn = async () => {
    if (!isGoogleAuthEnabled(config.public.googleAuthEnabled)) throw new Error('Google認証は利用できません。')
    await signInWithRedirect({ provider: 'Google' })
  }

  const updateUserProfile = async (nickname: string, displayName?: string) => {
    if (!profile.value) return null
    profile.value.nickname = nickname
    profile.value.display_name = displayName
    return profile.value
  }

  const getDisplayName = () => profile.value?.nickname || 'ウイスキー愛好家'

  return {
    isAuthenticated: readonly(isAuthenticated),
    user: readonly(user),
    profile,
    loading: readonly(loading),
    profileLoading: readonly(profileLoading),
    authReady: readonly(authReady),
    currentUserId,
    initialize,
    refreshAuthState,
    waitForAuthReady,
    getToken,
    getTokenSafely,
    signIn: handleSignIn,
    signOut: handleSignOut,
    signUp: handleSignUp,
    confirmSignUp: handleConfirmSignUp,
    resendSignUpCode: handleResendSignUpCode,
    resetPassword: handleResetPassword,
    confirmResetPassword: handleConfirmResetPassword,
    googleSignIn: handleGoogleSignIn,
    fetchUserProfile,
    updateUserProfile,
    getDisplayName,
  }
}

export const useAuth = () => createAuth(import.meta.dev)

export const __useAuthForTests = (isDevelopment: boolean) => createAuth(isDevelopment)

export const __resetAuthStateForTests = () => {
  state = null
  initializationPromise = null
}
