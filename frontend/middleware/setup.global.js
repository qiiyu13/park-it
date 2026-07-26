/**
 * Setup-complete middleware (global).
 *
 * Until the setup wizard has run, every route except /setup* redirects to /setup.
 * Once `setup_complete=true`, the wizard is locked: visiting /setup self-redirects
 * to / (see setup.vue onMounted). Steady-state config lives in Device + Settings;
 * re-provisioning is an installer action (re-run setup.sh, which resets the flag).
 */

let cachedComplete = null
let inflight = null

export default defineNuxtRouteMiddleware(async (to) => {
  if (import.meta.server) return
  if (to.path.startsWith('/setup')) return

  if (cachedComplete === null) {
    inflight = inflight || (async () => {
      try {
        const { fetchApi } = useApi()
        const s = await fetchApi('/api/setup/state')
        cachedComplete = !!s.setup_complete
      } catch {
        // If the API is unreachable, don't trap the user — let the next
        // route resolve and fail visibly there.
        cachedComplete = true
      } finally {
        inflight = null
      }
    })()
    await inflight
  }

  if (!cachedComplete) {
    return navigateTo('/setup')
  }
})
