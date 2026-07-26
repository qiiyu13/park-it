<template>
  <NuxtLayout name="kiosk">
    <template #status-bar>
      <div class="flex items-center gap-2 w-full min-w-0">
        <PosStatusBar
          class="flex-1 min-w-0"
          :booth-connected="gateStore.boothConnected"
          :hardware-status="hardwareStatus"
        />
        <div class="h-5 w-px bg-border shrink-0" />
        <PosWorkerBadge
          :worker="workerSessionStore.currentWorker"
          :session-status="workerSessionStore.sessionStatus"
          @click="onWorkerBadgeClick"
        />
      </div>
    </template>

    <!-- Main: State-driven single-column layout -->
    <div :class="['h-full overflow-hidden', timeoutBorderClass]">
      <!-- GATE_OPEN: awaiting gate open after payment -->
      <PosGateOpenView
        v-if="viewState === 'GATE_OPEN'"
        :change-amount="gateStore.changeAmount"
        :plate-number="gateStore.currentTransaction?.plate_number || ''"
        @open-gate="openGateAction"
      />

      <!-- ERROR: timeout or e-money errors -->
      <PosErrorView
        v-else-if="viewState === 'ERROR'"
        :payment-state="gateStore.paymentState"
        :emoney-state="gateStore.emoneyPaymentState"
        :waiting-seconds="gateStore.waitingSeconds"
        :plate-number="gateStore.currentTransaction?.plate_number || ''"
        @manual-open="openGateAction"
        @vehicle-left="vehicleLeftAction"
        @pay-cash="showCashDialog = true"
        @pay-rfid="showRfidDialog = true"
        @retry-emoney="retryEmoney"
        @cancel-correction="cancelCorrection"
      />

      <!-- UNIFIED: consistent layout for both IDLE and ACTIVE states -->
      <PosUnifiedView
        v-else
        :transaction="gateStore.currentTransaction"
        :cameras="gatecameras"
        :duration-seconds="gateStore.durationSeconds"
        :waiting-seconds="gateStore.waitingSeconds"
        :payment-state="gateStore.paymentState"
        :emoney-state="gateStore.emoneyPaymentState"
        :vehicle-types="websiteStore.vehicleTypes"
        :timeout-seconds="timeoutSeconds"
        :can-pay-cash="gateStore.canPayCash"
        :can-pay-emoney="gateStore.canPayEmoney"
        :card-info="emoneyCardInfo"
        :balance="emoneyBalance"
        :awaiting-gate-open="gateStore.awaitingGateOpen"
        :is-processing="isPaymentProcessing"
        :is-mixed-lane="isMixedLane"
        :active-vehicle-type-id="activeVehicleTypeId"
        :active-tariff="displayTariff"
        :shift-name="posSession.shiftName"
        :transaction-count="posSession.transactionCount"
        :cash-collected="posSession.cashCollected"
        :last-entry="lastEntry"
        @barcode-lookup="onBarcodeLookup"
        @pay-cash="showCashDialog = true"
        @pay-emoney="startEmoneyPayment"
        @retry-emoney="retryEmoney"
        @cancel-emoney="cancelEmoney"
        @update:vehicle-type-id="onVehicleTypeChange"
      />
    </div>

    <template #action-bar>
      <PosQuickActionBar
        :payment-state="gateStore.paymentState"
        :emoney-state="gateStore.emoneyPaymentState"
        :awaiting-gate-open="gateStore.awaitingGateOpen"
        :can-pay-cash="gateStore.canPayCash"
        :can-pay-emoney="gateStore.canPayEmoney"
        :gate-name="selectedGate?.name || ''"
        :shift-name="posSession.shiftName"
        :is-mixed-lane="isMixedLane"
        :active-vehicle-type-name="activeVehicleTypeName"
      />
    </template>

    <!-- Worker Check-In (blocking — no session active) -->
    <PosWorkerCheckInDialog
      v-if="showCheckInDialog"
      :gate-id="selectedGate?.id"
      :workers="workerSessionStore.workers"
      :is-loading="workerSessionStore.isLoading"
      @check-in="onCheckIn"
    />

    <!-- Worker Handover -->
    <PosWorkerHandoverDialog
      v-if="showHandoverDialog"
      :session-id="workerSessionStore.activeSession?.id"
      :current-worker="workerSessionStore.currentWorker"
      :workers="workerSessionStore.workers"
      :is-loading="workerSessionStore.isLoading"
      :initial-step="handoverInitialStep"
      :early-leave="isEarlyLeave"
      @confirm-outgoing="onConfirmOutgoing"
      @confirm-incoming="onConfirmIncoming"
      @force-leave="onForceLeave"
      @cancel="showHandoverDialog = false"
    />

    <!-- Cash Dialog -->
    <PosCashDialog
      v-model:open="showCashDialog"
      :tariff="currentTariff"
      @confirm="confirmCashPayment"
    />

    <!-- RFID Dialog -->
    <PosRfidDialog
      v-model:open="showRfidDialog"
      @confirm="confirmRfidPayment"
    />
  </NuxtLayout>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useKeyboard } from '~/composables/useKeyboard'
