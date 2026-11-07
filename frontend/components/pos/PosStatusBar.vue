<template>
  <div class="flex items-center justify-between w-full">
    <!-- Left: Local device statuses -->
    <div class="flex items-center gap-4">
      <span class="text-xs font-semibold tracking-wider text-sidebar-muted">Perangkat</span>
      <div
        v-for="item in indicators"
        :key="item.label"
        class="flex items-center gap-2"
        :title="`${item.label}: ${item.statusText}`"
      >
        <span
          :class="[
            'h-2 w-2 rounded-full',
            item.ok ? 'bg-success' : item.warn ? 'bg-warning' : 'bg-destructive',
          ]"
        />
        <span class="text-sm font-medium text-sidebar-foreground">{{ item.label }}</span>
      </div>
    </div>

    <!-- Right: Clock -->
    <div class="flex items-center gap-2">
      <ThemeToggle class="text-sidebar-muted hover:bg-white/10 hover:text-sidebar-foreground" />
      <div class="font-mono text-lg font-medium tabular-nums text-sidebar-foreground">{{ clock }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  boothConnected: { type: Boolean, default: false },
  hardwareStatus: { type: Object, default: () => ({}) },
})

const clock = ref('')
let clockTimer = null

const indicators = computed(() => [
  {
    label: 'Booth',
    ok: props.boothConnected,
    warn: false,
    statusText: props.boothConnected ? 'connected' : 'disconnected',
  },
  {
    label: 'RFID',
    ok: props.hardwareStatus?.rfid?.status === 'connected',
    warn: false,
    statusText: props.hardwareStatus?.rfid?.status || 'unknown',
  },
{
    label: 'E-Money',
    ok: props.hardwareStatus?.emoney?.status === 'ready',
    warn: props.hardwareStatus?.emoney?.status === 'stale',
    statusText: props.hardwareStatus?.emoney?.status || 'unknown',
  },
  {
    label: 'Printer',
    ok: props.hardwareStatus?.printer?.status === 'online',
    warn: props.hardwareStatus?.printer?.status === 'stale',
    statusText: props.hardwareStatus?.printer?.status || 'unknown',
  },
])

function updateClock() {
  clock.value = new Date().toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})
</script>
