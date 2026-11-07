<template>
  <button
    type="button"
    :class="[
      'group flex flex-col items-center gap-2 rounded-xl border bg-background p-5 text-center transition-colors',
      selected
        ? 'border-primary ring-2 ring-primary/30'
        : 'border-border hover:bg-surface-hover',
    ]"
    @click="$emit('select')"
  >
    <div class="font-mono text-xl font-semibold text-foreground">
      {{ inCount }} + {{ outCount }}
    </div>
    <pre class="text-xs leading-tight text-muted-foreground">{{ diagram }}</pre>
    <p class="text-sm font-medium text-foreground">{{ label }}</p>
    <p v-if="description" class="text-xs text-muted-foreground">{{ description }}</p>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  inCount: { type: Number, required: true },
  outCount: { type: Number, required: true },
  label: { type: String, default: '' },
  description: { type: String, default: '' },
  selected: { type: Boolean, default: false },
})

defineEmits(['select'])

const diagram = computed(() => {
  const inRows = Array.from({ length: props.inCount }).map((_, i) => `IN-${i + 1}  ▶ ░░`)
  const outRows = Array.from({ length: props.outCount }).map((_, i) => `OUT-${i + 1} ◀ ░░`)
  return [...inRows, ...outRows].join('\n')
})
</script>
