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
})

defineEmits(['test', 'edit', 'open'])

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
  if (hc.printer?.enabled) {
    rows.push({
      key: 'printer',
      label: 'Pencetak',
      status: hc.printer.last_ok ? 'online' : 'idle',
      detail: hc.printer.paper_pct != null ? `kertas ${hc.printer.paper_pct}%` : '',
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
  if (hc.camera?.enabled) rows.push({ key: 'camera', label: 'Kamera', status: hc.camera.url ? 'online' : 'idle', detail: hc.camera.url ? 'RTSP' : 'no url' })
  return rows
})

const heartbeatLabel = computed(() => {
  if (!props.gate.last_heartbeat) return '—'
  return new Date(props.gate.last_heartbeat).toLocaleTimeString('id-ID')
})
</script>
