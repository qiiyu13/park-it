/**
 * useCrud composable
 *
 * Reusable CRUD operations for any REST resource. Built on top of useApi.
 *
 * Provides automatic Indonesian-language toasts for create/update/delete so
 * admin pages don't have to wire `vue-sonner` themselves. Reads (list/get)
 * are silent by default; pass `{ silent: false }` to surface their errors.
 *
 * @param {string} resourcePath — e.g. '/api/users'
 * @param {object} [opts]
 * @param {string} [opts.label='Data'] — used in toast text, e.g. "Member berhasil dibuat"
 */

import { toast } from 'vue-sonner'

export const useCrud = (resourcePath, opts = {}) => {
  const { fetchApi } = useApi()

  if (!resourcePath) {
    throw new Error('useCrud requires a resourcePath')
  }

  const base = resourcePath.startsWith('/') ? resourcePath : `/${resourcePath}`
  const label = opts.label || 'Data'

  function _errorMessage(err) {
    const detail = err?.data?.detail
    if (Array.isArray(detail)) {
      // Pydantic validation errors — without this the toast shows "[object Object]".
      return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
    }
    return detail || err?.message || 'Terjadi kesalahan tidak terduga'
  }

  async function list(params = {}, { silent = true } = {}) {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        query.append(key, String(value))
      }
    }
    const qs = query.toString()
    try {
      return await fetchApi(`${base}${qs ? '?' + qs : ''}`)
    } catch (err) {
      if (!silent) toast.error(`Gagal memuat ${label.toLowerCase()}: ${_errorMessage(err)}`)
      throw err
    }
  }

  async function get(id, { silent = true } = {}) {
    try {
      return await fetchApi(`${base}/${id}`)
    } catch (err) {
      if (!silent) toast.error(`Gagal memuat ${label.toLowerCase()}: ${_errorMessage(err)}`)
      throw err
    }
  }

  async function create(payload, { silent = false } = {}) {
    try {
      const result = await fetchApi(base, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      if (!silent) toast.success(`${label} berhasil dibuat`)
      return result
    } catch (err) {
      if (!silent) toast.error(`Gagal menyimpan ${label.toLowerCase()}: ${_errorMessage(err)}`)
      throw err
    }
  }

  async function update(id, payload, { silent = false } = {}) {
    try {
      const result = await fetchApi(`${base}/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      })
      if (!silent) toast.success(`${label} berhasil diperbarui`)
      return result
    } catch (err) {
      if (!silent) toast.error(`Gagal memperbarui ${label.toLowerCase()}: ${_errorMessage(err)}`)
      throw err
    }
  }

  async function remove(id, { silent = false } = {}) {
    try {
      const result = await fetchApi(`${base}/${id}`, { method: 'DELETE' })
      if (!silent) toast.success(`${label} berhasil dihapus`)
      return result
    } catch (err) {
      if (!silent) toast.error(`Gagal menghapus ${label.toLowerCase()}: ${_errorMessage(err)}`)
      throw err
    }
  }

  return {
    list,
    get,
    create,
    update,
    remove,
  }
}
