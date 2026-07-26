<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center sketch-backdrop p-6">
      <div class="sketch-box w-full max-w-3xl p-7">

        <!-- Header -->
        <div class="flex items-baseline justify-between">
          <div>
            <div class="text-xs uppercase tracking-[0.2em] font-hand-tight text-sketch-muted">MULTI-STEP · SERAH TERIMA</div>
            <h2 class="font-hand text-4xl mt-1 leading-none">{{ stepTitle }}</h2>
          </div>
          <div class="text-xs font-hand-body text-sketch-muted text-right max-w-[220px]">
            Esc untuk batal · transaksi yang berjalan ditunda
          </div>
        </div>

        <!-- Stepper -->
        <div class="flex items-center gap-3 my-5">
          <div class="flex items-center gap-2">
            <span class="sketch-stepper-dot" :class="stepClass(0)">{{ stepIdx > 0 ? '✓' : '1' }}</span>
            <span class="font-hand-tight text-sm" :class="stepIdx === 0 ? '' : 'text-sketch-muted'">Petugas keluar</span>
          </div>
          <span class="flex-1 h-px border-t border-dashed border-[color:var(--color-sketch-ink)]/50"/>
          <div class="flex items-center gap-2">
            <span class="sketch-stepper-dot" :class="stepClass(1)">{{ stepIdx > 1 ? '✓' : '2' }}</span>
            <span class="font-hand-tight text-sm" :class="stepIdx === 1 ? '' : 'text-sketch-muted'">Petugas masuk</span>
          </div>
          <span class="flex-1 h-px border-t border-dashed border-[color:var(--color-sketch-ink)]/50"/>
          <div class="flex items-center gap-2">
            <span class="sketch-stepper-dot" :class="stepClass(2)">{{ stepIdx > 2 ? '✓' : '3' }}</span>
            <span class="font-hand-tight text-sm" :class="stepIdx === 2 ? '' : 'text-sketch-muted'">Konfirmasi tutup kas</span>
          </div>
        </div>

        <!-- Step 0: outgoing PIN -->
        <template v-if="internalStep === 'outgoing'">
          <div class="sketch-tile p-4 mb-4">
            <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted">PETUGAS AKTIF</div>
            <div class="font-hand text-2xl">{{ currentWorker?.full_name || currentWorker?.username }}</div>
          </div>
          <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-2">PIN ANDA</div>
          <div class="flex gap-2 mb-4">
            <div
v-for="i in 4" :key="i" class="sketch-pin-box"
              :class="{ 'is-filled': outgoingPin.length >= i, 'is-current': outgoingPin.length === i - 1 }">
              {{ outgoingPin[i - 1] ? '•' : (outgoingPin.length === i - 1 ? '|' : '') }}
            </div>
            <input
ref="outgoingPinInput" v-model="outgoingPin" type="password" inputmode="numeric"
              maxlength="4" class="sr-only" @keydown.enter="submitOutgoing" >
          </div>

          <div v-if="earlyLeave" class="mb-4">
            <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-1">ALASAN PERGI LEBIH AWAL</div>
            <input
v-model="endReason" type="text" maxlength="255" placeholder="Isi alasan..."
              class="sketch-input w-full px-3 py-2 font-hand-body" >
          </div>
        </template>

        <!-- Step 1: incoming worker + PIN -->
        <template v-else-if="internalStep === 'pending'">
          <div class="sketch-tile is-active p-3 mb-4">
            <div class="flex items-center gap-2">
              <span class="font-hand-tight text-xs uppercase tracking-widest">SUDAH SELESAI · LANGKAH 1</span>
              <span class="ml-auto text-sketch-accent-green">✓</span>
            </div>
            <div class="font-hand text-lg leading-tight">
              {{ currentWorker?.full_name || currentWorker?.username }} keluar shift · PIN diverifikasi
            </div>
            <div class="font-hand-body text-xs text-sketch-muted">tutup kas: Rp {{ formatRp(closingAmount) }} · {{ txCount }} transaksi</div>
          </div>

          <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-2">SIAPA YANG MASUK?</div>
          <div class="grid grid-cols-4 gap-2 mb-4">
            <button
              v-for="w in availableWorkers"
              :key="w.id"
              class="sketch-tile px-3 py-2.5 text-left"
              :class="{ 'is-active': incomingWorker?.id === w.id }"
              @click="incomingWorker = w; focusIncomingPin()"
            >
              <div class="font-hand text-lg leading-none truncate">{{ w.full_name || w.username }}</div>
              <div class="text-[10px] font-hand-tight text-sketch-muted truncate">{{ w.shift_name || w.role }}</div>
            </button>
            <div v-if="!availableWorkers.length" class="col-span-4 py-4 text-center font-hand-body text-sm text-sketch-muted">
              Tidak ada petugas lain tersedia.
            </div>
          </div>

          <div v-if="incomingWorker">
            <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-2">
              PIN {{ (incomingWorker.full_name || incomingWorker.username).toUpperCase() }}
            </div>
            <div class="flex gap-2 mb-4">
              <div
