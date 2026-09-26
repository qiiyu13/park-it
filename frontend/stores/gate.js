/**
 * Gate Store (Pinia)
 *
 * Real-time gate-out state for the POS operator.
 * Tracks: current transaction, payment state, e-money payment state,
 * WebSocket connection status, camera snapshot, waiting seconds,
 * duration timer, and hardware status.
 */

import { defineStore } from 'pinia'

export const useGateStore = defineStore('gate', () => {
  // State
  const currentTransaction = ref(null)
  const paymentState = ref('IDLE')
  const emoneyPaymentState = ref('IDLE')
  const wsConnected = ref(false)
  const boothConnected = ref(false)
  const cameraSnapshot = ref(null)
  const waitingSeconds = ref(0)
  const selectedGateOutId = ref(null)
  const alertMessage = ref(null)
  const isLoading = ref(false)
  const awaitingGateOpen = ref(false)
  const durationSeconds = ref(0)
  const changeAmount = ref(0)

  // Duration timer
  let durationInterval = null

  // Getters
  const isWaitingPayment = computed(() => paymentState.value === 'WAITING_PAYMENT')
  const isTimeout = computed(() => paymentState.value === 'TIMEOUT_ALERT')
  const canPayCash = computed(() => (isWaitingPayment.value || isTimeout.value) && !awaitingGateOpen.value)
  const canPayEmoney = computed(() => (isWaitingPayment.value || isTimeout.value) && !awaitingGateOpen.value)
  const canPayRfid = computed(() => (isWaitingPayment.value || isTimeout.value) && !awaitingGateOpen.value)

  // Actions

  function setTransaction(tx) {
    currentTransaction.value = tx
    if (tx?.entry_time) {
      startDurationTimer(tx.entry_time)
    }
  }

  function clearTransaction() {
    currentTransaction.value = null
    paymentState.value = 'IDLE'
    emoneyPaymentState.value = 'IDLE'
    cameraSnapshot.value = null
    waitingSeconds.value = 0
    alertMessage.value = null
    awaitingGateOpen.value = false
    changeAmount.value = 0
    stopDurationTimer()
  }

  function setPaymentState(state) {
    paymentState.value = state
  }

  function setEmoneyState(state) {
    emoneyPaymentState.value = state
  }

  function setWsConnected(connected) {
    wsConnected.value = connected
  }

  function setBoothConnected(connected) {
    boothConnected.value = connected
  }

  function setCameraSnapshot(url) {
    cameraSnapshot.value = url
  }

  function setWaitingSeconds(seconds) {
    waitingSeconds.value = seconds
  }

  function setSelectedGateOutId(id) {
    selectedGateOutId.value = id
  }

  function setAlertMessage(message) {
    alertMessage.value = message
  }

  function startDurationTimer(entryTime) {
    stopDurationTimer()
    const entry = new Date(entryTime)
    durationSeconds.value = Math.floor((Date.now() - entry.getTime()) / 1000)
    durationInterval = setInterval(() => {
      if (currentTransaction.value?.entry_time) {
        const e = new Date(currentTransaction.value.entry_time)
        durationSeconds.value = Math.floor((Date.now() - e.getTime()) / 1000)
      }
    }, 1000)
  }

  function stopDurationTimer() {
    if (durationInterval) {
      clearInterval(durationInterval)
      durationInterval = null
    }
    durationSeconds.value = 0
  }

  /**
   * Look up an active transaction by barcode, card, or plate.
   */
  async function lookupTransaction({ barcode, cardNumber, plateNumber }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/payments/lookup', {
        method: 'POST',
        body: JSON.stringify({
          barcode,
          card_number: cardNumber,
          plate_number: plateNumber,
        }),
      })
      if (res.found && res.transaction) {
        currentTransaction.value = {
          ...res.transaction,
          tariff: res.fee,
        }
        if (res.transaction.entry_time) {
          startDurationTimer(res.transaction.entry_time)
        }
        paymentState.value = 'WAITING_PAYMENT'
        return true
      }
      return false
    } catch (err) {
      console.error('lookupTransaction error:', err)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Confirm cash payment.
   * Returns { success, change_amount, message } — caller handles notifications.
   */
  async function confirmCashPayment({ gateId, gateOutId, paidAmount, vehicleTypeId = null }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/payments/cash', {
        method: 'POST',
        body: JSON.stringify({
          gate_id: gateId,
          gate_out_id: gateOutId,
          barcode: currentTransaction.value?.barcode,
          plate_number: currentTransaction.value?.plate_number,
          paid_amount: paidAmount,
          vehicle_type_id: vehicleTypeId,
        }),
      })
      if (res.success) {
        changeAmount.value = res.change_amount || 0
        awaitingGateOpen.value = true
        return res
      }
      return res
    } catch (err) {
      return { success: false, message: err.message || 'Pembayaran tunai gagal' }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Open the gate manually (two-step flow after cash payment).
   * Returns { success, message } — caller handles notifications.
   */
  async function openGate({ gateId }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi(`/api/gates/${gateId}/open`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'operator' }),
      })
      if (res.success) {
        awaitingGateOpen.value = false
        clearTransaction()
        return res
      }
      return res
    } catch (err) {
      return { success: false, message: err.message || 'Gagal membuka palang' }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Process RFID payment.
   * Returns { success, message } — caller handles notifications.
   */
  async function processRfidPayment({ gateId, gateOutId, cardNumber }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/payments/rfid', {
        method: 'POST',
        body: JSON.stringify({
          gate_id: gateId,
          gate_out_id: gateOutId,
          card_number: cardNumber,
        }),
      })
      if (res.success) {
        clearTransaction()
      }
      return res
    } catch (err) {
      return { success: false, message: err.message || 'Pembayaran RFID gagal' }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Arm an e-money deduct for a scanned ticket. API stores the pending
   * (gate_id → transaction_id) state in Redis; booth_bridge fires the
   * actual deduct when the driver taps. Returns { success, fee, transaction_id }.
   */
  async function startEmoneyDeduct({ gateId, gateOutId, barcode, vehicleTypeId = null }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/payments/emoney/deduct', {
        method: 'POST',
        body: JSON.stringify({
          gate_id: gateId,
          gate_out_id: gateOutId,
          barcode,
          vehicle_type_id: vehicleTypeId,
        }),
      })
      if (res.success) {
        emoneyPaymentState.value = 'PROCESSING'
      } else {
        emoneyPaymentState.value = 'FAILED'
      }
      return res
    } catch (err) {
      emoneyPaymentState.value = 'FAILED'
      return { success: false, message: err.message || 'E-money deduct gagal' }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Confirm e-money payment (called after booth bridge deduct success).
   * Returns { success, message } — caller handles notifications.
   *
   * Carries the settlement fields (payload/card type/MID/TID) so this
   * writer records complete data even when it beats the bridge's own POST.
   * The API is idempotent — whichever lands second returns the first's
   * result instead of erroring.
   */
  async function confirmEmoneyPayment({
    gateId, gateOutId, transactionId, cardNumber, deductAmount,
    balanceBefore, balanceAfter, transactionCounter, rawResponseHex,
    settlementPayloadHex = '', cardType = null, cardTypeCode = null,
    mid = null, tid = null,
  }) {
    isLoading.value = true
    try {
      const { fetchApi } = useApi()
      const res = await fetchApi('/api/payments/emoney/result', {
        method: 'POST',
        body: JSON.stringify({
          gate_id: gateId,
          gate_out_id: gateOutId,
          transaction_id: transactionId ?? null,
          card_number: cardNumber,
          status: 'SUCCESS',
          deduct_amount: deductAmount,
          balance_before: balanceBefore,
          balance_after: balanceAfter,
          transaction_counter: transactionCounter,
          raw_response_hex: rawResponseHex,
          settlement_payload_hex: settlementPayloadHex,
          card_type: cardType,
          card_type_code: cardTypeCode,
          mid,
          tid,
        }),
      })
      if (res.success) {
        clearTransaction()
      }
      return res
    } catch (err) {
      return { success: false, message: err.message || 'E-money payment failed' }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Handle incoming WebSocket event.
   */
  const AUDIO_TRACK_MAP = {
    1: '001_selamat_datang.mp3',
    2: '002_ambil_tiket.mp3',
    3: '003_kartu_tidak_valid.mp3',
    4: '004_member_tidak_aktif.mp3',
    5: '005_tunggu_petugas.mp3',
    6: '006_saldo_kurang.mp3',
    7: '007_kartu_salah.mp3',
    8: '008_hubungi_petugas.mp3',
    9: '009_terima_kasih.mp3',
    10: '010_pembayaran_berhasil.mp3',
    11: '011_transaksi_gagal.mp3',
    12: '012_waktu_habis.mp3',
  }

  function playAudioTrack(track) {
    const filename = AUDIO_TRACK_MAP[track]
    if (filename) {
      new Audio(`/audio/${filename}`).play().catch(() => {})
    }
  }

  async function handleWsEvent(event) {
    switch (event.type) {
      case 'vehicle_detected':
        paymentState.value = 'VEHICLE_PRESENT'
        if (event.card_number) {
          await lookupTransaction({ cardNumber: event.card_number })
        }
        break
      case 'gate_closed':
        paymentState.value = 'WAITING_PAYMENT'
        waitingSeconds.value = 0
        break
      case 'timeout_alert':
        paymentState.value = 'TIMEOUT_ALERT'
        alertMessage.value = `Kendaraan menunggu selama ${event.waiting_seconds || 0} detik`
        break
      case 'vehicle_passed':
      case 'vehicle_left':
        clearTransaction()
        break
      case 'deduct_result':
        if (event.status === 'SUCCESS') {
          emoneyPaymentState.value = 'SUCCESS'
          setTimeout(() => clearTransaction(), 3000)
        } else if (event.status === 'LOST_CONTACT') {
          emoneyPaymentState.value = 'LOST_CONTACT'
        } else if (event.status === 'WRONG_CARD') {
          emoneyPaymentState.value = 'WRONG_CARD'
        } else if (event.status === 'INSUFFICIENT_BALANCE') {
          emoneyPaymentState.value = 'INSUFFICIENT'
        } else {
          emoneyPaymentState.value = 'FAILED'
        }
        break
      case 'rfid_card_read':
        if (event.card_number && currentTransaction.value) {
          // RFID handled server-side; POS gets notified
        }
        break
      case 'camera_snapshot':
        if (event.snapshot_type === 'exit') {
          cameraSnapshot.value = event.snapshot_url
        }
        break
      case 'play_audio':
        playAudioTrack(event.track)
        break
      default:
        break
    }
  }

  return {
    currentTransaction,
    paymentState,
    emoneyPaymentState,
    wsConnected,
    boothConnected,
    cameraSnapshot,
    waitingSeconds,
    selectedGateOutId,
    alertMessage,
    isLoading,
    awaitingGateOpen,
    durationSeconds,
    changeAmount,
    isWaitingPayment,
    isTimeout,
    canPayCash,
    canPayEmoney,
    canPayRfid,
    setTransaction,
    clearTransaction,
    setPaymentState,
    setEmoneyState,
    setWsConnected,
    setBoothConnected,
    setCameraSnapshot,
    setWaitingSeconds,
    setSelectedGateOutId,
    setAlertMessage,
    startDurationTimer,
    stopDurationTimer,
    lookupTransaction,
    confirmCashPayment,
    openGate,
    processRfidPayment,
    startEmoneyDeduct,
    confirmEmoneyPayment,
    handleWsEvent,
  }
})
