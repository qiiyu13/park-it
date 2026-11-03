<template>
  <button
    :class="[
      'flex items-center gap-1.5 border border-border px-2 py-1 text-xs font-bold  shadow-brutal-sm transition-all duration-100',
      uncovered
        ? 'bg-destructive text-white   hover:shadow-none'
        : pendingHandover
          ? 'bg-warning text-foreground   hover:shadow-none'
          : 'bg-surface text-foreground   hover:shadow-none',
    ]"
    :title="tooltipText"
    @click="$emit('click')"
  >
    <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
    <span class="truncate max-w-[120px]">{{ displayName }}</span>
    <span v-if="pendingHandover" class="h-2 w-2 border border-border bg-foreground animate-pulse" />
    <span v-else-if="uncovered" class="h-2 w-2 border border-border bg-white animate-pulse" />
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  worker: { type: Object, default: null },
  sessionStatus: { type: String, default: null },
})

defineEmits(['click'])

const uncovered = computed(() => !props.worker && !props.sessionStatus)
const pendingHandover = computed(() => props.sessionStatus === 'PENDING_HANDOVER')

const displayName = computed(() => {
  if (uncovered.value) return 'Tidak ada petugas'
  if (pendingHandover.value) return 'Menunggu pengganti...'
  return props.worker?.full_name || props.worker?.username || '—'
})

const tooltipText = computed(() => {
  if (uncovered.value) return 'Pos tidak terjaga — klik untuk check-in'
  if (pendingHandover.value) return 'Menunggu petugas pengganti'
  return `Petugas: ${displayName.value} — klik untuk ganti shift`
})
</script>
