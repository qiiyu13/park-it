<template>
  <div class="mb-4 flex flex-wrap gap-1" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      role="tab"
      :aria-selected="modelValue === tab.key"
      :class="[
        'h-9 rounded-md px-4 text-sm font-medium transition-colors duration-150',
        modelValue === tab.key
          ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-surface-hover hover:text-foreground',
      ]"
      @click="$emit('update:modelValue', tab.key)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  tabs: { type: Array, required: true },
  modelValue: { type: String, required: true },
})
defineEmits(['update:modelValue'])
</script>