import { useFormatters } from '~/composables/useFormatters'

definePageMeta({
  // middleware: 'auth',
  layout: false,
})

const websiteStore = useWebsiteStore()
const gateStore = useGateStore()
const posSession = usePosSessionStore()
const workerSessionStore = useWorkerSessionStore()
const { $ws } = useNuxtApp()
const config = useRuntimeConfig()
const { fetchApi } = useApi()
const sound = useSound()
const { hardwareStatus, updateFromGate, updateWebSocketStatus, updateBoothHardware, resetBoothHardware, startPolling, stopPolling } = useHardwareStatus()
const { detectCardType, maskCardNumber } = useFormatters()

// Worker session state
const showHandoverDialog = ref(false)
let shiftEndTimer = null

const showCheckInDialog = computed(() =>
  !!selectedGate.value &&
  !workerSessionStore.activeSession &&
  !workerSessionStore.isLoading
)

const handoverInitialStep = computed(() =>
  workerSessionStore.isPendingHandover ? 'pending' : 'outgoing'
)

const isEarlyLeave = computed(() => {
  const endTime = workerSessionStore.shiftEndTime
  if (!endTime) return false
  return new Date() < endTime
})

// Refs
let unsubscribeWs = null
let boothWs = null
let boothWsReconnectTimer = null
let boothWsReconnectAttempts = 0
const BOOTH_MAX_RECONNECT_ATTEMPTS = 10
const showCashDialog = ref(false)
const showRfidDialog = ref(false)
const emoneyBalance = ref(null)
const isPaymentProcessing = ref(false)
const lastEntry = ref(null)

// View state (priority: GATE_OPEN > ERROR > UNIFIED)
// UNIFIED view is always shown unless we're in a special state
const viewState = computed(() => {
  if (gateStore.awaitingGateOpen) return 'GATE_OPEN'
  if (
    gateStore.paymentState === 'TIMEOUT_ALERT' ||
    ['LOST_CONTACT', 'WRONG_CARD', 'INSUFFICIENT', 'FAILED'].includes(gateStore.emoneyPaymentState)
  ) {
    return 'ERROR'
  }
  return 'UNIFIED' // Always show unified view (handles both IDLE and ACTIVE)
})

// Timeout border class — ring overlay at 70%/90% thresholds
const timeoutBorderClass = computed(() => {
  if (!gateStore.currentTransaction || viewState.value !== 'UNIFIED') return ''
  const percent = timeoutSeconds.value > 0
    ? (gateStore.waitingSeconds / timeoutSeconds.value) * 100
    : 0
  if (percent >= 90) return 'ring-2 ring-inset ring-destructive/60'
  if (percent >= 70) return 'ring-2 ring-inset ring-warning/40'
  return ''
})

// Computed
const selectedGate = computed(() =>
  websiteStore.activeGateOuts.find((g) => g.id === gateStore.selectedGateOutId)
)

