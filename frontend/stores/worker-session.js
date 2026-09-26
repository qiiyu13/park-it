/**
 * Worker Session Store (Pinia)
 * Manages shift handover state for POS operator UI.
 */

import { defineStore } from 'pinia'

export const useWorkerSessionStore = defineStore('worker-session', () => {
  const activeSession = ref(null)     // WorkerSessionResponse | null
  const workers = ref([])             // list of active workers with PINs
  const isLoading = ref(false)
  const error = ref(null)
  const fetchError = ref(null)        // last transient session-fetch failure

  const sessionStatus = computed(() => activeSession.value?.status || null)
  const currentWorker = computed(() => activeSession.value?.worker || null)
  const isUncovered = computed(() => activeSession.value === null)
  const isPendingHandover = computed(() => sessionStatus.value === 'PENDING_HANDOVER')

  // Shift end time as Date | null
  const shiftEndTime = computed(() => {
    const endTime = activeSession.value?.shift?.end_time
    if (!endTime) return null
    const [h, m] = endTime.split(':').map(Number)
    const d = new Date()
    d.setHours(h, m, 0, 0)
    return d
  })

  async function fetchActiveSession(gateId) {
    if (!gateId) return
    try {
      const { fetchApi } = useApi()
      const data = await fetchApi(`/api/worker-sessions/active?gate_id=${gateId}`)
      activeSession.value = data
      fetchError.value = null
    } catch (err) {
      if (err.status !== 404) {
        // Transient failure (network/server blip): keep the last known value
        // instead of nulling it — a false "no session" throws the operator
        // into the blocking check-in dialog while their shift is still live.
        fetchError.value = err.message
        console.warn('fetchActiveSession:', err.message)
        return
      }
      fetchError.value = null
      activeSession.value = null
    }
  }

  async function fetchWorkers() {
    try {
      const { fetchApi } = useApi()
      const data = await fetchApi('/api/users/workers')
      workers.value = Array.isArray(data) ? data : []
    } catch (err) {
      console.warn('fetchWorkers:', err.message)
    }
  }

  async function checkIn({ gateId, workerId, pin, shiftAssignmentId = null, isSubstitute = false, originalWorkerId = null }) {
    isLoading.value = true
    error.value = null
    try {
      const { fetchApi } = useApi()
      const session = await fetchApi('/api/worker-sessions/check-in', {
        method: 'POST',
        body: JSON.stringify({
          gate_id: gateId,
          worker_id: workerId,
          pin,
          shift_assignment_id: shiftAssignmentId,
          is_substitute: isSubstitute,
          original_worker_id: originalWorkerId,
        }),
      })
      activeSession.value = session
      return session
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function confirmOutgoing({ sessionId, pin, endType = 'SCHEDULED', endReason = null }) {
    isLoading.value = true
    error.value = null
    try {
      const { fetchApi } = useApi()
      const session = await fetchApi(`/api/worker-sessions/${sessionId}/confirm-outgoing`, {
        method: 'POST',
        body: JSON.stringify({ pin, end_type: endType, end_reason: endReason }),
      })
      activeSession.value = session
      return session
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function confirmIncoming({ sessionId, workerId, pin, isSubstitute = false, originalWorkerId = null }) {
    isLoading.value = true
    error.value = null
    try {
      const { fetchApi } = useApi()
      const session = await fetchApi(`/api/worker-sessions/${sessionId}/confirm-incoming`, {
        method: 'POST',
        body: JSON.stringify({
          worker_id: workerId,
          pin,
          is_substitute: isSubstitute,
          original_worker_id: originalWorkerId,
        }),
      })
      activeSession.value = session
      return session
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function forceLeave({ sessionId, pin, reason }) {
    isLoading.value = true
    error.value = null
    try {
      const { fetchApi } = useApi()
      const session = await fetchApi(`/api/worker-sessions/${sessionId}/force-leave`, {
        method: 'POST',
        body: JSON.stringify({ pin, reason }),
      })
      activeSession.value = null  // booth is now uncovered
      return session
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      isLoading.value = false
    }
  }

  function clearError() {
    error.value = null
  }

  return {
    activeSession,
    workers,
    isLoading,
    error,
    fetchError,
    sessionStatus,
    currentWorker,
    isUncovered,
    isPendingHandover,
    shiftEndTime,
    fetchActiveSession,
    fetchWorkers,
    checkIn,
    confirmOutgoing,
    confirmIncoming,
    forceLeave,
    clearError,
  }
})
