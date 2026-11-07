<template>
  <div class="flex h-full flex-col items-center justify-center gap-6 p-6">
    <!-- Change amount (if applicable) -->
    <div v-if="changeAmount > 0" class="text-center space-y-1">
      <div class="text-sm font-medium text-muted-foreground">Kembalian</div>
      <div class="text-5xl font-semibold text-foreground tabular-nums">{{ formattedChange }}</div>
    </div>

    <!-- Plate reminder -->
    <div v-if="plateNumber" class="text-center">
      <div class="font-mono text-2xl font-semibold text-muted-foreground tracking-wider">{{ plateNumber }}</div>
    </div>

    <!-- Giant green button -->
    <button
      class="h-40 w-full max-w-md rounded-xl bg-success text-3xl font-semibold text-on-solid shadow-brutal transition-[filter] duration-150 hover:brightness-95"
      @click="$emit('open-gate')"
    >
      Buka Palang
    </button>

    <!-- Space key hint -->
    <div class="text-sm font-medium text-muted-foreground">
      Tekan
      <kbd class="pos-key mx-1">Space</kbd>
      untuk buka palang
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useFormatters } from '~/composables/useFormatters'

const props = defineProps({
  changeAmount: { type: Number, default: 0 },
  plateNumber: { type: String, default: '' },
})

defineEmits(['open-gate'])

const { formatCurrency } = useFormatters()

const formattedChange = computed(() => formatCurrency(props.changeAmount))
</script>
