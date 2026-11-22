<template>
  <div class="flex h-full min-h-0 gap-4 p-4 overflow-hidden">
    <!-- Left: cashier form, vertical order like the old POS (v1) -->
    <div class="flex min-h-0 flex-1 flex-col">
      <!-- Slim clock header -->
      <div class="mb-2 flex items-baseline justify-between rounded-lg border border-border bg-surface px-4 py-1.5 shadow-brutal-sm">
        <div class="font-mono text-3xl font-semibold leading-none tabular-nums text-foreground">
          {{ clockHHMM }}
        </div>
        <div class="text-xs font-medium tracking-[0.18em] text-muted-foreground">
          {{ dayDateLabel }}
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <div v-if="showPlate" class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[-] NO. PLAT</label>
          <Input
            ref="plateInput"
            v-model="plateValue"
            data-plate-input
            :placeholder="platePlaceholder"
            class="h-10 rounded-md border-neutral-300 bg-white text-center font-mono text-base font-semibold tracking-wide text-neutral-900 placeholder:text-neutral-400"
            @keydown.enter="onPlateSubmit"
          />
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[+] NO. TIKET / KARTU</label>
          <Input
            ref="barcodeInput"
            v-model="barcodeValue"
            data-barcode-input
            placeholder="Scan barcode tiket…"
            class="h-10 rounded-md border-neutral-300 bg-white text-center font-mono text-base font-semibold tracking-wide text-neutral-900 placeholder:text-neutral-400"
            @keydown.enter="onBarcodeSubmit"
          />
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">[*] JENIS KENDARAAN</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-surface font-semibold text-foreground">
            {{ vehicleTypeName || '—' }}
          </div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">JAM MASUK</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-surface font-mono text-base font-semibold tabular-nums text-foreground">—</div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">JAM KELUAR</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-surface font-mono text-base font-semibold tabular-nums text-foreground">—</div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">DURASI PARKIR</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-surface font-mono text-base font-semibold tabular-nums text-foreground">—</div>
        </div>

        <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3">
          <label class="text-sm font-semibold tracking-wide text-foreground">TARIF</label>
          <div class="flex h-10 items-center justify-center rounded-md border border-border bg-white font-mono text-base font-semibold tabular-nums text-neutral-900">
            {{ tariffLabel }}
          </div>
        </div>
      </div>

      <div class="mt-3 flex flex-col gap-1.5">
        <button
          type="button"
          class="h-12 w-full rounded-lg bg-primary text-base font-semibold text-on-solid shadow-brutal transition-[filter] duration-150 hover:brightness-95"
          @click="$emit('gate-open')"
        >
          BUKA GATE
        </button>
      </div>
    </div>

    <!-- Right: live exit camera + last entry snapshot -->
    <aside class="flex min-h-0 w-full min-w-[340px] max-w-[620px] flex-shrink-0 basis-[42%] flex-col gap-2">
      <section class="flex min-h-0 flex-1 flex-col">
        <div
          class="mb-1 flex items-center justify-between text-xs font-medium text-muted-foreground"
        >
          <span>Live Exit</span>
          <span v-if="exitCameraLabel" class="text-muted-foreground">{{ exitCameraLabel }}</span>
        </div>
        <div class="min-h-0 flex-1">
          <CameraColumn :cameras="exitCameras" :placeholder-count="1" fill />
        </div>
      </section>

      <section class="flex min-h-0 flex-1 flex-col">
        <div
          class="mb-1 flex items-center justify-between text-xs font-medium text-muted-foreground"
        >
          <span>Snapshot Masuk</span>
          <span v-if="lastEntry?.gateLabel" class="text-muted-foreground">
            {{ lastEntry.gateLabel }}
          </span>
        </div>
        <div class="min-h-0 flex-1 overflow-hidden rounded-lg border border-border bg-muted/40">
          <img
            v-if="lastEntry?.snapshotUrl"
            :src="lastEntry.snapshotUrl"
            :alt="lastEntry.plateNumber || 'snapshot masuk'"
            class="h-full w-full object-cover"
          >
          <div
            v-else
            class="flex h-full min-h-[120px] w-full flex-col items-center justify-center gap-1 text-muted-foreground"
          >
            <Car class="h-8 w-8" />
            <span class="text-xs font-medium">Belum ada masuk</span>
          </div>
        </div>
        <div
          v-if="lastEntry?.plateNumber"
          class="mt-2 flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2 shadow-brutal-sm"
        >
          <div>
            <div class="font-mono text-sm font-semibold tracking-wide text-foreground">
              {{ lastEntry.plateNumber }}
            </div>
            <div class="text-xs text-muted-foreground">
              {{ lastEntry.subtitle || 'baru saja masuk' }}
            </div>
          </div>
          <div v-if="lastEntry.ageLabel" class="text-xs font-medium tabular-nums text-muted-foreground">
            {{ lastEntry.ageLabel }}
          </div>
        </div>
      </section>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Car } from 'lucide-vue-next'
