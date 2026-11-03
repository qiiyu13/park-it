<script setup lang="ts">
import { computed } from "vue"
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  class?: HTMLAttributes["class"]
}>()

const emits = defineEmits<{
  (e: "update:modelValue", payload: string | number): void
}>()

const modelValue = computed({
  get: () => props.modelValue ?? props.defaultValue,
  set: (value) => emits("update:modelValue", value),
})
</script>

<template>
  <input v-model="modelValue" :class="cn('flex h-10 w-full rounded-md border border-border bg-surface px-3.5 py-2 text-sm text-foreground transition-colors placeholder:text-muted-foreground/70 focus-visible:border-[color:var(--focus-ring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring)]/25 disabled:cursor-not-allowed disabled:opacity-40 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground', props.class)">
</template>
