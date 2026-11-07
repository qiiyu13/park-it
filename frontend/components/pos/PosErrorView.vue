<template>
  <div
    :class="[
      'flex h-full flex-col items-center justify-center gap-6 p-6',
      errorType === 'timeout' ? 'bg-destructive/10' : 'bg-warning/10',
    ]"
  >
    <!-- Icon + Title -->
    <div class="text-center space-y-2">
      <div
        :class="[
          'mx-auto flex h-16 w-16 items-center justify-center rounded-xl',
          errorType === 'timeout' ? 'bg-destructive' : 'bg-warning',
        ]"
      >
        <AlertTriangle
          v-if="errorType === 'timeout'"
          class="h-8 w-8 text-on-solid"
        />
        <CreditCard
          v-else
          class="h-8 w-8 text-on-solid"
        />
      </div>
      <div :class="['text-2xl font-semibold tracking-tight', errorType === 'timeout' ? 'text-destructive' : 'text-warning']">
        {{ title }}
      </div>
      <div class="text-sm font-medium text-muted-foreground max-w-md">{{ description }}</div>
    </div>

    <!-- Timeout counter -->
    <div v-if="errorType === 'timeout' && waitingSeconds > 0" class="text-center">
      <div class="text-6xl font-semibold text-destructive tabular-nums">{{ waitingSeconds }}s</div>
    </div>

    <!-- Plate reminder -->
    <div v-if="plateNumber" class="text-center">
      <div class="font-mono text-xl font-semibold text-muted-foreground tracking-wider">{{ plateNumber }}</div>
    </div>

    <!-- Recovery buttons -->
    <div class="flex flex-wrap items-center justify-center gap-3 max-w-lg">
      <!-- Timeout actions: primary=cash, secondary=open gate, tertiary=vehicle left -->
      <template v-if="errorType === 'timeout'">
        <Button size="lg" variant="default" class="h-14 px-6 text-base" @click="$emit('pay-cash')">
          Bayar Cash
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('manual-open')">
          Buka Palang
        </Button>
        <Button size="lg" variant="ghost" class="h-14 px-6 text-base text-muted-foreground" @click="$emit('vehicle-left')">
          Kendaraan Pergi
        </Button>
      </template>

      <!-- E-money: insufficient balance — primary=cash, secondary=rfid, tertiary=retry -->
      <template v-if="emoneyState === 'INSUFFICIENT'">
        <Button size="lg" variant="default" class="h-14 px-6 text-base" @click="$emit('pay-cash')">
          Bayar Cash
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('pay-rfid')">
          Bayar RFID
        </Button>
        <Button size="lg" variant="ghost" class="h-14 px-6 text-base text-muted-foreground" @click="$emit('retry-emoney')">
          Coba Lagi
        </Button>
      </template>

      <!-- E-money: wrong card — primary=cash, secondary=retry -->
      <template v-if="emoneyState === 'WRONG_CARD'">
        <Button size="lg" variant="default" class="h-14 px-6 text-base" @click="$emit('pay-cash')">
          Bayar Cash
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('retry-emoney')">
          Coba Lagi
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('pay-rfid')">
          Bayar RFID
        </Button>
      </template>

      <!-- E-money: lost contact — primary=tap again, secondary=cash/rfid, tertiary=cancel -->
      <template v-if="emoneyState === 'LOST_CONTACT'">
        <Button size="lg" variant="default" class="h-14 px-6 text-base" @click="$emit('retry-emoney')">
          Tap Lagi
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('pay-cash')">
          Bayar Cash
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('pay-rfid')">
          Bayar RFID
        </Button>
        <Button size="lg" variant="ghost" class="h-14 px-6 text-base text-muted-foreground" @click="$emit('cancel-correction')">
          Batalkan
        </Button>
      </template>

      <!-- E-money: generic failure — primary=cash, secondary=retry, no override -->
      <template v-if="emoneyState === 'FAILED'">
        <Button size="lg" variant="default" class="h-14 px-6 text-base" @click="$emit('pay-cash')">
          Bayar Cash
        </Button>
        <Button size="lg" variant="outline" class="h-14 px-6 text-base" @click="$emit('retry-emoney')">
          Coba Lagi
        </Button>
        <p class="w-full text-center text-xs text-muted-foreground">Hubungi admin jika masalah berlanjut.</p>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { AlertTriangle, CreditCard } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'

const props = defineProps({
  paymentState: { type: String, default: 'IDLE' },
  emoneyState: { type: String, default: 'IDLE' },
  waitingSeconds: { type: Number, default: 0 },
  plateNumber: { type: String, default: '' },
})

defineEmits([
  'manual-open',
  'vehicle-left',
  'pay-cash',
  'pay-rfid',
  'retry-emoney',
  'cancel-correction',
])

const errorType = computed(() => {
  if (props.paymentState === 'TIMEOUT_ALERT') return 'timeout'
  return 'emoney'
})

const title = computed(() => {
  if (props.paymentState === 'TIMEOUT_ALERT') return 'Timeout — Kendaraan Menunggu'
  if (props.emoneyState === 'INSUFFICIENT') return 'Saldo Tidak Cukup'
  if (props.emoneyState === 'WRONG_CARD') return 'Kartu Tidak Sesuai'
  if (props.emoneyState === 'LOST_CONTACT') return 'Kontak Kartu Hilang'
  if (props.emoneyState === 'FAILED') return 'Pembayaran E-Money Gagal'
  return 'Error'
})

const description = computed(() => {
  if (props.paymentState === 'TIMEOUT_ALERT') return 'Kendaraan telah menunggu melebihi batas waktu. Pilih tindakan di bawah.'
  if (props.emoneyState === 'INSUFFICIENT') return 'Saldo e-money tidak mencukupi untuk tarif parkir. Gunakan metode pembayaran lain.'
  if (props.emoneyState === 'WRONG_CARD') return 'Kartu yang di-tap tidak sesuai dengan kartu masuk. Gunakan kartu yang benar.'
  if (props.emoneyState === 'LOST_CONTACT') return 'Kartu terlepas saat proses debit. Tap kartu lagi, atau gunakan metode lain.'
  if (props.emoneyState === 'FAILED') return 'Proses pembayaran e-money gagal. Coba lagi atau gunakan metode pembayaran lain.'
  return ''
})
</script>