import { Input } from '~/components/ui/input'
import CameraColumn from './CameraColumn.vue'

const props = defineProps({
  cameras: { type: Array, default: () => [] },
  shiftName: { type: String, default: '' },
  transactionCount: { type: Number, default: 0 },
  cashCollected: { type: Number, default: 0 },
  lastEntry: { type: Object, default: null },
  showPlate: { type: Boolean, default: true },
  platePrefix: { type: String, default: '' },
  tariff: { type: Number, default: null },
  vehicleTypeName: { type: String, default: '' },
})

const emit = defineEmits(['barcode-lookup', 'plate-lookup', 'plate-entered', 'manual-open', 'reprint-receipt', 'gate-open'])

const barcodeInput = ref(null)
const barcodeValue = ref('')
const plateInput = ref(null)
const plateValue = ref('')

const platePlaceholder = computed(() =>
  props.platePrefix ? `${props.platePrefix}••••••` : 'Ketik plat nomor…',
)

const tariffLabel = computed(() => {
  if (props.tariff === null || props.tariff === undefined) return '—'
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0,
  }).format(props.tariff)
})

function applyPlatePrefix() {
  plateValue.value = props.platePrefix ? `${props.platePrefix} ` : ''
}

watch(() => props.platePrefix, applyPlatePrefix)
watch(() => props.showPlate, applyPlatePrefix)

function onBarcodeSubmit() {
  const v = barcodeValue.value.trim().toUpperCase()
  if (!v) return
  emit('barcode-lookup', v)
  barcodeValue.value = ''
}

function onPlateSubmit() {
  // Plate is informational only — the transaction is always found by barcode
  // or member card. Enter just moves the operator to the ticket field; looking
  // up by plate produced false "tidak ditemukan" errors.
  const raw = plateValue.value.trim()
  const v = raw.toUpperCase()

  // The member RFID reader on the cashier PC is a USB keyboard wedge: the card
  // number is typed wherever focus is. Since the plate row owns focus on this
  // screen, treat 6+ digits as a card tap instead of a plate.
  if (/^\d{6,}$/.test(raw)) {
    emit('barcode-lookup', raw)
    plateValue.value = ''
    focusBarcode()
    return
  }

  if (v) emit('plate-entered', v)
  focusBarcode()
}

function resolveInputEl(elRef) {
  const r = elRef
  const el = r?.$el ?? r
  return el?.querySelector?.('input') ?? (el?.tagName === 'INPUT' ? el : null)
}

function focusBarcode() {
  nextTick(() => {
    resolveInputEl(barcodeInput.value)?.focus?.()
  })
}

// The plate field is the first row of the form, so it owns the cursor when the
// POS opens (and after an F5 reload). Enter there moves on to the ticket field.
function focusPlate() {
  nextTick(() => {
    const el = resolveInputEl(plateInput.value)
    if (el) el.focus?.()
    else resolveInputEl(barcodeInput.value)?.focus?.()
  })
}

// Type anywhere on the idle screen → land in the barcode box (scanner pattern).
function onGlobalKeydown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return
  if (e.key.length !== 1) return
  const active = document.activeElement
  const tag = active?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active?.isContentEditable) return
  focusPlate()
}

const now = ref(new Date())
let tick = null

const DAY_NAMES = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu']
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

const clockHHMM = computed(() => {
  const d = now.value
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

const dayDateLabel = computed(() => {
  const d = now.value
  return `${DAY_NAMES[d.getDay()]} · ${d.getDate()} ${MONTH_NAMES[d.getMonth()]}`
})

const exitCameras = computed(() => props.cameras.slice(0, 1))
const exitCameraLabel = computed(() => exitCameras.value[0]?.label || null)

onMounted(() => {
  tick = setInterval(() => {
    now.value = new Date()
  }, 1000)
  applyPlatePrefix()
  // Focus after hydration/paint (Chrome may restore focus late), retry once.
  focusPlate()
  setTimeout(focusPlate, 250)
  setTimeout(() => {
    // Chrome may restore focus to whatever was focused before the reload
    // (usually the barcode box). Force the plate row unless a modal owns
    // focus (PIN/password dialog).
    if (document.querySelector('input[type=password]')) return
    focusPlate()
  }, 1200)
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  if (tick) clearInterval(tick)
  window.removeEventListener('keydown', onGlobalKeydown)
})

defineExpose({ focusBarcode, focusPlate })
</script>
