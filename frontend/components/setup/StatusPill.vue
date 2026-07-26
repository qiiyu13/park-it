<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 border-2 border-foreground px-2.5 py-1 text-xs font-bold uppercase shadow-brutal-sm',
      classes[status] || classes.idle,
    ]"
    role="status"
    aria-live="polite"
  >
    <span :class="['h-2 w-2 border border-foreground', dotClasses[status] || dotClasses.idle, status === 'testing' && 'animate-pulse']" />
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
  online: 'bg-success text-white',
  offline: 'bg-destructive text-white',
  testing: 'bg-primary text-foreground',
  warning: 'bg-warning text-foreground',
  idle: 'bg-muted text-muted-foreground',
}

const dotClasses = {
  online: 'bg-white',
  offline: 'bg-white',
  testing: 'bg-foreground',
  warning: 'bg-foreground',
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
