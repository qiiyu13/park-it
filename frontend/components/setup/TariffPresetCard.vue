<template>
  <button
    type="button"
    :class="[
      'group flex flex-col gap-2 rounded-lg border bg-background p-4 text-left transition-colors',
      selected
        ? 'border-primary ring-2 ring-primary/30'
        : 'border-border hover:bg-surface-hover',
    ]"
    @click="$emit('apply', preset.id)"
  >
    <div class="flex items-center justify-between">
      <p class="font-semibold text-foreground">{{ preset.name }}</p>
      <span
        v-if="selected"
        class="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
      >
        Dipilih
      </span>
    </div>
    <p class="text-xs text-muted-foreground">{{ preset.description }}</p>

    <ul class="mt-1 space-y-1 text-xs text-foreground">
      <li v-for="item in preset.items" :key="item.name" class="flex items-center justify-between">
        <span class="font-medium">{{ item.name }}</span>
        <span class="text-muted-foreground">
          {{ formatItem(item) }}
        </span>
      </li>
    </ul>
  </button>
</template>

<script setup>
import { useFormatters } from '~/composables/useFormatters'

defineProps({
  preset: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

defineEmits(['apply'])

const { formatCurrency } = useFormatters()

function formatItem(item) {
  if (item.rate_type === 'flat') {
    return `${formatCurrency(item.first_hour_rate)} flat`
  }
  if (item.rate_type === 'progressive') {
    return `${formatCurrency(item.first_hour_rate)} jam 1 · ${formatCurrency(item.per_hour_rate)}/jam (naik)`
  }
  return `${formatCurrency(item.first_hour_rate)} jam 1 · ${formatCurrency(item.per_hour_rate)}/jam`
}
</script>
