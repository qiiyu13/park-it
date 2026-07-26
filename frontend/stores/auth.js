/**
 * Auth Store (Pinia)
 *
 * Manages authentication state, user profile, and token lifecycle.
 * Tokens are stored in httpOnly cookies by the backend —
 * this store only tracks the in-memory user object and auth status.
 */

import { defineStore } from 'pinia'

// DEV ONLY: lets you browse the admin UI at localhost:3000 without logging in.
// Stripped from production builds (import.meta.dev is false there). API calls
// still need a real session cookie, so data tables may 401 / stay empty — this
// only unlocks the UI shell + admin nav for visual review.
const DEV_ADMIN = { id: 0, username: 'dev-admin', full_name: 'Dev Admin (no login)', role: 'admin' }
const devFallbackUser = () => (import.meta.dev ? { ...DEV_ADMIN } : null)

export const useAuthStore = defineStore('auth', () => {
  const { fetchApi } = useApi()

  // State
  const user = ref(devFallbackUser())
  const isLoading = ref(false)
  const error = ref(null)

  // Getters
  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isOperator = computed(() => ['admin', 'operator', 'supervisor'].includes(user.value?.role))

  // Actions

  /**
   * Log in with username and password.
   */
  async function login(username, password) {
    isLoading.value = true
    error.value = null
    try {
      const data = await fetchApi('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      if (data.data?.user) {
        user.value = data.data.user
      }
      return data
    } catch (err) {
      error.value = err.message || 'Login failed'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Fetch current user profile.
   */
  async function fetchUser() {
    isLoading.value = true
    error.value = null
    try {
      const data = await fetchApi('/api/auth/me')
      user.value = data
      return data
    } catch (err) {
      if (err.status === 401) {
        user.value = devFallbackUser()
      } else {
        error.value = err.message || 'Failed to fetch user'
      }
      throw err
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Log out and clear cookies.
   */
  async function logout() {
    isLoading.value = true
    try {
      await fetchApi('/api/auth/logout', { method: 'POST' })
    } catch {
      // Ignore logout errors
    } finally {
      user.value = null
      isLoading.value = false
      error.value = null
    }
  }

  /**
   * Refresh access token using refresh cookie.
   */
  async function refreshToken() {
    try {
      await fetchApi('/api/auth/refresh', { method: 'POST' })
      return true
    } catch {
      user.value = devFallbackUser()
      return false
    }
  }

  /**
   * Initialize auth state on app startup.
   */
  async function initAuth() {
    try {
      await fetchUser()
    } catch (err) {
      // Access token may be expired — try refreshing
      if (err?.status === 401) {
        const refreshed = await refreshToken()
        if (refreshed) {
          try {
            await fetchUser()
            return
          } catch {
            // Refresh succeeded but user fetch failed — give up
          }
        }
      }
      user.value = devFallbackUser()
    }
  }

  return {
    user,
    isLoading,
    error,
    isLoggedIn,
    isAdmin,
    isOperator,
    login,
    fetchUser,
    logout,
    refreshToken,
    initAuth,
  }
})
