<template>
  <div>
    <h1 class="mb-4 text-xl font-semibold text-foreground">Monitor Gate Masuk</h1>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <div
        v-for="gate in websiteStore.activeGateIns"
        :key="gate.id"
        :class="[
          'rounded-lg border border-border bg-surface p-4 transition-all',
          gateCardClass(gate.code),
        ]"
      >
        <!-- Header -->
        <div class="mb-3 flex items-center justify-between">
          <span class="font-semibold text-foreground">{{ gate.name }}</span>
          <span
:class="[
            'rounded-full px-2 py-0.5 text-xs font-medium',
            stateTagClass(gate.code),
          ]">
            {{ gateStateLabel(gate.code) }}
          </span>
        </div>

        <!-- Status -->
        <div class="mb-3 space-y-2">
          <div class="flex items-center gap-2">
            <span
:class="[
              'h-2 w-2 rounded-full',
              wsConnected(gate.code) ? 'bg-green-500 animate-pulse' : 'bg-red-500',
            ]" />
            <span class="text-xs text-muted-foreground">
              {{ wsConnected(gate.code) ? 'Online' : 'Offline' }}
            </span>
            <span class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {{ gate.protocol?.toUpperCase() || 'N/A' }}
            </span>
          </div>

          <div class="text-base font-medium text-foreground">
            {{ stateLabel(gate.code) }}
          </div>
        </div>

        <!-- Stats -->
        <div class="border-t border-border pt-2 text-xs text-muted-foreground space-y-1">
          <div>Kendaraan masuk: <span class="font-mono text-foreground">{{ vehicleCount(gate.code) }}</span></div>
          <div v-if="lastCard(gate.code)">Kartu: <span class="font-mono text-foreground">{{ lastCard(gate.code) }}</span></div>
          <div v-if="lastEvent(gate.code)">Event: <span class="text-foreground">{{ lastEvent(gate.code) }}</span></div>
        </div>
      </div>

      <!-- Empty state -->
      <div
        v-if="websiteStore.activeGateIns.length === 0"
        class="col-span-full py-12 text-center text-muted-foreground"
      >
        Tidak ada gate masuk terdaftar
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive } from 'vue'

definePageMeta({ middleware: 'auth' })

const websiteStore = useWebsiteStore()
const { $ws } = useNuxtApp()

const gateStates = reactive({})
const vehicleCounts = reactive({})
const lastCards = reactive({})
const lastEvents = reactive({})

const stateLabels = {
  IDLE: 'Siap',
  VEHICLE_PRESENT: 'Kendaraan Datang',
  GATE_CLOSED: 'Gate Tertutup',
  WAITING_BUTTON: 'Menunggu Tiket',
  WAITING_CARD: 'Menunggu Kartu',
  VALIDATING: 'Memvalidasi',
  CHECKING_BALANCE: 'Cek Saldo',
  WAITING_PRINT_DECISION: 'Cetak Tiket?',
  PROCESSING: 'Memproses',
  OPENING: 'Gate Terbuka',
  ERROR: 'Error',
  TIMEOUT_ALERT: 'Timeout',
}

let unsubscribers = []

function stateLabel(code) {
  return stateLabels[gateStates[code]?.state] || gateStates[code]?.state || '\u2014'
}

function gateStateLabel(code) {
  const s = gateStates[code]?.state
  if (!s) return '\u2014'
  return stateLabels[s] || s
}

function wsConnected(code) {
  return $ws.isConnected(code)
}

function vehicleCount(code) {
  return vehicleCounts[code] || 0
}

function lastCard(code) {
  return lastCards[code] || null
}

function lastEvent(code) {
  return lastEvents[code] || null
}

function gateCardClass(code) {
  const s = gateStates[code]?.state
  if (s === 'OPENING') return 'border-l-4 border-l-green-500'
  if (s?.includes('WAITING') || s === 'VEHICLE_PRESENT' || s === 'PROCESSING') return 'border-l-4 border-l-primary'
  return ''
}

function stateTagClass(code) {
  const s = gateStates[code]?.state
  if (s === 'OPENING') return 'bg-green-500/10 text-green-500'
  if (s === 'ERROR' || s === 'TIMEOUT_ALERT') return 'bg-destructive/10 text-destructive'
  if (s?.includes('WAITING') || s === 'VEHICLE_PRESENT' || s === 'PROCESSING') return 'bg-primary/10 text-primary'
  return 'bg-muted text-muted-foreground'
}

function handleEvent(code, event) {
  const type = event.event_type || event.type

  if (type === 'heartbeat_state') {
    gateStates[code] = { state: event.state, ...event }
    return
  }

  const stateMap = {
    'vehicle_detected': 'VEHICLE_PRESENT',
    'gate_closed': 'GATE_CLOSED',
    'rfid_card_read': 'VALIDATING',
    'passti_card_tap': 'CHECKING_BALANCE',
    'ticket_button_pressed': 'PROCESSING',
    'gate_opened': 'OPENING',
    'vehicle_passed': 'IDLE',
    'timeout_alert': 'TIMEOUT_ALERT',
    'vehicle_left': 'IDLE',
  }

  if (stateMap[type]) {
    gateStates[code] = { state: stateMap[type], ...event }
  }

  lastEvents[code] = type

  if (type === 'vehicle_detected') {
    vehicleCounts[code] = (vehicleCounts[code] || 0) + 1
  } else if (type === 'rfid_card_read' || type === 'passti_card_tap') {
    lastCards[code] = event.card_number || event.card_type
  }
}

onMounted(async () => {
  await websiteStore.loadAll()

  for (const gate of websiteStore.activeGateIns) {
    const code = gate.code
    gateStates[code] = { state: 'IDLE' }
    vehicleCounts[code] = 0

    const unsub = $ws.on(code, (event) => handleEvent(code, event))
    unsubscribers.push(unsub)
  }
})

onUnmounted(() => {
  unsubscribers.forEach(fn => fn())
  unsubscribers = []
})
</script>
