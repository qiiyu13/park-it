<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs font-medium',
      classes[status] || classes.idle,
    ]"
    role="status"
    aria-live="polite"
  >
    <span :class="['h-2 w-2 rounded-full', dotClasses[status] || dotClasses.idle, status === 'testing' && 'animate-pulse']" />
    <span>{{ label || defaultLabels[status] || status }}</span>
  </span>
</template>

<script setup>
defineProps({
  status: {
    type: String,
    default: 'idle',
    validator: (v) => ['online', 'offline', 'testing', 'warning', 'idle'].includes(v),
  },
  label: { type: String, default: '' },
})

const classes = {
  online: 'bg-success/10 text-success',
  offline: 'bg-destructive/10 text-destructive',
  testing: 'bg-primary/15 text-foreground',
  warning: 'bg-warning/10 text-warning',
  idle: 'bg-muted text-muted-foreground',
}

const dotClasses = {
  online: 'bg-success',
  offline: 'bg-destructive',
  testing: 'bg-primary',
  warning: 'bg-warning',
  idle: 'bg-muted-foreground/50',
}

const defaultLabels = {
  online: 'Terhubung',
  offline: 'Tidak Terhubung',
  testing: 'Menguji...',
  warning: 'Peringatan',
  idle: 'Idle',
}
</script>
