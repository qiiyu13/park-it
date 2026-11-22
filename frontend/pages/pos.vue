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

    <!-- Blocking registration error: never guess which lane this PC owns. -->
    <div
      v-if="posRegistrationError"
      class="fixed inset-0 z-40 flex items-center justify-center bg-background/95 p-6"
    >
      <div class="w-full max-w-lg rounded-xl border border-border bg-surface p-6 shadow-brutal-lg">
        <div class="text-xs font-semibold text-destructive">
          POS Tidak Terdaftar
        </div>
        <h1 class="mt-2 text-2xl font-semibold tracking-tight">
          Komputer ini belum terhubung ke booth
        </h1>
        <p class="mt-3 text-sm text-muted-foreground">
          {{ posRegistrationError }}
        </p>
        <div class="mt-5 flex gap-3">
          <Button variant="outline" @click="navigateTo('/')">
            Kembali ke Dashboard
          </Button>
          <Button @click="reloadPage">Coba Lagi</Button>
        </div>
      </div>
    </div>

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
        @pay-cash="payCash"
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
        :lane-vehicle-type-options="carLaneOptions"
        :timeout-seconds="timeoutSeconds"
        :can-pay-cash="gateStore.canPayCash"
        :can-pay-emoney="gateStore.canPayEmoney"
        :card-info="emoneyCardInfo"
        :balance="emoneyBalance"
        :awaiting-gate-open="gateStore.awaitingGateOpen"
        :is-processing="isPaymentProcessing"
        :is-mixed-lane="isMixedLane"
        :emoney-enabled="emoneyEnabled"
        :entry-snapshot-url="entrySnapshotUrl"
        :active-vehicle-type-id="activeVehicleTypeId"
        :active-tariff="displayTariff"
        :shift-name="posSession.shiftName"
        :transaction-count="posSession.transactionCount"
        :cash-collected="posSession.cashCollected"
        :last-entry="lastEntry"
        @barcode-lookup="onBarcodeLookup"
        @plate-lookup="onPlateLookup"
        @plate-entered="onPlateEntered"
        @pay-cash="payCash"
        @pay-emoney="startEmoneyPayment"
        @retry-emoney="retryEmoney"
        @cancel-emoney="cancelEmoney"
        @update:vehicle-type-id="onVehicleTypeChange"
        :show-plate="showPlate"
        :plate-prefix="platePrefix"
        :lane-vehicle-type-name="laneVehicleTypeName"
        :fallback-plate="pendingPlate"
        @manual-open="requestManualOpen"
        @reprint-receipt="reprintReceipt"
        @gate-open="onIdleGateOpen"
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
        :emoney-enabled="emoneyEnabled"
        :entry-snapshot-url="entrySnapshotUrl"
        :active-vehicle-type-name="activeVehicleTypeName"
        @manual-open="requestManualOpen"
        @reprint-receipt="reprintReceipt"
      />
    </template>

    <!-- Worker Check-In (blocking — no session active) -->
    <PosWorkerCheckInDialog
      v-if="showCheckInDialog"
      ref="checkInDialog"
      :gate-id="selectedGate?.id"
      :workers="workerSessionStore.workers"
      :is-loading="workerSessionStore.isLoading"
      @check-in="onCheckIn"
    />

    <!-- Worker Handover -->
    <PosWorkerHandoverDialog
      v-if="showHandoverDialog"
      ref="handoverDialog"
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

    <!-- Manual gate open (supervisor/admin password) -->
    <PosManualOpenDialog
      v-model:open="showManualOpen"
      :gate-name="selectedGate?.name || ''"
      :loading="manualOpenLoading"
      :error="manualOpenError"
      @confirm="submitManualOpen"
    />
  </NuxtLayout>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Button } from '~/components/ui/button'
import { useKeyboard } from '~/composables/useKeyboard'
import { useFormatters } from '~/composables/useFormatters'

