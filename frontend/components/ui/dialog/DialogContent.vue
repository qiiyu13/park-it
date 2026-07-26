<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { X } from "lucide-vue-next"
import {
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<DialogContentProps & { class?: HTMLAttributes["class"] }>()
const emits = defineEmits<DialogContentEmits>()

function omitClass() {
  const { class: _, ...rest } = props
  return rest
}
</script>

<template>
  <DialogPortal>
    <DialogOverlay
      class="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
    />
    <DialogContent
      v-bind="omitClass()"
      :class="
        cn(
          'fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 border-4 border-foreground bg-surface p-6 shadow-brutal-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]',
          props.class,
        )"
      @pointer-down-outside="emits('pointerDownOutside', $event)"
      @interact-outside="emits('interactOutside', $event)"
      @open-auto-focus="emits('openAutoFocus', $event)"
      @close-auto-focus="emits('closeAutoFocus', $event)"
    >
      <slot />

      <DialogClose
        class="absolute right-4 top-4 border-2 border-foreground bg-background p-1 font-bold opacity-80 transition-all hover:opacity-100 hover:shadow-brutal-sm hover:translate-x-[1px] hover:translate-y-[1px] focus:outline-none disabled:pointer-events-none"
      >
        <X class="w-4 h-4" />
        <span class="sr-only">Close</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
