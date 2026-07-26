<template>
  <div class="space-y-2">
    <div v-if="type === 'serial'" class="flex flex-wrap items-end gap-2">
      <WizardField label="Device" class="flex-1 min-w-[220px]">
        <div class="flex gap-2">
          <select
            v-model="localDevice"
            class="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
            @change="emitUpdate"
          >
            <option value="">— pilih perangkat —</option>
            <option v-for="opt in candidates" :key="opt.port" :value="opt.port">
              {{ opt.port }} · {{ opt.chip || opt.vid_pid }}
            </option>
            <option value="__custom__">Lainnya…</option>
          </select>
          <Button
            type="button"
            variant="outline"
            size="sm"
            :disabled="detecting"
            @click="detect"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            {{ detecting ? 'Mencari…' : 'Deteksi' }}
          </Button>
        </div>
      </WizardField>

      <WizardField v-if="localDevice === '__custom__'" label="Path manual" class="w-44">
        <Input v-model="localCustomDevice" placeholder="/dev/ttyUSB0" @blur="emitUpdate" />
      </WizardField>

      <WizardField label="Baudrate" class="w-32">
        <select
          v-model.number="localBaudrate"
          class="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          @change="emitUpdate"
        >
          <option v-for="b in baudrates" :key="b" :value="b">{{ b }}</option>
        </select>
      </WizardField>

      <Button type="button" variant="outline" size="sm" :disabled="!hasDevice || testing" class="h-10" @click="runTest">
        {{ testing ? 'Menguji…' : 'Test' }}
      </Button>

      <Button
        v-if="canPin"
        type="button"
        variant="outline"
        size="sm"
        :disabled="pinning"
        class="h-10"
        @click="confirmPin"
      >
        {{ pinning ? 'Memasang…' : pinLabel }}
      </Button>

      <StatusPill v-if="testStatus" :status="testStatus" :label="testLabel" />
    </div>

    <p v-if="pinConfirmFor" class="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
      Pasang {{ pinConfirmFor }} sebagai <span class="font-mono">/dev/parking-{{ role }}</span>?
      Akan tulis aturan udev permanen.
      <button class="ml-2 underline" @click="doPin">Pasang</button>
      <button class="ml-2 underline" @click="pinConfirmFor = ''">Batal</button>
    </p>

    <div v-else class="flex flex-wrap items-end gap-2">
      <WizardField label="Host / IP" class="flex-1 min-w-[200px]">
        <div class="flex gap-2">
          <select
            v-if="scanCandidates.length"
            class="w-40 rounded-md border border-border bg-background px-2 py-2 text-xs font-mono"
            @change="(e) => { localHost = e.target.value; emitUpdate() }"
          >
            <option value="">— hasil scan —</option>
            <option v-for="c in scanCandidates" :key="c.host" :value="c.host">
              {{ c.host }}{{ c.confirmed ? ' ✓' : '' }} · {{ Math.round(c.latency_ms) }}ms
            </option>
          </select>
          <Input v-model="localHost" placeholder="192.168.1.100" class="flex-1" @blur="emitUpdate" />
        </div>
      </WizardField>
      <WizardField label="Port" class="w-28">
        <Input v-model.number="localPort" type="number" min="1" max="65535" @blur="emitUpdate" />
      </WizardField>
      <Button type="button" variant="outline" size="sm" :disabled="scanning" class="h-10" @click="scanLan">
        {{ scanning ? 'Memindai…' : 'Scan LAN' }}
      </Button>
      <Button type="button" variant="outline" size="sm" :disabled="!localHost || testing" class="h-10" @click="runTest">
        {{ testing ? 'Menguji…' : 'Test' }}
      </Button>
      <StatusPill v-if="testStatus" :status="testStatus" :label="testLabel" />
    </div>

    <p v-if="errorDetail" class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
      {{ errorDetail }}
    </p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import WizardField from '~/components/setup/WizardField.vue'
import StatusPill from '~/components/setup/StatusPill.vue'

const props = defineProps({
  type: { type: String, default: 'serial' }, // 'serial' | 'tcp'
  role: { type: String, default: '' },
  device: { type: String, default: '' },
  baudrate: { type: Number, default: 9600 },
  host: { type: String, default: '' },
  port: { type: Number, default: 0 },
})

const emit = defineEmits(['update:device', 'update:baudrate', 'update:host', 'update:port', 'write-udev'])

const { fetchApi } = useApi()
const baudrates = [9600, 19200, 38400, 57600, 115200]

const candidates = ref([])
const detecting = ref(false)
const testing = ref(false)
const pinning = ref(false)
const pinConfirmFor = ref('')
const testStatus = ref('')
const testLabel = ref('')
const errorDetail = ref('')
const scanning = ref(false)
const scanCandidates = ref([])