v-for="i in 4" :key="i" class="sketch-pin-box"
                :class="{ 'is-filled': incomingPin.length >= i, 'is-current': incomingPin.length === i - 1 }">
                {{ incomingPin[i - 1] ? '•' : (incomingPin.length === i - 1 ? '|' : '') }}
              </div>
              <input
ref="incomingPinInput" v-model="incomingPin" type="password" inputmode="numeric"
                maxlength="4" class="sr-only" @keydown.enter="submitIncoming" >
            </div>
          </div>
        </template>

        <!-- Step 2: force-leave -->
        <template v-else-if="internalStep === 'force'">
          <p class="font-hand-body text-sm mb-3 text-sketch-muted">
            Admin akan diberitahu. Pos dianggap tidak terjaga sampai petugas baru check-in.
          </p>
          <div class="mb-3">
            <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-1">ALASAN (WAJIB)</div>
            <input
v-model="forceLeaveReason" type="text" maxlength="255"
              placeholder="darurat keluarga, sakit mendadak..."
              class="sketch-input w-full px-3 py-2 font-hand-body" >
          </div>
          <div class="mb-4">
            <div class="text-[11px] uppercase tracking-widest font-hand-tight text-sketch-muted mb-1">KONFIRMASI PIN ANDA</div>
            <div class="flex gap-2">
              <div
v-for="i in 4" :key="i" class="sketch-pin-box"
                :class="{ 'is-filled': forcePin.length >= i, 'is-current': forcePin.length === i - 1 }">
                {{ forcePin[i - 1] ? '•' : (forcePin.length === i - 1 ? '|' : '') }}
              </div>
              <input
ref="forcePinInput" v-model="forcePin" type="password" inputmode="numeric"
                maxlength="4" class="sr-only" @keydown.enter="submitForceLeave" >
            </div>
          </div>
        </template>

        <!-- Error -->
        <div v-if="errorMsg" class="font-hand-body text-sm text-[color:var(--color-sketch-accent-red)] mb-3">
          {{ errorMsg }}
        </div>

        <!-- Footer actions -->
        <div class="flex items-center justify-between mt-4">
          <div class="font-hand-body text-xs text-sketch-muted italic max-w-md">
            <template v-if="internalStep === 'outgoing'">setelah langkah 1 → konfirmasi tutup kas oleh petugas masuk</template>
            <template v-else-if="internalStep === 'pending'">petugas pengganti harus konfirmasi sebelum Anda boleh meninggalkan pos</template>
            <template v-else>tindakan ini dicatat audit</template>
          </div>
          <div class="flex gap-2">
            <button v-if="internalStep === 'pending'" class="sketch-btn is-danger" @click="internalStep = 'force'">
              Terpaksa Pergi
            </button>
            <button class="sketch-btn" @click="$emit('cancel')">
              <span class="sketch-chip mr-1 px-1.5 py-0">Esc</span> Batal
            </button>
            <button
              v-if="internalStep === 'outgoing'"
              class="sketch-btn is-primary"
              :disabled="outgoingPin.length < 4 || isLoading"
              @click="submitOutgoing"
            >
              <span class="sketch-chip mr-1 px-1.5 py-0">Enter</span> LANJUT →
            </button>
            <button
              v-else-if="internalStep === 'pending'"
              class="sketch-btn is-go"
              :disabled="!incomingWorker || incomingPin.length < 4 || isLoading"
              @click="submitIncoming"
            >
              <span class="sketch-chip mr-1 px-1.5 py-0">Enter</span> SERAH TERIMA →
            </button>
            <button
              v-else
              class="sketch-btn is-danger"
              :disabled="forcePin.length < 4 || !forceLeaveReason.trim() || isLoading"
              @click="submitForceLeave"
            >
              <span class="sketch-chip mr-1 px-1.5 py-0">Enter</span> TINGGALKAN POS →
            </button>
          </div>
        </div>

        <!-- Bottom keyboard strip -->
        <div class="mt-6 flex items-center justify-between pt-3 border-t border-dashed border-[color:var(--color-sketch-ink)]/40">
          <div class="flex items-center gap-3 font-hand-body text-xs text-sketch-muted">
            <span><span class="sketch-chip px-1.5 py-0">1–9</span> Pilih petugas masuk</span>
            <span><span class="sketch-chip px-1.5 py-0">0–9</span> PIN</span>
            <span><span class="sketch-chip px-1.5 py-0">Enter</span> Lanjut</span>
            <span><span class="sketch-chip px-1.5 py-0">Esc</span> Batal</span>
          </div>
          <div class="flex items-center gap-1 font-hand-body text-xs text-sketch-muted">
            <span class="inline-block w-2 h-2 rounded-full bg-[color:var(--color-sketch-highlight)]"/>
            Serah-terima shift · langkah {{ stepIdx + 1 }} dari 3
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  sessionId: { type: Number, required: true },
  currentWorker: { type: Object, default: null },
  workers: { type: Array, default: () => [] },
  isLoading: { type: Boolean, default: false },
  initialStep: { type: String, default: 'outgoing' },
  earlyLeave: { type: Boolean, default: false },
  closingAmount: { type: Number, default: 0 },
  txCount: { type: Number, default: 0 },
})
const emit = defineEmits(['confirm-outgoing', 'confirm-incoming', 'force-leave', 'cancel'])

