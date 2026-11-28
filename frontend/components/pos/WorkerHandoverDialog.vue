<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center pos-modal-backdrop p-6">
      <div class="pos-modal w-full max-w-3xl p-7">

        <!-- Header -->
        <div class="flex items-baseline justify-between">
          <div>
            <div class="text-xs  tracking-[0.2em] pos-label text-muted-foreground">MULTI-STEP · SERAH TERIMA</div>
            <h2 class="pos-display text-4xl mt-1 leading-none">{{ stepTitle }}</h2>
          </div>
          <div class="text-xs pos-body text-muted-foreground text-right max-w-[220px]">
            Esc untuk batal · transaksi yang berjalan ditunda
          </div>
        </div>

        <!-- Stepper -->
        <div class="flex items-center gap-3 my-5">
          <div class="flex items-center gap-2">
            <span class="pos-step" :class="stepClass(0)">{{ stepIdx > 0 ? '✓' : '1' }}</span>
            <span class="pos-label text-sm" :class="stepIdx === 0 ? '' : 'text-muted-foreground'">Petugas keluar</span>
          </div>
          <span class="flex-1 h-px border-t border-dashed border-border"/>
          <div class="flex items-center gap-2">
            <span class="pos-step" :class="stepClass(1)">{{ stepIdx > 1 ? '✓' : '2' }}</span>
            <span class="pos-label text-sm" :class="stepIdx === 1 ? '' : 'text-muted-foreground'">Petugas masuk</span>
          </div>
          <span class="flex-1 h-px border-t border-dashed border-border"/>
          <div class="flex items-center gap-2">
            <span class="pos-step" :class="stepClass(2)">{{ stepIdx > 2 ? '✓' : '3' }}</span>
            <span class="pos-label text-sm" :class="stepIdx === 2 ? '' : 'text-muted-foreground'">Konfirmasi tutup kas</span>
          </div>
        </div>

        <!-- Step 0: outgoing -->
        <template v-if="internalStep === 'outgoing'">
          <div class="pos-choice p-4 mb-4">
            <div class="text-[11px]  tracking-widest pos-label text-muted-foreground">PETUGAS AKTIF</div>
            <div class="pos-display text-2xl">{{ currentWorker?.full_name || currentWorker?.username }}</div>
          </div>
          <div class="pos-choice p-4 mb-4">
            <div class="text-[11px]  tracking-widest pos-label text-muted-foreground">PENERIMAAN SHIFT INI</div>
            <template v-if="summary">
              <div class="mt-2 grid grid-cols-4 gap-3">
                <div v-for="m in methodRows" :key="m.label">
                  <div class="pos-body text-xs text-muted-foreground">{{ m.label }} ({{ m.count }})</div>
                  <div class="pos-display text-lg leading-tight">Rp {{ formatRp(m.amount) }}</div>
                </div>
              </div>
              <div class="mt-3 flex items-baseline justify-between border-t border-dashed border-border pt-2">
                <span class="pos-label text-sm">Uang tunai diserahkan</span>
                <span class="pos-display text-2xl">Rp {{ formatRp(summary.cash_amount) }}</span>
              </div>
              <div v-if="summary.penalty_amount" class="pos-body text-xs text-muted-foreground mt-1">
                termasuk denda karcis hilang Rp {{ formatRp(summary.penalty_amount) }} ({{ summary.penalty_count }})
              </div>
            </template>
            <div v-else class="pos-body text-sm text-muted-foreground mt-1">{{ summaryError || 'Menghitung…' }}</div>
          </div>

          <div v-if="earlyLeave" class="mb-4">
            <div class="text-[11px]  tracking-widest pos-label text-muted-foreground mb-1">ALASAN PERGI LEBIH AWAL</div>
            <input
