<template>
  <div class="mx-auto max-w-7xl space-y-8">
    <!-- Greeting bar -->
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="text-xs font-semibold text-muted-foreground">Ringkasan operasional</p>
        <h2 class="mt-1 text-2xl font-semibold tracking-tight text-foreground">
          {{ greeting }}, {{ authStore.user?.full_name || authStore.user?.username || 'Pengguna' }}
        </h2>
        <p class="mt-1 text-sm text-muted-foreground">{{ formattedDate }}</p>
      </div>
      <NuxtLink
        v-if="authStore.isAdmin"
        to="/transaksi"
        class="text-sm font-medium text-info hover:underline"
      >
        Lihat transaksi
      </NuxtLink>
    </header>

    <!-- Live metrics -->
    <section class="grid gap-3 sm:grid-cols-3">
      <div class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-muted-foreground">Kendaraan aktif</span>
          <span :class="['h-2 w-2 rounded-full', activeCount > 0 ? 'bg-success' : 'bg-border']" />
        </div>
        <div class="mt-2 font-mono text-3xl font-semibold tabular-nums text-foreground">
          {{ loadingStatus ? '—' : activeCount }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground">Sedang berada di area parkir</p>
      </div>

      <NuxtLink to="/notification" class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm transition-colors duration-150 hover:bg-surface-hover">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-muted-foreground">Unresolved e-money</span>
          <span :class="['h-2 w-2 rounded-full', unresolvedCount > 0 ? 'bg-warning' : 'bg-border']" />
        </div>
        <div :class="['mt-2 font-mono text-3xl font-semibold tabular-nums', unresolvedCount > 0 ? 'text-warning' : 'text-foreground']">
          {{ loadingStatus ? '—' : unresolvedCount }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground">Transaksi butuh tindakan</p>
      </NuxtLink>

      <div class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-muted-foreground">Gate aktif</span>
        </div>
        <div class="mt-2 font-mono text-3xl font-semibold tabular-nums text-foreground">
          {{ websiteStore.activeGateOuts.length + websiteStore.activeGateIns.length }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground">Lane masuk dan keluar</p>
      </div>
    </section>

    <GateHeartbeatPanel />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

definePageMeta({
  middleware: 'auth',
  layout: 'default',
})

const authStore = useAuthStore()
const websiteStore = useWebsiteStore()
const { fetchApi } = useApi()

const loadingStatus = ref(true)
const activeCount = ref(0)
const unresolvedCount = ref(0)

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 11) return 'Selamat pagi'
  if (hour < 15) return 'Selamat siang'
  if (hour < 18) return 'Selamat sore'
  return 'Selamat malam'
})

const formattedDate = computed(() => {
  return new Date().toLocaleDateString('id-ID', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
})

async function loadStatus() {
  loadingStatus.value = true
  try {
    const [activeRes, unresolvedRes] = await Promise.all([
      fetchApi('/api/transactions?status=ACTIVE&limit=1').catch(() => null),
      fetchApi('/api/transactions?status=LOST_CONTACT&limit=1').catch(() => null),
    ])
    activeCount.value = activeRes?.total ?? 0
    unresolvedCount.value = unresolvedRes?.total ?? 0

  } finally {
    loadingStatus.value = false
  }
}

onMounted(async () => {
  await Promise.all([websiteStore.loadAll(), loadStatus()])
})
</script>