const localDevice = ref(props.device || '')
const localCustomDevice = ref(props.device && !candidates.value.find((c) => c.port === props.device) ? props.device : '')
const localBaudrate = ref(props.baudrate)
const localHost = ref(props.host)
const localPort = ref(props.port)

watch(() => props.device, (v) => { if (v !== localDevice.value) localDevice.value = v })
watch(() => props.baudrate, (v) => { if (v !== localBaudrate.value) localBaudrate.value = v })
watch(() => props.host, (v) => { if (v !== localHost.value) localHost.value = v })
watch(() => props.port, (v) => { if (v !== localPort.value) localPort.value = v })

const effectiveDevice = computed(() =>
  localDevice.value === '__custom__' ? localCustomDevice.value : localDevice.value,
)

const hasDevice = computed(() => !!effectiveDevice.value)

const isPinned = computed(() => (effectiveDevice.value || '').startsWith('/dev/parking-'))

const canPin = computed(() => props.type === 'serial' && !!props.role && hasDevice.value && !isPinned.value)

const pinLabel = computed(() => `Pasang /dev/parking-${props.role}`)

function emitUpdate() {
  if (props.type === 'serial') {
    emit('update:device', effectiveDevice.value)
    emit('update:baudrate', localBaudrate.value)
  } else {
    emit('update:host', localHost.value)
    emit('update:port', localPort.value)
  }
}

async function detect() {
  detecting.value = true
  errorDetail.value = ''
  try {
    const res = await fetchApi('/api/setup/detect-serial', { method: 'POST' })
    candidates.value = res.candidates || []
    // Pre-select a suggested-role match in the dropdown but DO NOT write
    // udev or commit any persistent change. Tech still has to click Test +
    // explicit "Pasang" to make the symlink permanent.
    const match = candidates.value.find((c) => c.suggested_role === props.role)
    if (match && !localDevice.value) {
      localDevice.value = match.port
      emitUpdate()
    }
  } catch (err) {
    errorDetail.value = `Gagal deteksi: ${err.message}`
  } finally {
    detecting.value = false
  }
}

function confirmPin() {
  if (!hasDevice.value) return
  pinConfirmFor.value = effectiveDevice.value
}

async function doPin() {
  const port = pinConfirmFor.value
  pinConfirmFor.value = ''
  if (!port || !props.role) return
  pinning.value = true
  errorDetail.value = ''
  try {
    const res = await fetchApi('/api/setup/write-udev', {
      method: 'POST',
      body: JSON.stringify({ role: props.role, port }),
    })
    if (res.ok && res.symlink) {
      localDevice.value = res.symlink
      emit('write-udev', res.symlink)
      emitUpdate()
    } else {
      errorDetail.value = res.error || 'Gagal pasang udev.'
    }
  } catch (err) {
    errorDetail.value = `Gagal pasang udev: ${err.message}`
  } finally {
    pinning.value = false
  }
}

async function scanLan() {
  scanning.value = true
  errorDetail.value = ''
  scanCandidates.value = []
  try {
    const octets = (localHost.value || '').split('.')
    const prefix = octets.length === 4 ? octets.slice(0, 3).join('.') : '192.168.1'
    const res = await fetchApi('/api/setup/discover-gates', {
      method: 'POST',
      body: JSON.stringify({ subnet: `${prefix}.0/24`, port: localPort.value || 5000 }),
    })
    scanCandidates.value = res.candidates || []
    if (!scanCandidates.value.length) {
      errorDetail.value = `Tidak ada controller ditemukan di ${prefix}.0/24 — cek kabel LAN atau isi IP manual.`
    }
  } catch (err) {
    errorDetail.value = `Gagal scan: ${err.message}`
  } finally {
    scanning.value = false
  }
}

async function runTest() {
  testing.value = true
  testStatus.value = 'testing'
  testLabel.value = 'Menguji…'
  errorDetail.value = ''
  try {
    const body =
      props.type === 'serial'
        ? { type: 'serial', device: effectiveDevice.value, baudrate: localBaudrate.value }
        : { type: 'tcp', host: localHost.value, port: localPort.value }
    const res = await fetchApi('/api/setup/test-device', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    if (res.ok) {
      testStatus.value = 'online'
      testLabel.value = res.latency_ms ? `${Math.round(res.latency_ms)}ms` : 'OK'
    } else {
      testStatus.value = 'offline'
      testLabel.value = 'Gagal'
      errorDetail.value = res.error || 'Tidak ada detail'
    }
  } catch (err) {
    testStatus.value = 'offline'
    testLabel.value = 'Gagal'
    errorDetail.value = err.message
  } finally {
    testing.value = false
  }
}
</script>