const gateStatuses = computed(() => {
  const statuses = []
  if (selectedGate.value) {
    statuses.push({
      name: selectedGate.value.name,
      direction: 'OUT',
      connected: gateStore.wsConnected,
    })
  }
  for (const g of websiteStore.activeGateIns) {
    statuses.push({
      name: g.name,
      direction: 'IN',
      connected: g.is_online ?? false,
    })
  }
  return statuses
})

// Alert operator when a gate controller transitions to disconnected.
// Debounced: a disconnect must persist GATE_FLAP_GRACE_MS before alerting, so
// brief network flap (drop + immediate reconnect) doesn't spam the operator.
const GATE_FLAP_GRACE_MS = 3000
const _prevGateConnected = new Map()
const _disconnectTimers = new Map()
const _disconnectAlerted = new Map()

watch(
  gateStatuses,
  (statuses) => {
    for (const g of statuses) {
      const prev = _prevGateConnected.get(g.name)
      if (prev === true && g.connected === false) {
        // Wait out the grace window — only alert if still down afterwards.
        if (!_disconnectTimers.has(g.name)) {
          const timer = setTimeout(() => {
            _disconnectTimers.delete(g.name)
            toast.error(`Controller ${g.name} terputus`)
            _disconnectAlerted.set(g.name, true)
          }, GATE_FLAP_GRACE_MS)
          _disconnectTimers.set(g.name, timer)
        }
      } else if (prev === false && g.connected === true) {
        // Reconnected — cancel any pending disconnect alert.
        const timer = _disconnectTimers.get(g.name)
        if (timer) {
          clearTimeout(timer)
          _disconnectTimers.delete(g.name)
        }
        // Only announce recovery if we actually surfaced the outage.
        if (_disconnectAlerted.get(g.name)) {
          toast.success(`Controller ${g.name} terhubung kembali`)
          _disconnectAlerted.set(g.name, false)
        }
      }
      _prevGateConnected.set(g.name, g.connected)
    }
  },
  { deep: true },
)

onBeforeUnmount(() => {
  for (const timer of _disconnectTimers.values()) clearTimeout(timer)
  _disconnectTimers.clear()
})

const gatecameras = computed(() => {
  const hw = selectedGate.value?.hardware_config
  if (!hw) return []
  const list = hw.cameras || []
  if (list.length) return list.filter((c) => c.url && c.enabled !== false)
  const cam = hw.camera
  if (cam?.enabled && cam?.url) return [{ url: cam.url, label: null }]
  return []
})

const displayTariff = ref(0)

const currentTariff = computed(() => displayTariff.value)

const timeoutSeconds = computed(() =>
  parseInt(websiteStore.getSetting('payment_timeout_seconds', '120'))
)

// Vehicle type selection
const activeVehicleTypeId = ref(null)

const isMixedLane = computed(() => {
  const hw = selectedGate.value?.hardware_config
  if (!hw || !hw.lane_type) return true
  return hw.lane_type === 'MIXED'
})

const activeVehicleTypeName = computed(() => {
  if (!activeVehicleTypeId.value) return null
  return websiteStore.vehicleTypes.find((t) => t.id === activeVehicleTypeId.value)?.name || null
})

const emoneyCardInfo = computed(() => {
  const tx = gateStore.currentTransaction
  if (!tx?.card_number) return null
  return {
    cardType: detectCardType(tx.card_number),
    cardNumber: maskCardNumber(tx.card_number),
  }
})

// Sync displayTariff when transaction loads/clears
watch(() => gateStore.currentTransaction, (tx) => {
  displayTariff.value = tx?.tariff || tx?.fee || 0
  if (tx?.entry_snapshot_id && tx?.plate_number) {
    lastEntry.value = {
      plateNumber: tx.plate_number,
      snapshotUrl: `/api/snapshots/${tx.entry_snapshot_id}/image`,
      gateLabel: tx.entry_gate_name || tx.entry_gate_code || null,
      subtitle: 'baru saja masuk',
    }
  }
})

