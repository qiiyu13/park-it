<template>
  <Teleport to="body">
    <div v-if="open" data-pos-modal class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" @keydown.esc="close">
      <form class="w-full max-w-4xl rounded-xl border border-border bg-surface p-7 shadow-brutal-lg" @submit.prevent="onSubmit">
        <div class="text-xs font-semibold text-muted-foreground">Denda Tiket Parkir Hilang</div>
        <h2 class="mt-1 text-2xl font-semibold tracking-tight text-foreground">Karcis Hilang</h2>
        <p class="mt-1 text-sm text-muted-foreground">
          Periksa STNK dan identitas pengemudi, isi sesuai kartu identitas. Tercatat di audit.
        </p>

        <div class="mt-5 grid grid-cols-2 gap-6">
          <!-- Vehicle + fare (Compass karcis-hilang screen) -->
          <div class="flex flex-col gap-2">
            <div :class="row">
              <label :class="lbl">NO. PLAT</label>
              <input ref="plateInput" v-model="plate" :class="inp" class="font-mono uppercase" maxlength="20" @input="requote">
            </div>
            <div :class="row">
              <label :class="lbl">[1/2/3] JENIS</label>
              <select v-model="vehicleTypeId" :class="inp" @change="requote">
                <option v-for="vt in vehicleTypes" :key="vt.id" :value="vt.id">{{ vt.name }}</option>
              </select>
            </div>
            <div :class="row">
              <label :class="lbl">JAM MASUK</label>
              <input v-model="entryLocal" type="datetime-local" :class="inp" :disabled="matched" @change="requote">
            </div>
            <div v-if="gateIns.length > 1" :class="row">
              <label :class="lbl">GATE MASUK</label>
              <select v-model="gateInId" :class="inp" :disabled="matched">
                <option :value="null">—</option>
                <option v-for="g in gateIns" :key="g.id" :value="g.id">{{ g.name }}</option>
              </select>
            </div>
            <p v-if="matched" class="text-xs font-medium text-success">
              Plat ini tercatat masih di dalam — jam masuk asli dipakai.
            </p>
            <div :class="row" class="mt-2">
              <label :class="lbl">TARIF</label>
              <div :class="fare">{{ rp(quote?.tariff) }}</div>
            </div>
            <div :class="row">
              <label :class="lbl">TARIF + DENDA</label>
              <div :class="fare" class="text-xl">{{ rp(quote?.total) }}</div>
            </div>
          </div>

          <!-- Driver identity (Compass Denda Tiket Hilang form) -->
          <div class="flex flex-col gap-2">
            <div :class="row">
              <label :class="lbl">NAMA PENGEMUDI *</label>
              <input v-model="form.driver_name" :class="inp" maxlength="100">
            </div>
            <div :class="row">
              <label :class="lbl">NO. IDENTITAS *</label>
              <input v-model="form.id_number" :class="inp" class="font-mono" maxlength="50">
            </div>
            <div :class="row">
              <label :class="lbl">ALAMAT</label>
              <input v-model="form.address" :class="inp" maxlength="200">
            </div>
            <div :class="row">
              <label :class="lbl">RT / RW</label>
              <input v-model="form.rt_rw" :class="inp" maxlength="20" placeholder="001/003">
            </div>
            <div :class="row">
              <label :class="lbl">KEL / DESA</label>
              <input v-model="form.kelurahan" :class="inp" maxlength="100">
            </div>
            <div :class="row">
              <label :class="lbl">KECAMATAN</label>
              <input v-model="form.kecamatan" :class="inp" maxlength="100">
            </div>
            <div :class="row">
              <label :class="lbl">KAB / KOTA</label>
              <input v-model="form.city" :class="inp" maxlength="100">
            </div>
            <div :class="row">
              <label :class="lbl">KETERANGAN</label>
              <input v-model="form.notes" :class="inp" maxlength="255">
            </div>
          </div>
        </div>

        <p v-if="error" class="mt-3 text-sm font-medium text-destructive">{{ error }}</p>

        <div class="mt-6 flex items-center justify-end gap-2">
          <button type="button" class="pos-btn" @click="close"><span class="pos-key mr-1 px-1.5 py-0">Esc</span> Batal</button>
          <button type="submit" class="pos-btn pos-btn-primary" :disabled="!canSubmit">
            <span class="pos-key mr-1 px-1.5 py-0">Enter</span> {{ saving ? 'Menyimpan…' : 'Lanjut ke Pembayaran' }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  initialPlate: { type: String, default: '' },
  vehicleTypes: { type: Array, default: () => [] },
  gateIns: { type: Array, default: () => [] },
  defaultVehicleTypeId: { type: Number, default: null },
  gateOutId: { type: Number, default: null },
})
const emit = defineEmits(['update:open', 'created'])

