<template>
  <div class="rounded-lg border border-border bg-background">
    <div class="flex items-center justify-between gap-3 px-4 py-3">
      <label class="flex items-center gap-3 cursor-pointer">
        <input
          type="checkbox"
          :checked="enabled"
          class="h-4 w-4 accent-primary"
          @change="$emit('update:enabled', $event.target.checked)"
        >
        <span class="text-sm font-medium text-foreground">{{ title }}</span>
      </label>
      <button
        v-if="enabled && $slots.default"
        type="button"
        class="text-xs text-muted-foreground hover:text-foreground"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Tutup' : 'Atur' }}
      </button>
    </div>

    <div
      v-if="enabled && expanded"
      class="border-t border-border bg-surface-hover/30 px-4 py-3"
    >
      <slot />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  enabled: { type: Boolean, default: false },
  defaultOpen: { type: Boolean, default: true },
})

defineEmits(['update:enabled'])

const expanded = ref(props.enabled && props.defaultOpen)
watch(() => props.enabled, (v) => { if (!v) expanded.value = false; else expanded.value = props.defaultOpen })
</script>
