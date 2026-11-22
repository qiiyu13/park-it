<template>
  <article
    class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm"
  >
    <header class="flex items-start justify-between gap-2">
      <div>
        <p class="font-mono text-xs font-medium text-muted-foreground">{{ gate.code }}</p>
        <h3 class="font-semibold tracking-tight text-foreground">{{ gate.name }}</h3>
      </div>
      <StatusPill :status="online ? 'online' : 'offline'" />
    </header>

    <p class="mt-1 text-xs text-muted-foreground">
      {{ protocolLabel }} · {{ connectionLabel }}
    </p>

    <div class="mt-3 space-y-1.5 text-xs">
      <div v-for="p in peripherals" :key="p.key" class="flex items-center justify-between">
        <span class="font-medium text-foreground">{{ p.label }}</span>
        <StatusPill :status="p.status" :label="p.detail" />
      </div>
    </div>

    <p class="mt-3 text-xs text-muted-foreground">
      Heartbeat:
      <span class="font-mono font-medium">{{ heartbeatLabel }}</span>
    </p>

    <div class="mt-3 flex flex-wrap gap-2">
      <Button variant="outline" size="sm" :disabled="testing" @click="$emit('test')">
        {{ testing ? 'Menguji…' : 'Test' }}
      </Button>
      <Button variant="outline" size="sm" @click="$emit('edit')">Edit</Button>
      <Button variant="outline" size="sm" @click="$emit('logs')">Log</Button>
      <Button
        v-if="gate.direction === 'IN' && !online"
        variant="outline"
        size="sm"
        @click="$emit('enable-daemon')"
      >
        Aktifkan
      </Button>
      <Button variant="ghost" size="sm" @click="$emit('open')">Buka Gate</Button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from '~/components/ui/button'
import StatusPill from '~/components/setup/StatusPill.vue'

const props = defineProps({
  gate: { type: Object, required: true },
  testing: { type: Boolean, default: false },
  booths: { type: Array, default: () => [] },
})

defineEmits(['test', 'edit', 'open', 'logs', 'enable-daemon'])

const online = computed(() => !!props.gate.is_online)

const protocolLabel = computed(() => {
  const m = { compass: 'Compass', enet: 'ENET', serial: 'Serial' }
  return m[props.gate.protocol] || props.gate.protocol || 'unknown'
})

const connectionLabel = computed(() => {
  const g = props.gate
  if (g.protocol === 'serial') return g.controller_device || 'device belum diatur'
  if (g.controller_host) return `${g.controller_host}:${g.controller_port || '?'}`
  return 'belum diatur'
})

const peripherals = computed(() => {
  const hc = props.gate.hardware_config || {}
  const rows = []
  if (hc.printer?.enabled || hc.printer_id) {
    rows.push({
      key: 'printer',
      label: 'Printer',
      status: hc.printer?.last_ok || hc.printer_id ? 'online' : 'idle',
      detail: hc.printer?.paper_pct != null ? `kertas ${hc.printer.paper_pct}%` : (hc.printer_id ? 'terpasang' : ''),
    })
  }
  if (hc.emoney?.enabled) {
    rows.push({
      key: 'emoney',
      label: 'E-Money',
      status: hc.emoney.last_ok ? 'online' : 'idle',
      detail: hc.emoney.last_init_ago_s != null ? `init ${hc.emoney.last_init_ago_s}s` : '',
    })
  }
  if (hc.rfid?.enabled) rows.push({ key: 'rfid', label: 'RFID', status: 'idle', detail: '' })
  const camCount = (hc.cameras && hc.cameras.length) || (hc.camera?.url ? 1 : 0)
  if (hc.camera?.enabled || camCount) {
    rows.push({
      key: 'camera',
      label: 'Kamera',
      status: camCount ? 'online' : 'idle',
      detail: camCount ? `${camCount} kamera` : 'no url',
    })
  }

  const barrier = barrierStatus.value
  rows.push({
    key: 'barrier',
    label: 'Gate Barrier',
    status: barrier.status,
    detail: barrier.detail,
  })
  return rows
})

// Exit barrier lives on the booth relay, not on this server. Show the booth's
// live relay status so a missing relay is visible without opening Edit Gate.
const barrierStatus = computed(() => {
  const gate = props.gate
  if (gate.direction === 'OUT' && gate.protocol === 'serial') {
    if (!gate.pos_id) return { status: 'idle', detail: 'belum terpasang' }
    const booth = props.booths.find((b) => b.id === gate.pos_id)
    if (!booth) return { status: 'idle', detail: 'booth tidak ditemukan' }
    const seen = booth.last_seen_at ? new Date(booth.last_seen_at).getTime() : 0
    const fresh = seen > 0 && Date.now() - seen < 90_000
    const connected = fresh && !!booth.last_status?.gate_connected
    return connected
      ? { status: 'online', detail: `via ${booth.code}` }
      : { status: 'offline', detail: `booth ${fresh ? 'relay tidak ada' : 'offline'}` }
  }
  const ok = gate.controller_ok ?? gate.is_online
  return ok
    ? { status: 'online', detail: 'controller' }
    : { status: 'offline', detail: 'controller' }
})

const heartbeatLabel = computed(() => {
  if (!props.gate.last_heartbeat) return '—'
  return new Date(props.gate.last_heartbeat).toLocaleTimeString('id-ID')
})
</script>
