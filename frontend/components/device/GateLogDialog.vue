<template>
  <Dialog :open="open" @update:open="(v) => { if (!v) emit('update:open', false) }">
    <DialogContent class="max-w-4xl">
      <DialogHeader>
        <DialogTitle>Log Perangkat — {{ gate?.code }}</DialogTitle>
      </DialogHeader>

      <div class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <label class="flex items-center gap-2">
          <input v-model="live" type="checkbox" class="accent-primary" >
          <span>Live (2 detik)</span>
        </label>
        <span>{{ entries.length }} baris</span>
        <span v-if="error" class="font-medium text-destructive">{{ error }}</span>
        <Button variant="outline" size="sm" class="ml-auto" @click="load">Muat ulang</Button>
      </div>

      <div
        ref="scrollBox"
        class="max-h-[55vh] overflow-auto rounded-md border border-border bg-black/90 p-3 font-mono text-[11px] leading-relaxed text-green-300"
      >
        <p v-if="!entries.length && !error" class="text-muted-foreground">Belum ada log…</p>
        <div v-for="(e, i) in entries" :key="i" class="whitespace-pre-wrap break-all">
          <span class="text-gray-400">{{ shortTime(e.ts) }}</span>
          <span :class="levelClass(e.level)"> {{ e.level }}</span>
          <span class="text-yellow-200"> {{ e.event }}</span>
          <span> {{ detailText(e.message) }}</span>
        </div>
      </div>

      <p class="text-[11px] text-muted-foreground">
        Log ini dari daemon lane (controller, tap kartu/RFID, relay, error). Untuk troubleshooting teknis.
      </p>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog'

const props = defineProps({
  open: { type: Boolean, default: false },
  gate: { type: Object, default: null },
})
const emit = defineEmits(['update:open'])

const entries = ref([])
const error = ref('')
const live = ref(true)
const scrollBox = ref(null)
let timer = null

function shortTime(ts) {
  if (!ts) return '--:--:--'
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? String(ts).slice(11, 19) : d.toLocaleTimeString('id-ID', { hour12: false })
}

function detailText(message) {
  if (message == null) return ''
  if (typeof message === 'string') return message
  try {
    return Object.entries(message)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
      .join('  ')
  } catch {
    return String(message)
  }
}

function levelClass(level) {
  return level === 'error' ? 'text-red-400' : level === 'warning' || level === 'warn' ? 'text-orange-300' : 'text-blue-300'
}

async function load() {
  if (!props.gate?.code) return
  try {
    error.value = ''
    const res = await fetch(`/api/gates/${encodeURIComponent(props.gate.code)}/logs?lines=300`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    entries.value = data.entries || []
    await nextTick()
    if (live.value && scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
  } catch (e) {
    error.value = e.message || 'gagal memuat log'
  }
}

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function start() {
  stop()
  timer = setInterval(() => { if (live.value) load() }, 2000)
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    load()
    start()
  } else {
    stop()
  }
})

onBeforeUnmount(stop)
</script>