const row = 'grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3'
const lbl = 'text-xs font-semibold tracking-wide text-foreground'
const inp = 'h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-primary disabled:opacity-60'
const fare = 'flex h-10 items-center justify-center rounded-md bg-destructive font-mono text-lg font-semibold tabular-nums text-white'

const { fetchApi } = useApi()
const plate = ref('')
const vehicleTypeId = ref(null)
const entryLocal = ref('')
const gateInId = ref(null)
const form = ref({})
const quote = ref(null)
const error = ref('')
const saving = ref(false)
const plateInput = ref(null)

const matched = computed(() => !!quote.value?.matched)
const canSubmit = computed(() =>
  !saving.value && plate.value.trim() && vehicleTypeId.value
  && form.value.driver_name?.trim() && form.value.id_number?.trim(),
)

function rp(v) {
  return v == null ? '—' : `Rp ${Number(v).toLocaleString('id-ID')}`
}
// datetime-local works in the booth PC's local time.
function toLocalInput(iso) {
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

let quoteTimer = null
function requote() {
  clearTimeout(quoteTimer)
  quoteTimer = setTimeout(loadQuote, 250)
}
async function loadQuote() {
  try {
    const res = await fetchApi('/api/lost-tickets/quote', {
      method: 'POST',
      body: JSON.stringify({
        plate_number: plate.value || null,
        vehicle_type_id: vehicleTypeId.value,
        entry_time: entryLocal.value ? new Date(entryLocal.value).toISOString() : null,
        gate_out_id: props.gateOutId,
      }),
    })
    quote.value = res
    if (res.matched) {
      entryLocal.value = toLocalInput(res.entry_time)
      gateInId.value = res.gate_in_id
    } else if (!entryLocal.value) {
      entryLocal.value = toLocalInput(res.default_entry_time)
    }
    error.value = ''
  } catch (e) {
    error.value = e?.data?.detail || e.message || 'Tarif tidak dapat dihitung'
  }
}

watch(() => props.open, async (open) => {
  if (!open) return
  plate.value = (props.initialPlate || '').toUpperCase()
  vehicleTypeId.value = props.defaultVehicleTypeId || props.vehicleTypes[0]?.id || null
  entryLocal.value = ''
  gateInId.value = props.gateIns.length === 1 ? props.gateIns[0].id : null
  form.value = { driver_name: '', id_number: '', address: '', rt_rw: '', kelurahan: '', kecamatan: '', city: '', notes: '' }
  quote.value = null
  error.value = ''
  await loadQuote()
  await nextTick()
  plateInput.value?.focus()
  plateInput.value?.select()
}, { immediate: true })

// 1/2/3 pick Motor/Mobil/Box like the POS, but never while typing in a field.
function onKey(e) {
  if (!props.open || ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target?.tagName)) return
  const pattern = { 1: /motor/i, 2: /mobil|car/i, 3: /box|bus|truk/i }[e.key]
  const vt = pattern && props.vehicleTypes.find((t) => pattern.test(t.name))
  if (vt) {
    vehicleTypeId.value = vt.id
    requote()
    e.preventDefault()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearTimeout(quoteTimer)
})

function close() {
  emit('update:open', false)
}

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  try {
    const res = await fetchApi('/api/lost-tickets', {
      method: 'POST',
      body: JSON.stringify({
        ...form.value,
        plate_number: plate.value,
        vehicle_type_id: vehicleTypeId.value,
        entry_time: entryLocal.value ? new Date(entryLocal.value).toISOString() : null,
        gate_in_id: gateInId.value,
        gate_out_id: props.gateOutId,
      }),
    })
    emit('created', { ...res, vehicleTypeId: vehicleTypeId.value, plate: plate.value.toUpperCase() })
    close()
  } catch (e) {
    error.value = e?.data?.detail || e.message || 'Gagal menyimpan karcis hilang'
  } finally {
    saving.value = false
  }
}
</script>