// Auto-set vehicle type for single-lane gates
watch(selectedGate, (gate) => {
  if (gate && !isMixedLane.value) {
    activeVehicleTypeId.value = gate.hardware_config?.default_vehicle_type_id || null
  } else {
    activeVehicleTypeId.value = null
  }
}, { immediate: true })

// Keyboard shortcuts
useKeyboard([
  { keys: ['F1'], action: () => gateStore.canPayCash && (showCashDialog.value = true) },
  { keys: ['F2'], action: () => gateStore.canPayEmoney && startEmoneyPayment() },
  { keys: ['F3'], action: () => gateStore.canPayRfid && (showRfidDialog.value = true) }, // hidden fallback
  { keys: [' '], action: () => gateStore.awaitingGateOpen && openGateAction() },
  { keys: ['Escape'], action: () => { showCashDialog.value = false; showRfidDialog.value = false } },
  {
    keys: ['c', 'C'],
    action: () => {
      if (!isMixedLane.value) return
      const vt = websiteStore.vehicleTypes.find((t) => /MOB|CAR/i.test(t.code))
        || websiteStore.vehicleTypes[0]
      if (vt) onVehicleTypeChange(vt.id)
    },
  },
  {
    keys: ['m', 'M'],
    action: () => {
      if (!isMixedLane.value) return
      const vt = websiteStore.vehicleTypes.find((t) => /MOT/i.test(t.code))
        || websiteStore.vehicleTypes[1]
      if (vt) onVehicleTypeChange(vt.id)
    },
  },
], {
  // Suppress F-key/letter shortcuts while a modal owns input focus so they
  // don't hijack PIN/amount typing. Escape still passes through.
  isBlocked: () =>
    showCashDialog.value ||
    showRfidDialog.value ||
    showCheckInDialog.value ||
    showHandoverDialog.value,
})

// Actions
async function onBarcodeLookup(input) {
  const v = input?.trim()
  if (!v) return
  const found = await gateStore.lookupTransaction({ barcode: v, plateNumber: v })
  if (!found) toast.warning('Transaksi tidak ditemukan')
}

async function onVehicleTypeChange(vehicleTypeId) {
  activeVehicleTypeId.value = vehicleTypeId
  const tx = gateStore.currentTransaction
  if (!tx?.id) return
  try {
    const res = await fetchApi('/api/payments/calculate-fee', {
      method: 'POST',
      body: JSON.stringify({ transaction_id: tx.id, vehicle_type_id: vehicleTypeId }),
    })
    displayTariff.value = res.fee
  } catch (e) {
    console.error('Fee calculation failed:', e)
  }
}

async function confirmCashPayment(amount) {
  if (!selectedGate.value || isPaymentProcessing.value) return
  isPaymentProcessing.value = true
  try {
    const gateCode = selectedGate.value.code || `gate-out-${selectedGate.value.id}`
    const result = await gateStore.confirmCashPayment({
      gateId: gateCode,
      gateOutId: selectedGate.value.id,
      paidAmount: amount,
      vehicleTypeId: activeVehicleTypeId.value,
    })
    if (result?.success) {
      sound.paymentSuccess()
      posSession.addCashPayment(amount - (result.change_amount || 0))
      toast.success('Pembayaran berhasil. Tekan Space untuk buka palang.')
    } else {
      toast.error(result?.message || 'Pembayaran tunai gagal')
    }
  } finally {
    isPaymentProcessing.value = false
  }
}

async function confirmRfidPayment(cardNumber) {
  if (!cardNumber.trim() || !selectedGate.value || isPaymentProcessing.value) {
    if (!cardNumber.trim()) toast.warning('Masukkan nomor kartu RFID')
    return
  }
  isPaymentProcessing.value = true
  try {
    const gateCode = selectedGate.value.code || `gate-out-${selectedGate.value.id}`
    const result = await gateStore.processRfidPayment({
      gateId: gateCode,
      gateOutId: selectedGate.value.id,
      cardNumber: cardNumber.trim(),
    })
    if (result?.success) {
      sound.paymentSuccess()
      posSession.addTransaction()
      toast.success(result.message || 'Pembayaran RFID berhasil')
    } else {
      toast.error(result?.message || 'Pembayaran RFID gagal')
    }
  } finally {
    isPaymentProcessing.value = false
  }
}

