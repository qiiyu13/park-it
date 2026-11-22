<template>
  <!-- IDLE: same cashier form, values stay empty until a ticket is scanned -->
  <PosIdleAmbient
    v-if="!hasTransaction"
    :cameras="cameras"
    :shift-name="shiftName"
    :transaction-count="transactionCount"
    :cash-collected="cashCollected"
    :last-entry="lastEntry"
    :show-plate="showPlate"
    :plate-prefix="platePrefix"
    :tariff="null"
    :vehicle-type-name="resolvedLaneVehicleTypeName"
    @barcode-lookup="(v) => $emit('barcode-lookup', v)"
    @plate-lookup="(v) => $emit('plate-lookup', v)"
    @manual-open="$emit('manual-open')"
    @reprint-receipt="$emit('reprint-receipt')"
    @gate-open="$emit('gate-open')"
  />

  <!-- ACTIVE: v1-style vertical rows: plat → tiket → jenis → jam → durasi → tarif -->
  <div v-else class="flex h-full min-h-0 gap-4 p-4 overflow-hidden">
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <div class="flex flex-col gap-1.5">
        <div v-if="showPlate" class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[-] NO. PLAT</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-neutral-300 bg-white font-mono text-base font-semibold tracking-wide text-neutral-900">
            {{ transaction.plate_number || fallbackPlate || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[+] NO. TIKET / KARTU</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-neutral-300 bg-white font-mono text-base font-semibold tracking-wide text-neutral-900">
            {{ transaction.barcode || transaction.card_number || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[*] JENIS KENDARAAN</label>
          <select
            v-if="!isMixedLane && laneVehicleTypeOptions.length > 1"
            :value="activeVehicleTypeId || ''"
            class="h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm font-semibold text-neutral-900 focus:border-primary focus:outline-none"
            @change="$emit('update:vehicle-type-id', Number($event.target.value))"
          >
            <option v-for="o in laneVehicleTypeOptions" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
          <select
            v-else-if="isMixedLane"
            :value="activeVehicleTypeId || ''"
            class="h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm font-semibold text-neutral-900 focus:border-primary focus:outline-none"
            @change="$emit('update:vehicle-type-id', $event.target.value ? Number($event.target.value) : null)"
          >
            <option value="">Pilih jenis…</option>
            <option v-for="vt in vehicleTypes" :key="vt.id" :value="vt.id">{{ vt.name }}</option>
          </select>
          <div v-else class="flex h-10 items-center justify-center rounded-md border border-neutral-300 bg-white font-semibold text-neutral-900">
            {{ vehicleTypeName || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">JAM MASUK</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-neutral-300 bg-white font-mono text-base font-semibold tabular-nums text-neutral-900">
            {{ formattedEntryTime || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">JAM KELUAR</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-neutral-300 bg-white font-mono text-base font-semibold tabular-nums text-neutral-900">
            {{ formattedExitTime || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">DURASI PARKIR</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-surface font-mono text-base font-semibold tabular-nums text-foreground">
            {{ formattedDuration || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">TARIF</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-primary/40 bg-primary/15 font-mono text-lg font-semibold tabular-nums text-foreground">
            {{ formattedTariff }}
          </div>
        </div>
      </div>

      <!-- Payment method choice: operator asks driver cash or e-money -->
      <div
        v-if="showPaymentChoice"
        :class="['mt-4 grid w-full gap-3', emoneyEnabled ? 'grid-cols-2' : 'grid-cols-1']"
      >
        <PaymentButton
          icon="cash"
          :label="emoneyEnabled ? 'Tunai' : 'Terima & Buka Palang'"
          :shortcut="emoneyEnabled ? 'F1' : 'Enter'"
          :disabled="!canPayCash"
          :processing="isProcessing"
          @click="$emit('pay-cash')"
        />
        <PaymentButton
          v-if="emoneyEnabled"
          icon="emoney"
          label="E-Money"
          shortcut="F2"
          :disabled="!canPayEmoney"
          :processing="isProcessing"
          @click="$emit('pay-emoney')"
        />
      </div>

      <!-- E-money inline status (when active) -->
      <EmoneyInlineStatus
        v-if="showEmoneyStatus && emoneyEnabled"
        class="mt-3 w-full"
        :emoney-state="emoneyState"
        :card-info="cardInfo"
        :balance="balance"
        :has-card-number="!!transaction?.card_number"
        @retry="$emit('retry-emoney')"
        @cancel="$emit('cancel-emoney')"
      />

      <!-- Timeout progress -->
      <div v-if="showTimeout" class="mt-3 flex-shrink-0 space-y-1.5">
        <div class="flex items-center justify-between text-xs">
          <span class="text-xs font-medium tracking-wider text-muted-foreground">Timeout</span>
          <span :class="timeoutTextColor" class="font-mono text-xs font-semibold tabular-nums">
            {{ waitingSeconds }}s / {{ timeoutSeconds }}s
          </span>
        </div>
        <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            :class="['h-full rounded-full transition-all duration-1000', timeoutBarColor]"
            :style="{ width: `${timeoutPercent}%` }"
          />
        </div>
      </div>

    </div>

    <!-- Right rail: maximised CCTV + entry snapshot -->
    <aside class="flex min-h-0 w-full min-w-[340px] max-w-[620px] flex-shrink-0 basis-[42%] flex-col gap-2">
      <section class="flex min-h-0 flex-1 flex-col">
        <div class="mb-1 flex items-center justify-between text-xs font-medium text-muted-foreground">
          <span>Live Exit</span>
          <span v-if="liveExitCameras[0]?.label" class="text-muted-foreground">{{ liveExitCameras[0].label }}</span>
        </div>
        <div class="min-h-0 flex-1">
          <CameraColumn :cameras="liveExitCameras" :placeholder-count="1" fill />
        </div>
      </section>
      <section class="flex min-h-0 flex-1 flex-col">
        <div class="mb-1 flex items-center justify-between text-xs font-medium text-muted-foreground">
          <span>Snapshot Masuk</span>
          <span v-if="entryCameras[0]?.label && !entrySnapshotUrl" class="text-muted-foreground">{{ entryCameras[0].label }}</span>
        </div>
        <div v-if="entrySnapshotUrl" class="min-h-0 flex-1 overflow-hidden rounded-lg border border-border/40 bg-black">
          <img :src="entrySnapshotUrl" alt="snapshot masuk" class="h-full w-full object-cover" >
        </div>
        <div v-else class="min-h-0 flex-1">
          <CameraColumn :cameras="entryCameras" :placeholder-count="1" fill />
        </div>
      </section>
    </aside>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useFormatters } from '~/composables/useFormatters'
import EmoneyInlineStatus from './EmoneyInlineStatus.vue'
import CameraColumn from './CameraColumn.vue'
import PosIdleAmbient from './PosIdleAmbient.vue'
import PaymentButton from './PaymentButton.vue'

const props = defineProps({
  transaction: { type: Object, default: null },
  cameras: { type: Array, default: () => [] },
  durationSeconds: { type: Number, default: 0 },
  waitingSeconds: { type: Number, default: 0 },
  paymentState: { type: String, default: 'IDLE' },
  emoneyState: { type: String, default: 'IDLE' },
  vehicleTypes: { type: Array, default: () => [] },
  laneVehicleTypeOptions: { type: Array, default: () => [] },
  timeoutSeconds: { type: Number, default: 120 },
  canPayCash: { type: Boolean, default: false },
  canPayEmoney: { type: Boolean, default: false },
  cardInfo: { type: Object, default: null },
  balance: { type: Number, default: null },
  awaitingGateOpen: { type: Boolean, default: false },
  isProcessing: { type: Boolean, default: false },
  isMixedLane: { type: Boolean, default: false },
  entrySnapshotUrl: { type: String, default: null },
  emoneyEnabled: { type: Boolean, default: true },
  activeVehicleTypeId: { type: Number, default: null },
  activeTariff: { type: Number, default: null },
  shiftName: { type: String, default: '' },
  transactionCount: { type: Number, default: 0 },
  cashCollected: { type: Number, default: 0 },
  lastEntry: { type: Object, default: null },
  showPlate: { type: Boolean, default: true },
  platePrefix: { type: String, default: '' },
  laneVehicleTypeName: { type: String, default: '' },
  fallbackPlate: { type: String, default: '' },
})

defineEmits([
  'pay-cash',
  'pay-emoney',
  'retry-emoney',
  'cancel-emoney',
  'update:vehicle-type-id',
  'barcode-lookup',
  'plate-lookup',
  'manual-open',
  'reprint-receipt',
  'gate-open',
])

const { formatCurrency, formatDuration, formatTime } = useFormatters()

const hasTransaction = computed(() => props.transaction !== null)

const resolvedLaneVehicleTypeName = computed(() => {
  const id = props.activeVehicleTypeId || props.transaction?.vehicle_type_id
  if (!id) return props.laneVehicleTypeName || ''
  return props.vehicleTypes.find((t) => t.id === id)?.name || props.laneVehicleTypeName || ''
})

const liveExitCameras = computed(() => {
  const exit = props.cameras.filter((c) => /exit|out|keluar/i.test(c.label || ''))
  return exit.length ? exit.slice(0, 1) : props.cameras.slice(0, 1)
})

const entryCameras = computed(() => {
  const entry = props.cameras.filter((c) => /entry|in|masuk/i.test(c.label || ''))
  if (entry.length) return entry.slice(0, 1)
  return props.cameras.slice(1, 2)
})

const formattedTariff = computed(() => {
  if (!hasTransaction.value) return 'Rp -----'
  const tariff = props.activeTariff ?? (props.transaction?.tariff || props.transaction?.fee || 0)
  return formatCurrency(tariff)
})

const formattedDuration = computed(() => {
  if (!hasTransaction.value) return null
  return formatDuration(props.durationSeconds)
})

const formattedEntryTime = computed(() => {
  if (!hasTransaction.value) return null
  return formatTime(props.transaction?.entry_time)
})

// Exit time is "now" until the transaction is completed.
const now = ref(new Date())
let clockTimer = null
onMounted(() => {
  clockTimer = setInterval(() => { now.value = new Date() }, 1000)
})
onBeforeUnmount(() => {
  if (clockTimer) clearInterval(clockTimer)
})

const formattedExitTime = computed(() => {
  if (!hasTransaction.value) return null
  if (props.transaction?.exit_time) return formatTime(props.transaction.exit_time)
  const d = now.value
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

const vehicleTypeName = computed(() => {
  if (!hasTransaction.value) return null
  const vtId = props.activeVehicleTypeId || props.transaction?.vehicle_type_id
  if (!vtId) return null
  const vt = props.vehicleTypes.find((t) => t.id === vtId)
  return vt?.name || props.transaction?.vehicle_type || null
})

const timeoutPercent = computed(() => {
  if (props.timeoutSeconds <= 0) return 0
  return Math.min(100, (props.waitingSeconds / props.timeoutSeconds) * 100)
})

const timeoutBarColor = computed(() => {
  if (timeoutPercent.value >= 90) return 'bg-destructive'
  if (timeoutPercent.value >= 70) return 'bg-warning'
  return 'bg-success'
})

const timeoutTextColor = computed(() => {
  if (timeoutPercent.value >= 90) return 'text-destructive'
  if (timeoutPercent.value >= 70) return 'text-warning'
  return 'text-success'
})

const showTimeout = computed(() =>
  hasTransaction.value &&
  (props.paymentState === 'WAITING_PAYMENT' || props.paymentState === 'TIMEOUT_ALERT'),
)

const showEmoneyStatus = computed(() =>
  hasTransaction.value && props.emoneyState !== 'IDLE',
)

// Operator chooses cash or e-money once tariff is shown, before driver pays.
// Hidden once an e-money attempt is underway or the gate is awaiting open.
const showPaymentChoice = computed(() =>
  hasTransaction.value &&
  props.emoneyState === 'IDLE' &&
  !props.awaitingGateOpen &&
  (props.paymentState === 'WAITING_PAYMENT' || props.paymentState === 'TIMEOUT_ALERT'),
)

</script>
