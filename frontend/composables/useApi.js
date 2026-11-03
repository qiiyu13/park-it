/**
 * useApi composable
 *
 * Low-level fetch wrapper for the FastAPI backend.
 * Handles httpOnly cookie auth, JSON parsing, and common error patterns.
 */

export const useApi = () => {
  const config = useRuntimeConfig()
  const baseURL = config.public.apiBaseUrl

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

    const response = await fetch(url, merged)

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
