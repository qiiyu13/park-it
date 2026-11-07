<template>
  <div class="rounded-lg border border-border bg-surface p-4 text-center shadow-brutal-sm">
    <div class="mb-1 text-xs font-semibold text-muted-foreground">{{ label }}</div>
    <div :class="['font-mono text-xl font-semibold', variantClass]">{{ value }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  variant: { type: String, default: '' },
})

const variantClass = computed(() => ({
  success: 'text-success',
  destructive: 'text-destructive',
  warning: 'text-warning',
}[props.variant] ?? 'text-foreground'))
</script>
