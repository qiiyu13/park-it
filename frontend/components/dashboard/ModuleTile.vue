<template>
  <NuxtLink
    :to="to"
    class="group flex items-start gap-4 rounded-lg border border-border bg-surface p-5 shadow-brutal-sm transition-colors duration-150 hover:border-border/30 hover:bg-surface-hover/60"
  >
    <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/15 text-foreground">
      <component
        :is="icon"
        class="h-5 w-5"
        :stroke-width="2"
      />
    </div>
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-foreground">{{ title }}</h3>
        <span
          v-if="badge"
          class="rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-semibold text-destructive"
        >
          {{ badge }}
        </span>
      </div>
      <p class="mt-1 text-sm text-muted-foreground leading-relaxed">{{ description }}</p>
    </div>
  </NuxtLink>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, required: true },
  // Vue icon component (all dashboard modules use lucide components).
  icon: { type: [Object, Function], required: true },
  to: { type: String, required: true },
  badge: { type: [String, Number], default: null },
})
</script>
