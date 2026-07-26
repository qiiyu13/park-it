<template>
  <div class="flex h-full min-h-0 gap-4 p-4 overflow-hidden">
    <!-- Left: ambient clock + waiting prompt -->
    <div class="relative flex flex-1 min-h-0 flex-col items-center justify-center">
      <div
        class="flex h-72 w-72 items-center justify-center border-4 border-foreground bg-surface shadow-brutal-lg"
      >
        <div class="text-center">
          <div
            class="font-mono text-7xl font-black leading-none tracking-tight tabular-nums text-foreground"
          >
            {{ clockHHMM }}
          </div>
          <div class="mt-3 text-xs font-black uppercase tracking-[0.25em] text-muted-foreground">
            {{ dayDateLabel }}
          </div>
        </div>
      </div>

      <div class="mt-12 w-full max-w-2xl">
        <Input
          ref="barcodeInput"
          v-model="barcodeValue"
          data-barcode-input
          placeholder="Scan barcode atau ketik nomor plat..."
          class="h-16 text-center font-mono text-2xl font-bold uppercase tracking-wider border-4 focus-visible:shadow-brutal-lg"
          @keydown.enter="onBarcodeSubmit"
        />
      </div>
    </div>

    <!-- Right: live exit camera + last entry snapshot -->
    <aside class="flex w-96 flex-shrink-0 flex-col gap-3 min-h-0">
      <section>
        <div
          class="mb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground"
        >
          <span>Live Exit</span>
          <span v-if="exitCameraLabel" class="text-muted-foreground/60">{{ exitCameraLabel }}</span>
        </div>
        <CameraColumn :cameras="exitCameras" :placeholder-count="1" />
      </section>

      <section>
        <div
          class="mb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground"
        >
          <span>Snapshot Masuk</span>
          <span v-if="lastEntry?.gateLabel" class="text-muted-foreground/60">
            {{ lastEntry.gateLabel }}
          </span>
        </div>
        <div
          class="w-full aspect-video overflow-hidden border-2 border-foreground bg-muted/10"
        >
          <img
            v-if="lastEntry?.snapshotUrl"
            :src="lastEntry.snapshotUrl"
            :alt="lastEntry.plateNumber || 'snapshot masuk'"
            class="h-full w-full object-cover"
          >
          <div
            v-else
            class="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-foreground/20"
          >
            <Car class="h-8 w-8" />
            <span class="text-[10px] font-bold">Belum ada masuk</span>
          </div>
        </div>
        <div
          v-if="lastEntry?.plateNumber"
          class="mt-2 flex items-center justify-between border-2 border-foreground bg-surface px-3 py-2 shadow-brutal-sm"
        >
          <div>
            <div class="font-mono text-sm font-black tracking-wider text-foreground">
              {{ lastEntry.plateNumber }}
            </div>
            <div class="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
              {{ lastEntry.subtitle || 'baru saja masuk' }}
            </div>
          </div>
          <div v-if="lastEntry.ageLabel" class="text-[10px] font-bold tabular-nums text-muted-foreground">
            {{ lastEntry.ageLabel }}
          </div>
        </div>
      </section>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Car } from 'lucide-vue-next'
import { Input } from '~/components/ui/input'
import CameraColumn from './CameraColumn.vue'

const props = defineProps({
  cameras: { type: Array, default: () => [] },
  shiftName: { type: String, default: '' },
  transactionCount: { type: Number, default: 0 },
  cashCollected: { type: Number, default: 0 },
  lastEntry: { type: Object, default: null },
})

const emit = defineEmits(['barcode-lookup'])

const barcodeInput = ref(null)
const barcodeValue = ref('')

function onBarcodeSubmit() {
  const v = barcodeValue.value.trim().toUpperCase()
  if (!v) return
  emit('barcode-lookup', v)
  barcodeValue.value = ''
}

function resolveInputEl() {
  const r = barcodeInput.value
  const el = r?.$el ?? r
  return el?.querySelector?.('input') ?? (el?.tagName === 'INPUT' ? el : null)
}

function focusBarcode() {
  nextTick(() => {
    resolveInputEl()?.focus?.()
  })
}

// Type anywhere on the idle screen → land in the barcode box (scanner pattern).
// Refocus when a printable key is pressed and focus isn't already in a field.
function onGlobalKeydown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return
  if (e.key.length !== 1) return
  const active = document.activeElement
  const tag = active?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active?.isContentEditable) return
  resolveInputEl()?.focus?.()
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
  focusBarcode()
  window.addEventListener('keydown', onGlobalKeydown)
})

defineExpose({ focusBarcode })

onBeforeUnmount(() => {
  if (tick) clearInterval(tick)
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>
