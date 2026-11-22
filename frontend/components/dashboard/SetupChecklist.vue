<template>
  <section class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-sm font-semibold text-foreground">Kelengkapan Setup</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          {{ doneCount }}/{{ items.length }} siap — yang merah bisa membuat POS/palang macet.
        </p>
      </div>
      <button
        class="text-xs font-medium text-info hover:underline"
        :disabled="loading"
        @click="load"
      >
        {{ loading ? 'Memuat…' : 'Muat ulang' }}
      </button>
    </div>

    <div class="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      <NuxtLink
        v-for="item in items"
        :key="item.key"
        :to="item.to"
        class="flex items-start gap-2 rounded-md border border-border px-3 py-2 transition-colors hover:bg-surface-hover"
      >
        <span
          :class="['mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full', item.ok ? 'bg-success' : 'bg-destructive']"
        />
        <span class="min-w-0">
          <span class="block text-sm font-medium text-foreground">{{ item.label }}</span>
          <span class="block truncate text-xs text-muted-foreground">{{ item.ok ? item.okText : item.hint }}</span>
        </span>
      </NuxtLink>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

const { fetchApi } = useApi()
const loading = ref(true)
const state = ref({
  shifts: [],
  workers: [],
  assignments: [],
  gates: [],
  booths: [],
  printers: [],
  cameras: [],
  vehicleTypes: [],
})

function today() {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

async function load() {
  loading.value = true
  try {
    const safe = (p) => fetchApi(p).catch(() => [])
    const [shifts, workers, assignments, gates, booths, printers, cameras, vehicleTypes] = await Promise.all([
      safe('/api/shifts'),
      safe('/api/users/workers'),
      safe(`/api/shift-assignments?date_filter=${today()}`),
      safe('/api/gates'),
      safe('/api/pos'),
      safe('/api/printers/'),
      safe('/api/cameras'),
      safe('/api/vehicle-types'),
    ])
    state.value = {
      shifts: shifts || [],
      workers: workers || [],
      assignments: assignments || [],
      gates: gates || [],
      booths: booths || [],
      printers: printers || [],
      cameras: cameras || [],
      vehicleTypes: vehicleTypes || [],
    }
  } finally {
    loading.value = false
  }
}

const items = computed(() => {
  const s = state.value
  const workersWithPin = s.workers.filter((w) => w.worker_pin)
  const gatesWithController = s.gates.filter(
    (g) => g.controller_host || g.controller_device
  )
  return [
    {
      key: 'shifts',
      label: 'Master Shift',
      ok: s.shifts.length > 0,
      okText: `${s.shifts.length} shift`,
      hint: 'Buat shift dulu (Pagi/Siang/Malam)',
      to: '/shifts-schedule',
    },
    {
      key: 'personnel',
      label: 'Petugas + PIN',
      ok: workersWithPin.length > 0,
      okText: `${workersWithPin.length} petugas siap`,
      hint: 'Tambah personil dan set PIN 4 digit',
      to: '/personnel',
    },
    {
      key: 'assignments',
      label: 'Penugasan hari ini',
      ok: s.assignments.length > 0,
      okText: `${s.assignments.length} penugasan`,
      hint: 'Belum ada jadwal hari ini — POS tidak bisa check-in',
      to: '/shifts-schedule',
    },
    {
      key: 'gates',
      label: 'Gate + controller',
      ok: gatesWithController.length > 0,
      okText: `${gatesWithController.length} gate terhubung`,
      hint: 'Isi host/port controller atau device serial',
      to: '/device',
    },
    {
      key: 'booths',
      label: 'Booth POS',
      ok: s.booths.length > 0,
      okText: `${s.booths.length} booth`,
      hint: 'Daftarkan booth + gate default',
      to: '/device',
    },
    {
      key: 'printers',
      label: 'Printer tiket',
      ok: s.printers.length > 0,
      okText: `${s.printers.length} printer`,
      hint: 'Tambah printer (mode Otomatis)',
      to: '/device',
    },
    {
      key: 'cameras',
      label: 'Kamera',
      ok: s.cameras.length > 0,
      okText: `${s.cameras.length} kamera`,
      hint: 'Daftarkan URL RTSP kamera',
      to: '/device',
    },
    {
      key: 'tariff',
      label: 'Tarif kendaraan',
      ok: s.vehicleTypes.length > 0,
      okText: `${s.vehicleTypes.length} jenis`,
      hint: 'Atur tarif motor/mobil',
      to: '/setting',
    },
  ]
})

const doneCount = computed(() => items.value.filter((i) => i.ok).length)

onMounted(load)
</script>
