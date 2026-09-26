<template>
  <!-- IDLE: ambient clock view -->
  <PosIdleAmbient
    v-if="!hasTransaction"
    :cameras="cameras"
    :shift-name="shiftName"
    :transaction-count="transactionCount"
    :cash-collected="cashCollected"
    :last-entry="lastEntry"
    @barcode-lookup="(v) => $emit('barcode-lookup', v)"
  />

  <!-- ACTIVE: transaction layout (wireframe redesign) -->
  <div v-else class="flex h-full min-h-0 gap-4 p-4 overflow-hidden">
    <!-- Left: Main transaction stage -->
    <div class="flex flex-1 min-h-0 flex-col">
      <!-- Top row: meta (left) + scan-plat chip (right) -->
      <div class="flex items-start justify-between gap-4 flex-shrink-0">
        <div class="flex items-start gap-6">
          <div class="flex flex-col">
            <span class="h-4 text-[11px] font-black uppercase tracking-wider text-muted-foreground leading-none">Durasi</span>
            <span class="mt-1 flex h-9 items-center text-2xl font-black tabular-nums leading-none text-foreground">{{ formattedDuration || '--' }}</span>
          </div>
          <div class="flex flex-col">
            <span class="h-4 text-[11px] font-black uppercase tracking-wider text-muted-foreground leading-none">Masuk</span>
            <span class="mt-1 flex h-9 items-center text-2xl font-black tabular-nums leading-none text-foreground">{{ formattedEntryTime || '--' }}</span>
          </div>
          <div class="flex flex-col">
            <span class="h-4 text-[11px] font-black uppercase tracking-wider text-muted-foreground leading-none">Jenis</span>
            <div v-if="isMixedLane" class="mt-1 h-9">
              <select
                :value="activeVehicleTypeId || ''"
                class="h-9 border-2 border-foreground bg-surface px-2 text-base font-black uppercase text-foreground focus:outline-none focus:shadow-brutal-sm min-w-[96px]"
                @change="$emit('update:vehicle-type-id', $event.target.value ? Number($event.target.value) : null)"
              >
                <option value="">?</option>
                <option v-for="vt in vehicleTypes" :key="vt.id" :value="vt.id">{{ vt.name }}</option>
              </select>
            </div>
            <span v-else class="mt-1 flex h-9 items-center text-2xl font-black uppercase leading-none text-foreground">{{ vehicleTypeName || '--' }}</span>
          </div>
        </div>

      </div>

      <!-- Center: Plate + tariff stage -->
      <div class="flex flex-1 min-h-0 flex-col items-center justify-center gap-6">
        <div class="flex flex-col items-center w-full">
          <span class="text-xs font-black uppercase tracking-wider text-muted-foreground self-start ml-[10%]">Plat Nomor</span>
          <div class="font-mono text-[7rem] font-black tracking-wider leading-none text-foreground mt-2 border-b-4 border-foreground px-8 pb-2">
            {{ transaction.plate_number }}
          </div>
        </div>

        <!-- Tariff highlighted chip -->
        <div class="inline-flex items-center border-4 border-foreground bg-warning px-10 py-4 shadow-brutal">
          <span class="font-mono text-5xl font-black tabular-nums text-foreground">
            {{ formattedTariff }}
          </span>
        </div>

        <!-- Payment method choice: operator asks driver cash or e-money -->
        <div v-if="showPaymentChoice" class="grid w-full max-w-md grid-cols-2 gap-4">
          <PaymentButton
            icon="cash"
            label="Tunai"
            shortcut="F1"
            :disabled="!canPayCash"
            :processing="isProcessing"
            @click="$emit('pay-cash')"
          />
          <PaymentButton
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
          v-if="showEmoneyStatus"
          class="w-full max-w-md"
          :emoney-state="emoneyState"
          :card-info="cardInfo"
          :balance="balance"
          :has-card-number="!!transaction?.card_number"
          @retry="$emit('retry-emoney')"
          @cancel="$emit('cancel-emoney')"
        />
      </div>

      <!-- Bottom: Timeout progress -->
      <div v-if="showTimeout" class="flex-shrink-0 space-y-1.5">
        <div class="flex items-center justify-between text-xs">
          <span class="uppercase tracking-wider font-black text-muted-foreground">Timeout</span>
          <span :class="timeoutTextColor" class="font-mono tabular-nums font-black">
            {{ waitingSeconds }}s / {{ timeoutSeconds }}s
          </span>
        </div>
        <div class="h-3 w-full border-2 border-foreground bg-surface overflow-hidden">
          <div
            :class="['h-full transition-all duration-1000', timeoutBarColor]"
            :style="{ width: `${timeoutPercent}%` }"
          />
        </div>
      </div>
    </div>

    <!-- Right rail (matches idle aside structure for stable transition) -->
    <aside class="flex w-96 flex-shrink-0 flex-col gap-3 min-h-0">
      <section>
        <div class="mb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>Live Exit</span>
          <span v-if="liveExitCameras[0]?.label" class="text-muted-foreground/60">{{ liveExitCameras[0].label }}</span>
        </div>
        <CameraColumn :cameras="liveExitCameras" :placeholder-count="1" />
      </section>
      <section>
        <div class="mb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>Snapshot Masuk</span>
          <span v-if="entryCameras[0]?.label" class="text-muted-foreground/60">{{ entryCameras[0].label }}</span>
        </div>
        <CameraColumn :cameras="entryCameras" :placeholder-count="1" />
      </section>
    </aside>
  </div>
</template>

<script setup>
import { computed } from 'vue'
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
  timeoutSeconds: { type: Number, default: 120 },
  canPayCash: { type: Boolean, default: false },
  canPayEmoney: { type: Boolean, default: false },
  cardInfo: { type: Object, default: null },
  balance: { type: Number, default: null },
  awaitingGateOpen: { type: Boolean, default: false },
  isProcessing: { type: Boolean, default: false },
  isMixedLane: { type: Boolean, default: false },
  activeVehicleTypeId: { type: Number, default: null },
  activeTariff: { type: Number, default: null },
  shiftName: { type: String, default: '' },
  transactionCount: { type: Number, default: 0 },
  cashCollected: { type: Number, default: 0 },
  lastEntry: { type: Object, default: null },
})

defineEmits([
  'pay-cash',
  'pay-emoney',
  'retry-emoney',
  'cancel-emoney',
  'update:vehicle-type-id',
  'barcode-lookup',
])

const { formatCurrency, formatDuration, formatTime } = useFormatters()

const hasTransaction = computed(() => props.transaction !== null)

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