async function startEmoneyPayment() {
  const tx = gateStore.currentTransaction
  if (!tx?.barcode) {
    toast.warning('Pindai tiket terlebih dulu sebelum tap kartu')
    return
  }
  if (!selectedGate.value) return

  if (!gateStore.boothConnected || !boothWs) {
    toast.error('Booth bridge offline — tidak dapat memproses e-money')
    return
  }

  const gateCode = selectedGate.value.code || `gate-out-${selectedGate.value.id}`
  // 1. Arm the deduct server-side (stores pending state, returns recomputed fee).
  const armed = await gateStore.startEmoneyDeduct({
    gateId: gateCode,
    gateOutId: selectedGate.value.id,
    barcode: tx.barcode,
    vehicleTypeId: tx.vehicle_type_id ?? null,
  })
  if (!armed?.success) {
    toast.error(armed?.message || 'Gagal menyiapkan pembayaran e-money')
    return
  }

  // 2. Ask booth bridge to deduct the armed amount when the driver taps.
  boothWs.send(JSON.stringify({
    action: 'emoney_deduct',
    peripheral: 'emoney_reader',
    amount: armed.fee,
    gate_id: gateCode,
    gate_out_id: selectedGate.value.id,
  }))
  gateStore.setEmoneyState('PROCESSING')
  toast.info('Silakan tap kartu e-money')
}

function cancelEmoney() {
  gateStore.setEmoneyState('IDLE')
}

function retryEmoney() {
  gateStore.setEmoneyState('IDLE')
  startEmoneyPayment()
}

function cancelCorrection() {
  gateStore.setEmoneyState('IDLE')
  toast.info('Koreksi dibatalkan')
}

async function openGateAction() {
  if (!selectedGate.value) return

  // Attended OUT gates: drive booth_bridge directly (no daemon at exit).
  // Frontend only requests the open — hardware path + hex live in the
  // bridge's pre-configured GateOpener (gate.hardware_config + booth.json),
  // so a stale POS cache can't write to the wrong port.
  if (gateStore.boothConnected && boothWs) {
    boothWs.send(JSON.stringify({
      action: 'open_gate',
      gate_code: selectedGate.value.code,
    }))
    sound.gateOpen()
    toast.success('Palang pintu dibuka')
    gateStore.clearTransaction()
    return
  }

  const result = await gateStore.openGate({ gateId: selectedGate.value.id })
  if (result?.success) {
    sound.gateOpen()
    toast.success('Palang pintu dibuka')
  } else {
    toast.error(result?.message || 'Gagal membuka palang')
  }
}

function vehicleLeftAction() {
  gateStore.clearTransaction()
  toast.info('Kendaraan pergi — transaksi dibersihkan')
}

// Booth bridge connection
function connectBooth() {
  if (boothWs) {
    try { boothWs.close() } catch { /* ignore */ }
  }

  if (boothWsReconnectAttempts >= BOOTH_MAX_RECONNECT_ATTEMPTS) {
    console.warn('Booth bridge: max reconnect attempts reached, giving up')
    gateStore.setBoothConnected(false)
    resetBoothHardware()
    return
  }

  const boothUrl = config.public.boothBridgeUrl || 'ws://localhost:5678/'
  boothWs = new WebSocket(boothUrl)
  boothWs.onopen = () => {
    gateStore.setBoothConnected(true)
    boothWsReconnectAttempts = 0
    if (boothWsReconnectTimer) {
      clearTimeout(boothWsReconnectTimer)
      boothWsReconnectTimer = null
    }
  }
  boothWs.onmessage = (event) => {
    try {
      handleBoothMessage(JSON.parse(event.data))
    } catch (e) {
      console.error('Booth message parse error:', e)
    }
  }
  boothWs.onerror = () => { gateStore.setBoothConnected(false); resetBoothHardware() }
  boothWs.onclose = () => {
    gateStore.setBoothConnected(false)
    resetBoothHardware()
    if (!boothWsReconnectTimer) {
      boothWsReconnectAttempts++
      const delay = Math.min(3000 * Math.pow(2, boothWsReconnectAttempts - 1), 60000)
      boothWsReconnectTimer = setTimeout(() => {
        boothWsReconnectTimer = null
        connectBooth()
      }, delay)
    }
  }
}

