<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" tabindex="-1" @keydown.esc="close">
      <div class="w-full max-w-3xl rounded-xl border border-border bg-surface p-7 shadow-brutal-lg">
        <!-- Header -->
        <div class="flex items-baseline justify-between mb-1">
          <div />
          <div class="text-xs font-semibold text-muted-foreground">F1 dari layar utama</div>
        </div>
        <h2 class="text-4xl font-semibold tracking-tight mb-5 leading-none text-foreground">Bayar Tunai</h2>

        <!-- Three tiles: Tagihan / Diterima / Kembali -->
        <div class="grid grid-cols-3 gap-4 mb-6">
          <div class="rounded-lg border border-border bg-background p-4">
            <div class="text-xs font-semibold text-muted-foreground mb-1">Tagihan</div>
            <div class="text-3xl font-semibold tabular-nums text-foreground">{{ formatRp(tariff) }}</div>
          </div>
          <div class="rounded-lg border border-primary/40 bg-primary/15 p-4">
            <div class="text-xs font-semibold text-foreground mb-1">Diterima</div>
            <input
              ref="amountInput"
              v-model.number="paidAmount"
              type="number"
              :min="0"
              class="w-full bg-transparent outline-none text-3xl font-semibold tabular-nums text-foreground"
              placeholder="0"
              @keydown.enter.prevent="onConfirm"
              @keydown.esc.prevent="close"
            >
            <div class="text-xs font-medium text-foreground/70 mt-1">ketik nominal · enter untuk lanjut</div>
          </div>
          <div class="rounded-lg border border-border bg-background p-4" :class="{ 'opacity-50': paidAmount < tariff }">
            <div class="text-xs font-semibold text-muted-foreground mb-1">Kembali</div>
            <div class="text-3xl font-semibold tabular-nums text-foreground">{{ formatRp(Math.max(0, paidAmount - tariff)) }}</div>
          </div>
        </div>

        <!-- Denomination shortcuts -->
        <div class="text-xs font-semibold text-muted-foreground mb-2">Shortcut Nominal</div>
        <div class="grid grid-cols-7 gap-2 mb-6">
          <button
            v-for="(denom, idx) in denominations"
            :key="denom"
            class="rounded-md border border-border bg-background px-2 py-3 text-center transition-colors duration-150 hover:bg-surface-hover"
            :class="{ 'border-primary bg-primary/15': paidAmount === denom }"
            @click="setDenom(denom)"
          >
            <div class="text-xl font-semibold leading-none text-foreground">{{ shortLabel(denom) }}</div>
            <div class="text-xs font-medium text-muted-foreground">«{{ idx + 1 }}»</div>
          </button>
        </div>

        <!-- Footer hint + actions -->
        <div class="flex items-center justify-between">
          <div class="text-xs font-medium text-muted-foreground max-w-md">
            <div>Konfirmasi 1/7 — bisa juga ketik angka langsung.</div>
            <div class="mt-1">setelah Enter, struk dicetak otomatis, layar pindah ke 'buka palang', tekan Space saat kembalian sudah diberikan.</div>
          </div>
          <div class="flex gap-2">
            <button class="pos-btn" @click="close">
              <kbd class="pos-key">Esc</kbd> Batal
            </button>
            <button class="pos-btn is-go" :disabled="paidAmount < tariff" @click="onConfirm">
              <kbd class="pos-key">Enter</kbd> DITERIMA →
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  tariff: { type: Number, default: 0 },
})
const emit = defineEmits(['update:open', 'confirm'])

const amountInput = ref(null)
const paidAmount = ref(0)

const denominations = [1000, 2000, 5000, 10000, 20000, 50000, 100000]

function formatRp(v) {
  return 'Rp ' + Number(v || 0).toLocaleString('id-ID')
}
function shortLabel(v) {
  if (v >= 1000) return (v / 1000) + 'rb'
  return String(v)
}
function setDenom(v) { paidAmount.value = v }
function close() { emit('update:open', false) }
function onConfirm() {
  if (paidAmount.value < props.tariff) return
  emit('confirm', paidAmount.value)
  emit('update:open', false)
}

function onKey(e) {
  if (!props.open) return
  const idx = parseInt(e.key, 10)
  if (idx >= 1 && idx <= denominations.length) {
    paidAmount.value = denominations[idx - 1]
    e.preventDefault()
  }
}

watch(() => props.open, (val) => {
  if (val) {
    paidAmount.value = props.tariff
    nextTick(() => amountInput.value?.focus())
    window.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('keydown', onKey)
    nextTick(() => {
      const barcodeInput = document.querySelector('[data-barcode-input]')
      barcodeInput?.focus()
    })
  }
})
</script>
