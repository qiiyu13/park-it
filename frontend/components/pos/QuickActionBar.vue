<template>
  <div class="flex items-center justify-between w-full">
    <!-- Left: Keyboard shortcuts (always visible) -->
    <div class="flex items-center gap-4">
      <span v-if="gateName || shiftName" class="flex items-center gap-2 text-sm">
        <span v-if="gateName" class="font-semibold text-foreground">{{ gateName }}</span>
        <span v-if="gateName && shiftName" class="text-border">/</span>
        <span v-if="shiftName" class="text-muted-foreground">{{ shiftName }}</span>
      </span>
      <span v-if="isMixedLane && activeVehicleTypeName" class="mr-2 flex items-center gap-2">
        <span class="rounded-md border border-primary/30 bg-primary/15 px-2.5 py-1 text-xs font-semibold text-foreground">{{ activeVehicleTypeName }}</span>
      </span>
      <button
        v-for="shortcut in shortcuts"
        :key="shortcut.key"
        type="button"
        class="flex items-center gap-2"
        :class="shortcut.active ? 'opacity-100' : 'opacity-40'"
        @click="shortcut.action && shortcut.action()"
      >
        <kbd
          :class="[
            'inline-flex h-8 min-w-8 items-center justify-center rounded-md border px-1.5 font-mono text-xs font-semibold',
            shortcut.active
              ? 'border-primary/40 bg-primary/10 text-foreground'
              : 'border-border bg-surface text-muted-foreground',
          ]"
        >
          {{ shortcut.key }}
        </kbd>
        <span :class="['text-xs font-medium', shortcut.active ? 'text-foreground' : 'text-muted-foreground']">{{ shortcut.label }}</span>
      </button>
    </div>

  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  paymentState: { type: String, default: 'IDLE' },
  emoneyState: { type: String, default: 'IDLE' },
  awaitingGateOpen: { type: Boolean, default: false },
  canPayCash: { type: Boolean, default: false },
  canPayEmoney: { type: Boolean, default: false },
  gateName: { type: String, default: '' },
  shiftName: { type: String, default: '' },
  isMixedLane: { type: Boolean, default: false },
  activeVehicleTypeName: { type: String, default: null },
  emoneyEnabled: { type: Boolean, default: true },
})

const emit = defineEmits(['manual-open', 'reprint-receipt'])

const shortcuts = computed(() => {
  const base = [
    // Cash-only site: Enter pays the exact fare and opens the gate; F1 is hidden.
    props.emoneyEnabled
      ? { key: 'F1', label: 'Tunai', active: props.canPayCash }
      : { key: 'Enter', label: 'Terima & Buka', active: props.canPayCash },
    ...(props.emoneyEnabled
      ? [{ key: 'F2', label: 'E-Money', active: props.canPayEmoney }]
      : []),
    { key: 'F11', label: 'Buka Manual', active: true, action: () => emit('manual-open') },
    { key: 'F12', label: 'Cetak Struk', active: true, action: () => emit('reprint-receipt') },
    { key: 'Space', label: 'Buka Palang', active: props.awaitingGateOpen },
    { key: 'Esc', label: 'Batal', active: true },
  ]
  if (props.isMixedLane) {
    base.unshift(
      { key: '1', label: 'Motor', active: true },
      { key: '2', label: 'Mobil', active: true },
    )
  }
  return base
})

</script>
