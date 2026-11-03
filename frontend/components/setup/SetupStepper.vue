<template>
  <nav role="navigation" aria-label="Setup steps" class="flex flex-wrap items-center gap-2 sm:gap-3">
    <template v-for="(step, idx) in steps" :key="step.key">
      <div class="flex flex-col items-center gap-1">
        <button
          type="button"
          :aria-current="idx === currentIndex ? 'step' : undefined"
          :disabled="!canNavigate(idx)"
          :class="[
            'flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors',
            idx < currentIndex && 'border-success bg-success text-white',
            idx === currentIndex && 'border-primary bg-primary text-primary-foreground',
            idx > currentIndex && 'border-border bg-muted text-muted-foreground',
            canNavigate(idx) ? 'cursor-pointer' : 'cursor-not-allowed opacity-70',
          ]"
          @click="onClick(idx)"
        >
          <svg v-if="idx < currentIndex" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span v-else>{{ idx + 1 }}</span>
        </button>
        <span
          :class="[
            'hidden text-xs sm:block',
            idx === currentIndex ? 'font-semibold text-foreground' : 'font-medium text-muted-foreground',
          ]"
        >
          {{ step.label }}
        </span>
      </div>
      <div
        v-if="idx < steps.length - 1"
        :class="[
          'mt-[-12px] h-0.5 flex-1 min-w-4 max-w-12',
          idx < currentIndex ? 'bg-success' : 'bg-border',
        ]"
      />
    </template>
  </nav>
</template>

<script setup>
const props = defineProps({
  steps: { type: Array, required: true },
  currentIndex: { type: Number, default: 0 },
})

const emit = defineEmits(['navigate'])

function canNavigate(idx) {
  return idx <= props.currentIndex
}

function onClick(idx) {
  if (canNavigate(idx)) emit('navigate', idx)
}
</script>