definePageMeta({
  middleware: 'auth',
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

// Selected exit lane — declared before any watched computed so the initial
// watch evaluation does not hit a temporal-dead-zone ReferenceError.
const selectedGate = computed(() =>
  websiteStore.activeGateOuts.find((g) => g.id === gateStore.selectedGateOutId)
)

function reloadPage() {
  window.location.reload()
}

// Worker session state
const showHandoverDialog = ref(false)
const checkInDialog = ref(null)
const handoverDialog = ref(null)
let shiftEndTimer = null

// Stays mounted while check-in is in flight so a failure can show in the dialog.
const showCheckInDialog = computed(() =>
  !!selectedGate.value && !workerSessionStore.activeSession
)

// The check-in dialog blocks the whole POS. If it's shown with an empty
// worker list (fetchWorkers failed at boot), the operator is stranded with
// "contact your admin" and no retry — re-fetch every 15s while shown.
watch(showCheckInDialog, (shown) => {
  if (!shown) return
  const timer = setInterval(async () => {
    if (!showCheckInDialog.value || workerSessionStore.workers.length) {
      clearInterval(timer)
      return
    }
    await workerSessionStore.fetchWorkers()
  }, 15000)
})

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
const showManualOpen = ref(false)
const manualOpenLoading = ref(false)
const manualOpenError = ref('')
const boothPeripherals = ref({})
// Plate typed by the operator before scanning; kept for display after the
// ticket lookup replaces the idle form (cash tickets often have no plate).
const pendingPlate = ref('')
const emoneyBalance = ref(null)
const isPaymentProcessing = ref(false)
const lastEntry = ref(null)
const posRegistrationError = ref('')

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

watch(() => gateStore.entrySnapshot, (url) => {
  if (!url) return
  lastEntry.value = {
    plateNumber: gateStore.currentTransaction?.plate_number || '',
    snapshotUrl: url,
    gateLabel: selectedGate.value?.name || null,
    subtitle: 'baru saja masuk',
  }
})

onBeforeUnmount(() => {
  for (const timer of _disconnectTimers.values()) clearTimeout(timer)
  _disconnectTimers.clear()
})

const gatecameras = computed(() => {
  const hw = selectedGate.value?.hardware_config
  if (!hw) return []
  const list = hw.cameras || []
  if (list.length) {
    return list
      .filter((c) => (c.url || c.preview_url) && c.enabled !== false)
      .map((c) => ({ ...c, url: c.preview_url || c.url }))
  }
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

// Car exit lane: dropdown "2. Mobil" / "3. Box" (Mobil first = default).
const CAR_TYPE = /mobil|car|box/i
const carLaneOptions = computed(() => {
  if (isMixedLane.value) return []
  const defId = selectedGate.value?.hardware_config?.default_vehicle_type_id
  const def = websiteStore.vehicleTypes.find((t) => t.id === defId)
  if (!def || !CAR_TYPE.test(def.name)) return []
  return websiteStore.vehicleTypes
    .filter((t) => CAR_TYPE.test(t.name))
    .sort((a, b) => Number(/box/i.test(a.name)) - Number(/box/i.test(b.name)))
    .map((t, i) => ({ id: t.id, label: `${i + 2}. ${t.name}` }))
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
  if (!tx) pendingPlate.value = ''
  displayTariff.value = tx?.tariff || tx?.fee || 0
  if (isMixedLane.value) activeVehicleTypeId.value = tx?.vehicle_type_id ?? null
  // Fixed lane: every new ticket starts back at the lane default (Mobil).
  else activeVehicleTypeId.value = selectedGate.value?.hardware_config?.default_vehicle_type_id || null
  // Cash tickets have no plate — show the entry snapshot anyway (barcode as
  // the label). Previously the panel stayed on the live view for every cash
  // vehicle.
  if (tx?.entry_snapshot_id && (tx?.plate_number || tx?.barcode)) {
    lastEntry.value = {
      plateNumber: tx.plate_number || tx.barcode,
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

function selectVehicleTypeKey(key) {
  if (!gateStore.currentTransaction) {
    toast.warning('Pindai tiket terlebih dulu')
    return
  }
  const pattern = key === '1' ? /motor/i : /mobil|car|box|bus|truk/i
  const boxVt = key === '3' ? carLaneOptions.value.find((o) => /box/i.test(o.label)) : null
  const vt = boxVt
    ? { id: boxVt.id }
    : websiteStore.vehicleTypes.find((t) => pattern.test(t.name))
  if (!vt) {
    if (key === '3') toast.info('Box/Bus masuk kategori Mobil')
    return
  }
  if (key === '3' && !boxVt) toast.info('Box/Bus dihitung sebagai Mobil')
  onVehicleTypeChange(vt.id)
}

// Keyboard shortcuts
useKeyboard([
  { keys: ['F1'], action: () => {
    if (!emoneyEnabled.value) return // cash-only: Enter pays
    if (gateStore.canPayCash) payCash()
    else toast.warning('Bayar Cash belum tersedia — pindai tiket terlebih dulu')
  } },
  { keys: ['F2'], action: () => {
    if (!emoneyEnabled.value) return
    if (gateStore.canPayEmoney) startEmoneyPayment()
    else toast.warning('E-money belum tersedia — pindai tiket atau hubungkan booth bridge')
  } },
  { keys: ['F3'], action: () => {
    if (gateStore.canPayRfid) showRfidDialog.value = true
    else toast.warning('Bayar RFID belum tersedia — pindai tiket terlebih dulu')
  } }, // hidden fallback
  { keys: ['Enter'], action: () => quickCashEnter() },
  { keys: [' '], action: () => requestManualOpen() },
  { keys: ['F11'], action: () => requestManualOpen() },
  { keys: ['F12'], action: () => reprintReceipt() },
  { keys: ['Escape'], action: () => {
    showCashDialog.value = false
    showRfidDialog.value = false
    showManualOpen.value = false
  } },
  // Numeric keys: 1=MOTOR, 2=MOBIL, 3=BOX (own type when it exists, else Mobil).
  { keys: ['1'], action: () => selectVehicleTypeKey('1') },
  { keys: ['2'], action: () => selectVehicleTypeKey('2') },
  { keys: ['3'], action: () => selectVehicleTypeKey('3') },
], {
  // Suppress F-key/letter shortcuts while a modal owns input focus so they
  // don't hijack PIN/amount typing. Escape still passes through.
  isBlocked: () =>
    showCashDialog.value ||
    showRfidDialog.value ||
    showCheckInDialog.value ||
    showHandoverDialog.value ||
    showManualOpen.value,
})

// Actions
const entrySnapshotUrl = computed(() => {
  if (lastEntry.value?.snapshotUrl) return lastEntry.value.snapshotUrl
  const tx = gateStore.currentTransaction
  return tx?.entry_snapshot_id ? `/api/snapshots/${tx.entry_snapshot_id}/image` : null
})

// Per-booth plate field: 'prefix' (show, prefilled with the global city code),
// 'plain' (show, empty) or 'hidden'. Older booths only have ui.show_plate.
const plateMode = computed(() => {
  const ui = boothPeripherals.value?.ui || {}
  return ui.plate_mode || (ui.show_plate === false ? 'hidden' : 'prefix')
})

// Global city code prefix (server setting pos_plate_prefix, e.g. "H").
const platePrefix = computed(() => {
  if (plateMode.value !== 'prefix') return ''
  const raw = websiteStore.getSetting('pos_plate_prefix', '')
  return String(raw || '').trim().toUpperCase()
})

const showPlate = computed(() => plateMode.value !== 'hidden')

const emoneyEnabled = computed(() => {
  const raw = websiteStore.getSetting('emoney_enabled', 'true')
  return String(raw).toLowerCase() !== 'false'
})

async function onBarcodeLookup(input) {
  const v = input?.trim()
  if (!v) return

  // USB RFID readers are keyboard wedges: the card number lands in the barcode
  // box. Numeric card -> close the member transaction and open the exit gate
  // straight away (no lookup screen).
  if (/^\d{6,}$/.test(v)) {
    const cardTx = await gateStore.lookupTransaction({ cardNumber: v })
    if (cardTx) {
      await confirmRfidPayment(v)
      return
    }
  }

  const found = await gateStore.lookupTransaction({ barcode: v })
  if (!found) toast.warning('Transaksi tidak ditemukan untuk barcode tersebut')
}

function onPlateEntered(value) {
  pendingPlate.value = value
}

async function onPlateLookup(input) {
  const v = input?.trim().toUpperCase()
  if (!v) return
  const found = await gateStore.lookupTransaction({ plateNumber: v })
  if (!found) toast.warning(`Tidak ada transaksi aktif untuk plat ${v}`)
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
    return res.fee
  } catch (e) {
    console.error('Fee calculation failed:', e)
    return null
  }
}

// Setting cash_auto_open (default on): cash confirm opens the gate directly,
// no separate "Buka Palang" screen. Set to "false" to restore the two-step flow.
const cashAutoOpen = computed(() =>
  String(websiteStore.getSetting('cash_auto_open', 'true')).toLowerCase() !== 'false'
)

// Enter-to-pay (cash-only sites): exact fare, then auto-open.
const txLoadedAt = ref(0)
watch(() => gateStore.currentTransaction?.id, (id) => { txLoadedAt.value = id ? Date.now() : 0 })

function payExactCash() {
  if (!gateStore.currentTransaction || isPaymentProcessing.value) return
  if (isMixedLane.value && !activeVehicleTypeId.value) {
    toast.warning('Pilih jenis kendaraan dulu')
    return
  }
  // No amount sent: the server charges its own computed fee.
  confirmCashPayment(null)
}

// Cash button / F1: cash-only sites skip the amount dialog (no change counting,
// exact fare); sites with e-money keep the dialog.
function payCash() {
  if (emoneyEnabled.value) showCashDialog.value = true
  else payExactCash()
}

function quickCashEnter() {
  // Enter after a scan means "collect exact fare and open" — cash is the
  // default action even when an e-money reader exists; F1 keeps the dialog.
  if (!gateStore.canPayCash) return
  // Scanners type a trailing Enter right after the barcode; ignore it.
  if (Date.now() - txLoadedAt.value < 800) return
  payExactCash()
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
      plateNumber: pendingPlate.value || null,
      autoOpen: cashAutoOpen.value,
    })
    if (result?.success) {
      sound.paymentSuccess()
      posSession.addCashPayment(result.fee ?? (amount - (result.change_amount || 0)))
      if (cashAutoOpen.value) {
        const change = result.change_amount || 0
        toast.success(change > 0
          ? `Pembayaran berhasil. Kembalian Rp ${change.toLocaleString('id-ID')}`
          : 'Pembayaran berhasil')
        await openGateAction()
      } else {
        toast.success('Pembayaran berhasil. Tekan Space untuk buka palang.')
      }
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
      await openGateAction()
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
    transaction_id: armed.transaction_id,
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

function waitForBoothConnection(timeoutMs = 1500) {
  return new Promise((resolve) => {
    const started = Date.now()
    const tick = () => {
      if (gateStore.boothConnected && boothWs?.readyState === WebSocket.OPEN) return resolve(true)
      if (Date.now() - started >= timeoutMs) return resolve(false)
      setTimeout(tick, 100)
    }
    tick()
  })
}

async function openGateAction() {
  if (!selectedGate.value) return

  // Recover from a bridge restart: the socket may have dropped while the POS
  // was idle. Try one fresh connection before falling back to the API (which
  // refuses to fake an exit open).
  if (!gateStore.boothConnected || boothWs?.readyState !== WebSocket.OPEN) {
    connectBooth()
    if (!(await waitForBoothConnection(1500))) {
      toast.error('Booth bridge tidak terhubung — reload POS atau cek service booth-bridge-booth di PC kasir')
      return
    }
  }

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

  // No booth, no relay: the exit lane has no daemon, so this only records the
  // open. Never tell the operator the barrier moved.
  const result = await gateStore.openGate({ gateId: selectedGate.value.id })
  if (result?.success) {
    toast.warning('Booth offline. Palang tidak terbuka otomatis, buka secara manual.')
  } else {
    toast.error(result?.message || 'Gagal membuka palang')
  }
}

function onIdleGateOpen() {
  if (!gateStore.currentTransaction) {
    toast.warning('Pindai tiket atau ketik plat nomor dulu, lalu bayar di layar transaksi')
    return
  }
  if (gateStore.awaitingGateOpen) openGateAction()
  else toast.warning('Selesaikan pembayaran dulu untuk membuka palang')
}

function requestManualOpen() {
  // After a payment the giant "Buka Palang" button owns the action; elsewhere
  // the operator must authorise it with a supervisor/admin account.
  if (gateStore.awaitingGateOpen) {
    openGateAction()
    return
  }
  manualOpenError.value = ''
  showManualOpen.value = true
}

async function submitManualOpen({ username, password, reason }) {
  if (!selectedGate.value) return
  // Exit lanes are opened by the booth bridge on the cashier PC. Without that
  // websocket there is nothing to shoot the relay command at.
  if (!gateStore.boothConnected || !boothWs) {
    manualOpenError.value = 'Booth bridge tidak terhubung — palang tidak bisa dibuka dari POS ini.'
    return
  }
  manualOpenLoading.value = true
  manualOpenError.value = ''
  try {
    await fetchApi(`/api/gates/${selectedGate.value.id}/manual-open`, {
      method: 'POST',
      body: JSON.stringify({ username, password, reason }),
    })
    if (gateStore.boothConnected && boothWs) {
      boothWs.send(JSON.stringify({
        action: 'open_gate',
        gate_code: selectedGate.value.code,
      }))
      toast.success('Palang pintu dibuka (manual)')
    } else {
      toast.success('Otorisasi diterima — perintah buka dikirim')
    }
    gateStore.clearTransaction()
    showManualOpen.value = false
  } catch (err) {
    manualOpenError.value = err?.data?.detail || err?.message || 'Gagal otorisasi buka manual'
  } finally {
    manualOpenLoading.value = false
  }
}

async function reprintReceipt() {
  if (!selectedGate.value) return
  try {
    await fetchApi('/api/pos/reprint-receipt', {
      method: 'POST',
      body: JSON.stringify({ gate_id: selectedGate.value.id }),
    })
    toast.success('Struk terakhir dikirim ke printer')
  } catch (err) {
    toast.error(err?.data?.detail || err?.message || 'Gagal mencetak struk')
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
      // Never give up: the bridge can be restarted at any time. Cap the delay
      // so recovery is quick once it is back.
      const delay = Math.min(2000 * Math.pow(2, Math.min(boothWsReconnectAttempts - 1, 3)), 10000)
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
          transactionId: data.transaction_id,
          cardNumber: data.card_number,
          deductAmount: data.deduct_amount,
          balanceBefore: data.balance_before,
          balanceAfter: data.balance_after,
          transactionCounter: data.transaction_counter,
          rawResponseHex: data.raw_response_hex,
          settlementPayloadHex: data.settlement_payload_hex,
          cardType: data.card_type,
          cardTypeCode: data.card_type_code,
          mid: data.mid,
          tid: data.tid,
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

function workerErrorText(err) {
  if (err.status === 401) return 'PIN salah — coba lagi atau minta admin reset PIN'
  const msg = err?.data?.detail || err.message || 'Gagal memproses'
  // Actionable hints for the two most common blockers.
  if (/shift aktif|No active shift/i.test(msg)) {
    return 'Belum ada shift aktif untuk jam ini. Minta admin membuat master Shift dan penugasan hari ini (Jadwal Shift).'
  }
  if (/Penugasan|assignment/i.test(msg)) {
    return 'Penugasan tidak cocok. Minta admin membuat penugasan hari ini untuk gate ini (Jadwal Shift → Penugasan).'
  }
  return msg
}

async function onCheckIn(payload) {
  try {
    await workerSessionStore.checkIn(payload)
    toast.success(`Selamat bertugas, ${workerSessionStore.currentWorker?.full_name || ''}!`)
  } catch (err) {
    checkInDialog.value?.setError(workerErrorText(err))
  }
}

async function onConfirmOutgoing(payload) {
  try {
    await workerSessionStore.confirmOutgoing(payload)
    handoverDialog.value?.advanceToPending()
  } catch (err) {
    handoverDialog.value?.setError(workerErrorText(err))
  }
}

async function onConfirmIncoming(payload) {
  try {
    await workerSessionStore.confirmIncoming(payload)
    showHandoverDialog.value = false
    scheduleShiftEndTimer()
    toast.success(`Serah terima berhasil. Selamat bertugas!`)
  } catch (err) {
    handoverDialog.value?.setError(workerErrorText(err))
  }
}

async function onForceLeave(payload) {
  try {
    await workerSessionStore.forceLeave(payload)
    showHandoverDialog.value = false
    toast.warning('Anda meninggalkan pos. Admin telah diberitahu.')
  } catch (err) {
    handoverDialog.value?.setError(workerErrorText(err))
  }
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
    boothPeripherals.value = pos.booth_peripherals || {}
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
    if (err.status === 404 && websiteStore.activeGateOuts.length !== 1) {
      // With zero or multiple exit lanes, guessing would let the operator
      // charge/open the wrong barrier. Block until the booth is registered.
      posRegistrationError.value = websiteStore.activeGateOuts.length === 0
        ? 'Belum ada gate keluar aktif. Aktifkan gate di Device → Gates.'
        : 'Daftarkan booth ini di Device → POS (kode booth dan IP komputer), lalu muat ulang halaman.'
      return
    }
  }

  if (!gateDetected && websiteStore.activeGateOuts.length !== 1) {
    posRegistrationError.value = websiteStore.activeGateOuts.length === 0
      ? 'Belum ada gate keluar aktif. Aktifkan gate di Device → Gates.'
      : 'Booth terdeteksi, tetapi gate default-nya tidak aktif. Periksa Device → POS / Gates.'
    return
  }

  // Single-lane fallback only: unambiguous and safe.
  if (!gateDetected && websiteStore.activeGateOuts.length === 1) {
    const fallbackGate = websiteStore.activeGateOuts[0]
    gateStore.setSelectedGateOutId(fallbackGate.id)
    onGateChange(fallbackGate.id)
    toast.warning(`POS belum terdaftar, memakai satu-satunya gate: ${fallbackGate.name}`)
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