function disconnectBooth() {
  if (boothWsReconnectTimer) {
    clearTimeout(boothWsReconnectTimer)
    boothWsReconnectTimer = null
  }
  if (boothWs) {
    try { boothWs.close() } catch { /* ignore */ }
    boothWs = null
  }
  gateStore.setBoothConnected(false)
  resetBoothHardware()
}

function handleBoothMessage(data) {
  // Server-pushed events from booth_bridge (UHF auto-flow, eMoney broadcast)
  if (data.type === 'hardware_status') {
    updateBoothHardware(data)
    return
  }
  if (data.event === 'member_card_scanned') {
    if (data.success) {
      sound.gateOpen()
      toast.success(`Member ${data.card_number} keluar`)
    } else {
      sound.paymentFailed()
      toast.error(data.message || `Kartu ${data.card_number} ditolak`)
    }
    return
  }
  if (data.event === 'emoney_payment_completed') {
    // Mirror of emoney_deduct_result; primary handling already done via action response.
    return
  }

  if (data.action === 'emoney_deduct_result') {
    if (data.status === 'SUCCESS') {
      gateStore.setEmoneyState('SUCCESS')
      emoneyBalance.value = data.balance_after
      sound.paymentSuccess()
      if (selectedGate.value) {
        const gateCode = selectedGate.value.code || `gate-out-${selectedGate.value.id}`
        gateStore.confirmEmoneyPayment({
          gateId: gateCode,
          gateOutId: selectedGate.value.id,
          cardNumber: data.card_number,
          deductAmount: data.deduct_amount,
          balanceBefore: data.balance_before,
          balanceAfter: data.balance_after,
          transactionCounter: data.transaction_counter,
          rawResponseHex: data.raw_response_hex,
        })
      }
      toast.success('Pembayaran e-money berhasil')
    } else if (data.status === 'LOST_CONTACT') {
      gateStore.setEmoneyState('LOST_CONTACT')
      sound.paymentFailed()
      toast.warning('Tap kartu lagi untuk koreksi')
    } else if (data.status === 'INSUFFICIENT_BALANCE') {
      gateStore.setEmoneyState('INSUFFICIENT')
      sound.paymentFailed()
      toast.warning('Saldo tidak cukup')
    } else if (data.status === 'WRONG_CARD') {
      gateStore.setEmoneyState('WRONG_CARD')
      sound.paymentFailed()
      toast.error('Kartu tidak sesuai')
    } else {
      gateStore.setEmoneyState('FAILED')
      sound.paymentFailed()
      toast.error(data.error || 'E-Money gagal')
    }
  }
}

function onGateChange(gateId) {
  if (unsubscribeWs) {
    unsubscribeWs()
    unsubscribeWs = null
  }

  gateStore.clearTransaction()

  if (!gateId) return

  const gate = websiteStore.activeGateOuts.find((g) => g.id === gateId)
  if (!gate) return

  const gateCode = gate.code || `gateway-out-${gateId}`

  unsubscribeWs = $ws.on(gateCode, (event) => {
    gateStore.handleWsEvent(event)

    if (event.type === 'ws_open') {
      gateStore.setWsConnected(true)
      updateWebSocketStatus(true)
    } else if (event.type === 'ws_close' || event.type === 'ws_error') {
      gateStore.setWsConnected(false)
      updateWebSocketStatus(false)
    } else if (event.type === 'vehicle_detected') {
      sound.vehicleDetected()
    } else if (event.type === 'timeout_alert') {
      sound.timeoutAlert()
    }
  })

  const connected = $ws.isConnected(gateCode)
  gateStore.setWsConnected(connected)
  updateWebSocketStatus(connected)
  updateFromGate(gate)
}

