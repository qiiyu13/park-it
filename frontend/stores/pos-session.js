/**
 * POS Session Store (Pinia)
 *
 * API-backed shift data. Survives page refreshes.
 * Replaces the session-scoped cashCollected/transactionCount refs.
 */

import { defineStore } from 'pinia'

export const usePosSessionStore = defineStore('pos-session', () => {
  const cashCollected = ref(0)
  const transactionCount = ref(0)
  const shiftName = ref('')
  const shiftTimeRange = ref('')
  const isLoading = ref(false)
  const availableShifts = ref([])

  async function loadShiftSummary() {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/pos/shift-summary')
      if (res) {
        cashCollected.value = res.cash_collected || 0
        transactionCount.value = res.transaction_count || 0
        shiftName.value = res.shift_name || ''
        shiftTimeRange.value = res.shift_time_range || ''
      }
    } catch (err) {
      // Non-critical — shift data just stays at 0
      console.warn('Failed to load shift summary:', err.message)
    } finally {
      isLoading.value = false
    }
  }

  async function fetchShifts() {
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/shifts/active')
      if (Array.isArray(res)) {
        availableShifts.value = res
      }
    } catch (err) {
      console.warn('Failed to fetch shifts:', err.message)
    }
  }

  function addTransaction() {
    transactionCount.value += 1
  }

  function addCashPayment(amount) {
    cashCollected.value += amount
    addTransaction()
  }

  function reset() {
    cashCollected.value = 0
    transactionCount.value = 0
    shiftName.value = ''
    shiftTimeRange.value = ''
    availableShifts.value = []
  }

  return {
    cashCollected,
    transactionCount,
    shiftName,
    shiftTimeRange,
    isLoading,
    availableShifts,
    loadShiftSummary,
    fetchShifts,
    addTransaction,
    addCashPayment,
    reset,
  }
})
