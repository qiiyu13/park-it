import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { usePosSessionStore } from '~/stores/pos-session'

describe('pos-session store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('counts a cash payment in both shift totals', () => {
    const store = usePosSessionStore()
    store.addCashPayment(6000)
    store.addTransaction()
    expect(store.cashCollected).toBe(6000)
    expect(store.transactionCount).toBe(2)
  })
})