v-model="endReason" type="text" maxlength="255" placeholder="Isi alasan..."
              class="pos-input w-full px-3 py-2 pos-body" >
          </div>
        </template>

        <!-- Step 1: incoming worker -->
        <template v-else-if="internalStep === 'pending'">
          <div class="pos-choice is-active p-3 mb-4">
            <div class="flex items-center gap-2">
              <span class="pos-label text-xs  tracking-widest">SUDAH SELESAI · LANGKAH 1</span>
              <span class="ml-auto text-success">✓</span>
            </div>
            <div class="pos-display text-lg leading-tight">
              {{ currentWorker?.full_name || currentWorker?.username }} keluar shift
            </div>
            <div v-if="summary" class="pos-body text-xs text-muted-foreground">tutup kas: Rp {{ formatRp(summary.cash_amount) }} tunai · {{ summary.total_count }} transaksi · slip laporan dicetak</div>
          </div>

          <div class="text-[11px]  tracking-widest pos-label text-muted-foreground mb-2">SIAPA YANG MASUK?</div>
          <div class="grid grid-cols-4 gap-2 mb-4">
            <button
              v-for="w in availableWorkers"
              :key="w.id"
              class="pos-choice px-3 py-2.5 text-left"
              :class="{ 'is-active': incomingWorker?.id === w.id }"
              @click="incomingWorker = w"
            >
              <div class="pos-display text-lg leading-none truncate">{{ w.full_name || w.username }}</div>
              <div class="text-xs pos-label text-muted-foreground truncate">{{ w.shift_name || w.role }}</div>
            </button>
            <div v-if="!availableWorkers.length" class="col-span-4 py-4 text-center pos-body text-sm text-muted-foreground">
              Tidak ada petugas lain tersedia.
            </div>
          </div>

        </template>

        <!-- Step 2: force-leave -->
        <template v-else-if="internalStep === 'force'">
          <p class="pos-body text-sm mb-3 text-muted-foreground">
            Admin akan diberitahu. Pos dianggap tidak terjaga sampai petugas baru check-in.
          </p>
          <div class="mb-3">
            <div class="text-[11px]  tracking-widest pos-label text-muted-foreground mb-1">ALASAN (WAJIB)</div>
            <input
v-model="forceLeaveReason" type="text" maxlength="255"
              placeholder="darurat keluarga, sakit mendadak..."
              class="pos-input w-full px-3 py-2 pos-body" >
          </div>
        </template>

        <!-- Error -->
        <div v-if="errorMsg" class="pos-body text-sm text-destructive mb-3">
          {{ errorMsg }}
        </div>

        <!-- Footer actions -->
        <div class="flex items-center justify-between mt-4">
          <div class="pos-body text-xs text-muted-foreground italic max-w-md">
            <template v-if="internalStep === 'outgoing'">setelah Lanjut, slip laporan penerimaan dicetak → serahkan uang ke petugas masuk</template>
            <template v-else-if="internalStep === 'pending'">petugas pengganti harus konfirmasi sebelum Anda boleh meninggalkan pos</template>
            <template v-else>tindakan ini dicatat audit</template>
          </div>
          <div class="flex gap-2">
            <button v-if="internalStep === 'pending'" class="pos-btn is-danger" @click="internalStep = 'force'">
              Terpaksa Pergi
            </button>
            <button class="pos-btn" @click="$emit('cancel')">
              <span class="pos-key mr-1 px-1.5 py-0">Esc</span> Batal
            </button>
            <button
              v-if="internalStep === 'outgoing'"
              class="pos-btn is-primary"
              :disabled="isLoading"
              @click="submitOutgoing"
            >
              <span class="pos-key mr-1 px-1.5 py-0">Enter</span> LANJUT →
            </button>
            <button
              v-else-if="internalStep === 'pending'"
              class="pos-btn is-go"
              :disabled="!incomingWorker || isLoading"
              @click="submitIncoming"
            >
              <span class="pos-key mr-1 px-1.5 py-0">Enter</span> SERAH TERIMA →
            </button>
            <button
              v-else
              class="pos-btn is-danger"
              :disabled="!forceLeaveReason.trim() || isLoading"
              @click="submitForceLeave"
            >
              <span class="pos-key mr-1 px-1.5 py-0">Enter</span> TINGGALKAN POS →
            </button>
          </div>
        </div>

        <!-- Bottom keyboard strip -->
        <div class="mt-6 flex items-center justify-between pt-3 border-t border-dashed border-border">
          <div class="flex items-center gap-3 pos-body text-xs text-muted-foreground">
            <span><span class="pos-key px-1.5 py-0">1–9</span> Pilih petugas masuk</span>
            <span><span class="pos-key px-1.5 py-0">Enter</span> Lanjut</span>
            <span><span class="pos-key px-1.5 py-0">Esc</span> Batal</span>
          </div>
          <div class="flex items-center gap-1 pos-body text-xs text-muted-foreground">
            <span class="inline-block w-2 h-2 rounded-full bg-warning"/>
            Serah-terima shift · langkah {{ stepIdx + 1 }} dari 3
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  sessionId: { type: Number, required: true },
  currentWorker: { type: Object, default: null },
  workers: { type: Array, default: () => [] },
  isLoading: { type: Boolean, default: false },
  initialStep: { type: String, default: 'outgoing' },
  earlyLeave: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm-outgoing', 'confirm-incoming', 'force-leave', 'cancel'])