const internalStep = ref(props.initialStep)
const outgoingPin = ref('')
const endReason = ref('')
const incomingWorker = ref(null)
const incomingPin = ref('')
const forceLeaveReason = ref('')
const forcePin = ref('')
const errorMsg = ref('')

const outgoingPinInput = ref(null)
const incomingPinInput = ref(null)
const forcePinInput = ref(null)

const availableWorkers = computed(() =>
  props.workers.filter(w => w.id !== props.currentWorker?.id)
)
const stepIdx = computed(() => {
  if (internalStep.value === 'outgoing') return 0
  if (internalStep.value === 'pending') return 1
  if (internalStep.value === 'force') return 1
  return 2
})
const stepTitle = computed(() => {
  if (internalStep.value === 'outgoing') return 'Petugas keluar'
  if (internalStep.value === 'pending') return 'Petugas masuk'
  return 'Tinggalkan pos'
})

function stepClass(i) {
  if (stepIdx.value > i) return 'is-done'
  if (stepIdx.value === i) return 'is-active'
  return ''
}
function formatRp(v) {
  return Number(v || 0).toLocaleString('id-ID')
}
function focusIncomingPin() {
  incomingPin.value = ''
  nextTick(() => incomingPinInput.value?.focus())
}

watch(() => props.initialStep, (val) => { internalStep.value = val })
watch(internalStep, async (val) => {
  errorMsg.value = ''
  await nextTick()
  if (val === 'outgoing') outgoingPinInput.value?.focus()
  else if (val === 'pending') incomingPinInput.value?.focus()
  else if (val === 'force') forcePinInput.value?.focus()
})

function onKey(e) {
  if (internalStep.value === 'pending' && !incomingWorker.value && /^[1-9]$/.test(e.key)) {
    const idx = parseInt(e.key, 10) - 1
    if (availableWorkers.value[idx]) {
      incomingWorker.value = availableWorkers.value[idx]
      focusIncomingPin()
      e.preventDefault()
    }
  }
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  nextTick(() => outgoingPinInput.value?.focus())
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function submitOutgoing() {
  if (outgoingPin.value.length < 4 || props.isLoading) return
  errorMsg.value = ''
  try {
    await emit('confirm-outgoing', {
      sessionId: props.sessionId,
      pin: outgoingPin.value,
      endType: props.earlyLeave ? 'EARLY' : 'SCHEDULED',
      endReason: endReason.value || null,
    })
    internalStep.value = 'pending'
  } catch (err) {
    errorMsg.value = err.message || 'PIN salah'
    outgoingPin.value = ''
  }
}
async function submitIncoming() {
  if (!incomingWorker.value || incomingPin.value.length < 4 || props.isLoading) return
  errorMsg.value = ''
  try {
    await emit('confirm-incoming', {
      sessionId: props.sessionId,
      workerId: incomingWorker.value.id,
      pin: incomingPin.value,
    })
  } catch (err) {
    errorMsg.value = err.message || 'PIN salah'
    incomingPin.value = ''
  }
}
async function submitForceLeave() {
  if (forcePin.value.length < 4 || !forceLeaveReason.value.trim() || props.isLoading) return
  errorMsg.value = ''
  try {
    await emit('force-leave', {
      sessionId: props.sessionId,
      pin: forcePin.value,
      reason: forceLeaveReason.value.trim(),
    })
  } catch (err) {
    errorMsg.value = err.message || 'PIN salah'
    forcePin.value = ''
  }
}

defineExpose({ setError: (m) => { errorMsg.value = m } })
</script>
