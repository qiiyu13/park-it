/**
 * useApi composable
 *
 * Low-level fetch wrapper for the FastAPI backend.
 * Handles httpOnly cookie auth, JSON parsing, and common error patterns.
 */

export const useApi = () => {
  const config = useRuntimeConfig()
  // In the browser an empty base means "same origin" (nginx proxies /api).
  // During SSR a relative URL has no origin to resolve against — Node's fetch
  // throws, the auth middleware treats it as unauthenticated and every hard
  // reload of /device bounced back to /login. SSR talks to the API directly.
  const configured = config.public.apiBaseUrl
  const baseURL = configured || (import.meta.server ? 'http://127.0.0.1:8000' : '')

  // During SSR the browser's cookies are not attached to a plain Node fetch.
  // Forward them so route middleware (auth/me) and page data work on a hard
  // reload/direct URL, not only after a client-side navigation.
  const ssrHeaders = import.meta.server ? useRequestHeaders(['cookie']) : {}

  /**
   * Perform an authenticated fetch request.
   *
   * @param {string} path        — API path (e.g. '/api/auth/me')
   * @param {object} options     — fetch options
   * @returns {Promise<any>}     — parsed JSON response
   */
  async function fetchApi(path, options = {}) {
    const url = `${baseURL}${path}`

    const defaults = {
      headers: {
        ...ssrHeaders,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...options.headers,
      },
      credentials: 'include', // httpOnly cookies
    }

    // Merge defaults with caller options
    const merged = {
      ...defaults,
      ...options,
      headers: { ...defaults.headers, ...options.headers },
    }

    // Remove Content-Type for FormData / Blob bodies
    if (options.body instanceof FormData || options.body instanceof Blob) {
      delete merged.headers['Content-Type']
    }

    let response = await fetch(url, merged)

    // Access token lifetime is short (30 min by default). Without this, every
    // admin form suddenly failed with "Invalid authentication credentials"
    // mid-shift. Refresh once and replay the request.
    if (
      response.status === 401 &&
      !options._retried &&
      !path.startsWith('/api/auth/')
    ) {
      try {
        const refreshed = await fetch(`${baseURL}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        })
        if (refreshed.ok) {
          merged._retried = true
          response = await fetch(url, merged)
        }
      } catch {
        // fall through to the normal error path
      }
    }

    // Binary downloads (CSV/Excel/PDF exports) bypass JSON parsing.
    if (options.responseType === 'blob') {
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`)
        error.status = response.status
        throw error
      }
      return await response.blob()
    }

    // Attempt to parse JSON regardless of status for structured errors
    let data = null
    const contentType = response.headers.get('content-type')
    if (contentType && contentType.includes('application/json')) {
      data = await response.json()
    }

    if (!response.ok) {
      const error = new Error(data?.detail || data?.message || `HTTP ${response.status}`)
      error.status = response.status
      error.data = data
      throw error
    }

    return data
  }

  return {
    fetchApi,
    baseURL,
  }
}
