<template>
  <div v-if="visible" class="border border-border bg-surface p-4 shadow-brutal">
    <!-- Card info header -->
    <div v-if="cardInfo" class="mb-3 flex items-center justify-between">
      <div>
        <div class="text-xs font-bold  tracking-wide text-muted-foreground">{{ cardInfo.cardType }}</div>
        <div class="font-mono text-sm font-bold text-foreground tracking-wide">{{ cardInfo.cardNumber }}</div>
      </div>
      <Badge :variant="stateVariant">{{ stateLabel }}</Badge>
    </div>

    <!-- State-specific content -->
    <div class="space-y-2">
      <!-- Waiting for card -->
      <div v-if="emoneyState === 'IDLE' && hasCardNumber" class="text-center py-1">
        <div class="text-sm font-medium text-muted-foreground">Tekan tombol E-Money untuk mulai</div>
      </div>

      <!-- Processing -->
      <div v-if="emoneyState === 'PROCESSING'" class="text-center py-1">
        <div class="flex items-center justify-center gap-2">
          <span class="h-3 w-3 border border-border bg-warning animate-pulse" />
          <span class="text-sm font-bold  text-warning">Memproses pembayaran...</span>
        </div>
        <div class="mt-1 text-xs font-medium text-muted-foreground">Jangan geser kartu</div>
      </div>

      <!-- Success -->
      <div v-if="emoneyState === 'SUCCESS'" class="text-center py-1">
        <div class="text-base font-bold  text-success">Pembayaran Berhasil</div>
        <div v-if="balance != null" class="mt-1">
          <span class="text-xs font-medium text-muted-foreground">Saldo tersisa: </span>
          <span class="font-mono text-base font-bold text-foreground">{{ formattedBalance }}</span>
        </div>
      </div>

      <!-- Error states -->
      <div v-if="isError" class="text-center py-1">
        <div class="text-sm font-bold  text-destructive">{{ errorMessage }}</div>
      </div>
    </div>

    <!-- Action buttons for error states -->
    <div v-if="isError" class="mt-3 flex gap-2">
      <Button
        v-if="emoneyState !== 'LOST_CONTACT'"
        variant="outline"
        size="sm"
        class="flex-1"
        @click="$emit('retry')"
      >
        Coba Lagi
      </Button>
      <Button
        variant="outline"
        size="sm"
        class="flex-1"
        @click="$emit('cancel')"
      >
        {{ emoneyState === 'LOST_CONTACT' ? 'Batalkan' : 'Batal' }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useFormatters } from '~/composables/useFormatters'
import { Button } from '~/components/ui/button'
import Badge from '~/components/ui/badge/Badge.vue'

const props = defineProps({
  emoneyState: { type: String, default: 'IDLE' },
  cardInfo: { type: Object, default: null },
  balance: { type: Number, default: null },
  hasCardNumber: { type: Boolean, default: false },
})

defineEmits(['retry', 'cancel'])

const { formatCurrency } = useFormatters()

const visible = computed(() => {
  return props.emoneyState !== 'IDLE' || props.hasCardNumber
})

const isError = computed(() =>
  ['LOST_CONTACT', 'WRONG_CARD', 'INSUFFICIENT', 'FAILED'].includes(props.emoneyState)
)

const formattedBalance = computed(() => formatCurrency(props.balance))

const stateVariant = computed(() => {
  switch (props.emoneyState) {
    case 'PROCESSING': return 'secondary'
    case 'SUCCESS': return 'default'
    case 'FAILED': case 'LOST_CONTACT': case 'WRONG_CARD': case 'INSUFFICIENT': return 'destructive'
    default: return 'outline'
  }
})

const stateLabel = computed(() => {
  switch (props.emoneyState) {
    case 'PROCESSING': return 'Proses'
    case 'SUCCESS': return 'Berhasil'
    case 'LOST_CONTACT': return 'Kontak Hilang'
    case 'WRONG_CARD': return 'Kartu Salah'
    case 'INSUFFICIENT': return 'Saldo Kurang'
    case 'FAILED': return 'Gagal'
    default: return 'Siap'
  }
})

const errorMessage = computed(() => {
  switch (props.emoneyState) {
    case 'LOST_CONTACT': return 'Kartu terlepas. Tap kartu lagi untuk koreksi.'
    case 'WRONG_CARD': return 'Kartu tidak sesuai. Gunakan kartu yang benar.'
    case 'INSUFFICIENT': return 'Saldo e-money tidak cukup.'
    case 'FAILED': return 'Pembayaran e-money gagal.'
    default: return ''
  }
})
</script>