const internalStep = ref(props.initialStep)
const endReason = ref('')
const incomingWorker = ref(null)
const forceLeaveReason = ref('')
const errorMsg = ref('')

// Takings for this session; the server closes the window at handover.
const { fetchApi } = useApi()
const summary = ref(null)
const summaryError = ref('')
async function loadSummary() {
  try {
    summary.value = await fetchApi(`/api/worker-sessions/${props.sessionId}/summary`)
    summaryError.value = ''
  } catch {
    summaryError.value = 'Ringkasan penerimaan tidak dapat dimuat'
  }
}
const methodRows = computed(() => {
  const by = summary.value?.by_method || {}
  const pick = (code) => by[code] || { count: 0, amount: 0 }
  return [
    { label: 'Tunai', ...pick('CASH') },
    { label: 'E-Money', ...pick('EMONEY') },
    { label: 'Member', ...pick('RFID_MEMBER') },
    { label: 'Total', count: summary.value.total_count, amount: summary.value.total_amount },
  ]
})

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

watch(() => props.initialStep, (val) => { internalStep.value = val })
watch(internalStep, () => { errorMsg.value = '' })

function onKey(e) {
  const typing = e.target?.tagName === 'INPUT'
  if (internalStep.value === 'pending' && !typing && /^[1-9]$/.test(e.key)) {
    const idx = parseInt(e.key, 10) - 1
    if (availableWorkers.value[idx]) {
      incomingWorker.value = availableWorkers.value[idx]
      e.preventDefault()
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (internalStep.value === 'outgoing') submitOutgoing()
    else if (internalStep.value === 'pending') submitIncoming()
    else submitForceLeave()
  }
}
onMounted(() => {
  loadSummary()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function submitOutgoing() {
  if (props.isLoading) return
  errorMsg.value = ''
  emit('confirm-outgoing', {
    sessionId: props.sessionId,
    endType: props.earlyLeave ? 'EARLY' : 'SCHEDULED',
    endReason: endReason.value || null,
  })
}
async function submitIncoming() {
  if (!incomingWorker.value || props.isLoading) return
  errorMsg.value = ''
  emit('confirm-incoming', {
    sessionId: props.sessionId,
    workerId: incomingWorker.value.id,
  })
}
async function submitForceLeave() {
  if (!forceLeaveReason.value.trim() || props.isLoading) return
  errorMsg.value = ''
  emit('force-leave', {
    sessionId: props.sessionId,
    reason: forceLeaveReason.value.trim(),
  })
}

defineExpose({
  setError: (m) => { errorMsg.value = m },
  // Emit can't report failure, so the parent advances only after the API succeeds.
  advanceToPending: () => { internalStep.value = 'pending'; loadSummary() },
})
</script>
