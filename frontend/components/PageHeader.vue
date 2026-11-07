<template>
  <div class="mb-6 flex items-start justify-between gap-3 border-b border-border pb-4">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">{{ title }}</h1>
      <p v-if="subtitle" class="mt-1 text-sm text-muted-foreground">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.action" class="shrink-0">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>
