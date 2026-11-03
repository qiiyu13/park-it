import { beforeEach, describe, expect, it, vi } from 'vitest'

import authMiddleware from '../../middleware/auth.js'

function store(overrides = {}) {
  return {
    user: null,
    isLoading: false,
    isLoggedIn: false,
    isAdmin: false,
    fetchUser: vi.fn().mockRejectedValue(new Error('not authenticated')),
    ...overrides,
  }
}

describe('auth route middleware', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.navigateTo = vi.fn()
  })

  it('lets /setup through without a JWT (token-gated by the page)', async () => {
    globalThis.useAuthStore = vi.fn(() => store())

    const result = await authMiddleware({ path: '/setup' })

    expect(result).toBeUndefined()
    expect(globalThis.useAuthStore).not.toHaveBeenCalled()
    expect(globalThis.navigateTo).not.toHaveBeenCalled()
  })

  it('redirects unauthenticated users to /login', async () => {
    globalThis.useAuthStore = vi.fn(() => store())

    await authMiddleware({ path: '/' })

    expect(globalThis.navigateTo).toHaveBeenCalledWith('/login')
  })

  it('allows an authenticated admin through', async () => {
    globalThis.useAuthStore = vi.fn(() =>
      store({ user: { id: 1, role: 'admin' }, isLoggedIn: true, isAdmin: true })
    )

    await authMiddleware({ path: '/' })

    expect(globalThis.navigateTo).not.toHaveBeenCalled()
  })

  it('sends operators away from admin-only pages', async () => {
    globalThis.useAuthStore = vi.fn(() =>
      store({ user: { id: 2, role: 'operator' }, isLoggedIn: true })
    )

    await authMiddleware({ path: '/device' })

    expect(globalThis.navigateTo).toHaveBeenCalledWith('/pos')
  })

  it('sends logged-in users away from /login', async () => {
    globalThis.useAuthStore = vi.fn(() =>
      store({ user: { id: 2, role: 'operator' }, isLoggedIn: true })
    )

    await authMiddleware({ path: '/login' })

    expect(globalThis.navigateTo).toHaveBeenCalledWith('/pos')
  })
})
