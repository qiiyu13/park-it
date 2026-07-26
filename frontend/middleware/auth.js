/**
 * Auth + Role Middleware
 *
 * - Redirects unauthenticated users to /login.
 * - Routes logged-in users away from /login based on role.
 * - Blocks operators from admin-only pages (URL-hack defense).
 */

const ADMIN_ONLY_PREFIXES = [
  '/',          // admin dashboard (exact match handled below)
  '/setting',
  '/device',
  '/setup',
  '/member',
  '/report',
  '/personnel',   // user management — admin only
]

const OPERATOR_HOME = '/pos'
const ADMIN_HOME = '/'

function isAdminOnly(path) {
  if (path === '/') return true
  return ADMIN_ONLY_PREFIXES
    .filter((p) => p !== '/')
    .some((p) => path === p || path.startsWith(p + '/'))
}

export default defineNuxtRouteMiddleware(async (to) => {
  const authStore = useAuthStore()

  const publicRoutes = ['/login']

  if (!authStore.user && !authStore.isLoading && !publicRoutes.includes(to.path)) {
    try {
      await authStore.fetchUser()
    } catch {
      // Not authenticated
    }
  }

  if (!authStore.isLoggedIn && !publicRoutes.includes(to.path)) {
    return navigateTo('/login')
  }

  if (authStore.isLoggedIn && to.path === '/login') {
    return navigateTo(authStore.isAdmin ? ADMIN_HOME : OPERATOR_HOME)
  }

  if (authStore.isLoggedIn && !authStore.isAdmin && isAdminOnly(to.path)) {
    return navigateTo(OPERATOR_HOME)
  }
})
