<template>
  <div class="flex h-screen flex-col overflow-hidden bg-background text-foreground">
    <!-- Status Bar -->
    <header class="flex h-16 shrink-0 items-center gap-3 border-b border-white/10 bg-sidebar px-5 text-sidebar-foreground">
      <div class="flex-1 min-w-0">
        <slot name="status-bar" />
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 overflow-hidden">
      <slot />
    </main>

    <!-- Action Bar -->
    <footer class="flex h-20 shrink-0 items-center border-t border-border bg-surface px-6">
      <slot name="action-bar" />
    </footer>
  </div>
</template>
