<template>
  <div class="flex h-screen flex-col overflow-hidden bg-background text-foreground">
    <!-- Status Bar -->
    <header class="flex h-16 shrink-0 items-center gap-3 border-b border-white/10 bg-sidebar px-5 text-sidebar-foreground">
      <div class="flex-1 min-w-0">
        <slot name="status-bar" />
      </div>
      <button
        type="button"
        class="flex shrink-0 items-center gap-1.5 rounded-md border border-white/20 px-3 py-1.5 text-xs font-semibold text-sidebar-foreground transition-colors hover:bg-white/10"
        title="Keluar dari sesi POS — lalu login sebagai admin"
        @click="switchUser"
      >
        Keluar
      </button>
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

<script setup>
const authStore = useAuthStore()
const router = useRouter()

async function switchUser() {
  await authStore.logout()
  // `switch=1` lets the auth middleware show /login even if a cookie survived.
  await router.push('/login?switch=1')
}
</script>
