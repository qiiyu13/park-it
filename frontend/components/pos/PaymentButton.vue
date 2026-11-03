<template>
  <button
    :class="[
      'w-full h-16 flex items-center justify-between rounded-lg px-5 border border-transparent font-semibold text-lg text-white shadow-brutal-sm transition-colors duration-150',
      'hover:enabled:brightness-95',
      'disabled:opacity-35 disabled:cursor-not-allowed',
      buttonColorClass,
    ]"
    :disabled="disabled || processing"
    @click="$emit('click')"
  >
    <div class="flex items-center gap-3">
      <component :is="iconComponent" class="w-8 h-8" />
      <span>{{ label }}</span>
    </div>
    <div class="text-sm opacity-70 font-bold">
      <div v-if="processing" class="flex items-center gap-2">
        <span class="h-4 w-4 animate-spin border border-white/20 border-t-white" />
      </div>
      <span v-else>{{ shortcut }}</span>
    </div>
  </button>
</template>

<script setup>
import { computed, h } from 'vue'

const props = defineProps({
  icon: { type: String, required: true }, // 'cash', 'rfid', 'emoney'
  label: { type: String, required: true },
  shortcut: { type: String, required: true },
  disabled: { type: Boolean, default: false },
  processing: { type: Boolean, default: false },
})

defineEmits(['click'])

const buttonColorClass = computed(() => {
  switch (props.icon) {
    case 'cash': return 'bg-success'
    case 'rfid': return 'bg-info'
    case 'emoney': return 'bg-emoney'
    default: return 'bg-primary text-primary-foreground'
  }
})

const iconComponent = computed(() => {
  switch (props.icon) {
    case 'cash':
      return h('svg', {
        fill: 'none',
        stroke: 'currentColor',
        viewBox: '0 0 24 24',
      }, [
        h('path', {
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          'stroke-width': '2',
          d: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z',
        })
      ])
    case 'rfid':
      return h('svg', {
        fill: 'none',
        stroke: 'currentColor',
        viewBox: '0 0 24 24',
      }, [
        h('path', {
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          'stroke-width': '2',
          d: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
        })
      ])
    case 'emoney':
      return h('svg', {
        fill: 'none',
        stroke: 'currentColor',
        viewBox: '0 0 24 24',
      }, [
        h('path', {
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          'stroke-width': '2',
          d: 'M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z',
        })
      ])
    default:
      return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [])
  }
})
</script>