// Worker session handlers
function onWorkerBadgeClick() {
  if (!workerSessionStore.activeSession) return  // check-in dialog handles it
  showHandoverDialog.value = true
}

async function onCheckIn(payload) {
  await workerSessionStore.checkIn(payload)
  toast.success(`Selamat bertugas, ${workerSessionStore.currentWorker?.full_name || ''}!`)
}

async function onConfirmOutgoing(payload) {
  await workerSessionStore.confirmOutgoing(payload)
  // dialog stays open in pending step
}

async function onConfirmIncoming(payload) {
  await workerSessionStore.confirmIncoming(payload)
  showHandoverDialog.value = false
  scheduleShiftEndTimer()
  toast.success(`Serah terima berhasil. Selamat bertugas!`)
}

async function onForceLeave(payload) {
  await workerSessionStore.forceLeave(payload)
  showHandoverDialog.value = false
  toast.warning('Anda meninggalkan pos. Admin telah diberitahu.')
}

function scheduleShiftEndTimer() {
  if (shiftEndTimer) {
    clearTimeout(shiftEndTimer)
    shiftEndTimer = null
  }
  const endTime = workerSessionStore.shiftEndTime
  if (!endTime) return
  const msUntilEnd = endTime.getTime() - Date.now()
  if (msUntilEnd <= 0) return
  shiftEndTimer = setTimeout(() => {
    if (workerSessionStore.sessionStatus === 'ACTIVE') {
      showHandoverDialog.value = true
    }
  }, msUntilEnd)
}

// Watch for pending handover state (e.g. page reload mid-handover)
watch(() => workerSessionStore.isPendingHandover, (val) => {
  if (val) showHandoverDialog.value = true
})

// Toast helper (using vue-sonner)
const toast = {
  success: (msg) => useNuxtApp().$toast?.success?.(msg) || console.log('[success]', msg),
  error: (msg) => useNuxtApp().$toast?.error?.(msg) || console.error('[error]', msg),
  warning: (msg) => useNuxtApp().$toast?.warning?.(msg) || console.warn('[warning]', msg),
  info: (msg) => useNuxtApp().$toast?.info?.(msg) || console.log('[info]', msg),
}

// Lifecycle
onMounted(async () => {
  await websiteStore.loadAll()
  await posSession.loadShiftSummary()

  // Auto-detect booth by IP
  let gateDetected = false
  try {
    const pos = await fetchApi('/api/pos/by-ip')
    if (pos.default_gate_id) {
      const gate = websiteStore.activeGateOuts.find((g) => g.id === pos.default_gate_id)
      if (gate) {
        gateStore.setSelectedGateOutId(gate.id)
        onGateChange(gate.id)
        gateDetected = true
        toast.info(`Terhubung ke ${gate.name}`)
      }
    }
  } catch (err) {
    console.warn('Booth auto-detection failed:', err.message)
  }

  // Fallback to first available gate
  if (!gateDetected && websiteStore.activeGateOuts.length > 0) {
    const fallbackGate = websiteStore.activeGateOuts[0]
    gateStore.setSelectedGateOutId(fallbackGate.id)
    onGateChange(fallbackGate.id)
    toast.warning(`Auto-deteksi gagal, menggunakan ${fallbackGate.name}`)
  }

  connectBooth()
  startPolling(60000)

  // Worker session init (after gate detection so gateId is available)
  await workerSessionStore.fetchWorkers()
  if (selectedGate.value?.id) {
    await workerSessionStore.fetchActiveSession(selectedGate.value.id)
    scheduleShiftEndTimer()
  }
})

onBeforeUnmount(() => {
  if (unsubscribeWs) {
    unsubscribeWs()
    unsubscribeWs = null
  }
  disconnectBooth()
  stopPolling()
  gateStore.stopDurationTimer()
  if (shiftEndTimer) clearTimeout(shiftEndTimer)
})
</script>
