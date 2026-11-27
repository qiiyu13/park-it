<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center pos-modal-backdrop p-6" @keydown.esc.stop>
      <div class="pos-modal w-full max-w-3xl p-7">
        <!-- Header -->
        <div class="text-xs  tracking-[0.2em] pos-label text-muted-foreground">BLOCKING · SEBELUM TRANSAKSI</div>
        <h2 class="pos-display text-4xl mt-1 leading-none">Belum ada petugas</h2>
        <p class="pos-body text-sm text-muted-foreground mt-2">pilih nama Anda untuk mulai shift.</p>
        <div class="pos-divider my-4"/>

        <!-- Worker tiles -->
        <div class="text-[11px]  tracking-widest pos-label text-muted-foreground mb-2">PETUGAS</div>
        <div class="grid grid-cols-5 gap-2 mb-5">
          <button
            v-for="worker in workers"
            :key="worker.id"
            class="pos-choice px-3 py-3 text-left"
            :class="{ 'is-active': selectedWorker?.id === worker.id }"
            @click="pickWorker(worker)"
          >
            <div class="pos-display text-xl leading-none truncate">{{ worker.full_name || worker.username }}</div>
            <div class="text-xs pos-label text-muted-foreground truncate">{{ workerSub(worker) }}</div>
          </button>
          <div v-if="!workers.length" class="col-span-5 py-6 text-center pos-body text-sm text-muted-foreground">
            Tidak ada petugas aktif — tambahkan di menu Personil.
          </div>
        </div>

        <div v-if="errorMsg" class="pos-body text-sm text-destructive mb-4">{{ errorMsg }}</div>

        <!-- Substitute toggle -->
        <div class="flex items-center gap-3 mb-4">
          <label class="flex items-center gap-2 cursor-pointer pos-body text-sm">
            <input v-model="isSubstitute" type="checkbox" class="accent-[color:var(--color-foreground)]" >
            Saya menggantikan petugas lain
          </label>
          <select
            v-if="isSubstitute"
            v-model="originalWorkerId"
            class="pos-input px-3 py-1 pos-body text-sm"
          >
            <option :value="null">— pilih petugas asli —</option>
            <option v-for="w in workers.filter(w => w.id !== selectedWorker?.id)" :key="w.id" :value="w.id">
              {{ w.full_name || w.username }}
            </option>
          </select>
        </div>

        <!-- Action -->
        <div class="flex items-center justify-end gap-2">
          <button
            class="pos-btn is-go"
            :disabled="!selectedWorker || isLoading"
            @click="submit"
          >
            <span class="pos-key mr-1 px-1.5 py-0">Enter</span>
            <span v-if="isLoading">Memproses...</span>
            <span v-else>MASUK SHIFT →</span>
          </button>
        </div>

        <!-- Bottom keyboard strip -->
        <div class="mt-6 flex items-center justify-between pt-3 border-t border-dashed border-border">
          <div class="flex items-center gap-3 pos-body text-xs text-muted-foreground">
            <span><span class="pos-key px-1.5 py-0">1–{{ Math.min(workers.length, 9) }}</span> Pilih petugas</span>
            <span><span class="pos-key px-1.5 py-0">Enter</span> Masuk Shift</span>
          </div>
          <div class="flex items-center gap-1 pos-body text-xs text-muted-foreground">
            <span class="inline-block w-2 h-2 rounded-full bg-destructive"/>
            Booth belum di check-in
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  gateId: { type: Number, required: true },
  workers: { type: Array, default: () => [] },
  isLoading: { type: Boolean, default: false },
})
const emit = defineEmits(['check-in'])

const selectedWorker = ref(null)
const errorMsg = ref('')
const isSubstitute = ref(false)
const originalWorkerId = ref(null)

function workerSub(w) {
  return w.shift_name || w.role || ''
}
function pickWorker(w) {
  selectedWorker.value = w
  errorMsg.value = ''
}

function onKey(e) {
  if (e.target?.tagName === 'SELECT') return
  if (/^[1-9]$/.test(e.key)) {
    const idx = parseInt(e.key, 10) - 1
    if (props.workers[idx]) {
      pickWorker(props.workers[idx])
      e.preventDefault()
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    submit()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function submit() {
  if (!selectedWorker.value || props.isLoading) return
  errorMsg.value = ''
  emit('check-in', {
    gateId: props.gateId,
    workerId: selectedWorker.value.id,
    isSubstitute: isSubstitute.value,
    originalWorkerId: isSubstitute.value ? originalWorkerId.value : null,
  })
}

defineExpose({ setError: (m) => { errorMsg.value = m } })
</script>
