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

      <div class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-muted-foreground">Unresolved e-money</span>
          <span :class="['h-2 w-2 rounded-full', unresolvedCount > 0 ? 'bg-warning' : 'bg-border']" />
        </div>
        <div :class="['mt-2 font-mono text-3xl font-semibold tabular-nums', unresolvedCount > 0 ? 'text-warning' : 'text-foreground']">
          {{ loadingStatus ? '—' : unresolvedCount }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground">Transaksi butuh tindakan</p>
      </div>

      <div class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-muted-foreground">Gate aktif</span>
          <span class="h-2 w-2 rounded-full bg-info" />
        </div>
        <div class="mt-2 font-mono text-3xl font-semibold tabular-nums text-foreground">
          {{ websiteStore.activeGateOuts.length + websiteStore.activeGateIns.length }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground">Lane masuk dan keluar</p>
      </div>
    </section>

    <!-- Hero tile: POS Kiosk (operators only) -->
    <NuxtLink
      v-if="!authStore.isAdmin"
      to="/pos"
      class="group flex items-center gap-5 rounded-xl border border-primary/40 bg-primary/10 p-5 transition-colors duration-150 hover:border-primary hover:bg-primary/15"
    >
      <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="M2 10h20" />
          <path d="M12 4v6" />
        </svg>
      </div>
      <div class="flex-1 min-w-0">
        <h3 class="text-xl font-semibold tracking-tight text-foreground">Mulai POS Kiosk</h3>
        <p class="mt-1 text-sm text-muted-foreground">
          Mode layar penuh untuk operasional gate keluar
        </p>
        <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span v-if="posSession.shiftName" class="rounded-md bg-surface px-2 py-0.5 font-medium">
            Shift: {{ posSession.shiftName }}
          </span>
          <span class="rounded-md bg-surface px-2 py-0.5 font-medium">
            Transaksi: <span class="font-mono text-foreground">{{ posSession.transactionCount }}</span>
          </span>
          <span class="rounded-md bg-surface px-2 py-0.5 font-medium">
            Kas: <span class="font-mono text-foreground">{{ formatCurrency(posSession.cashCollected) }}</span>
          </span>
        </div>
      </div>
      <div class="shrink-0 text-muted-foreground transition-transform group-hover:translate-x-1">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </div>
    </NuxtLink>

    <!-- Operational modules -->
    <section v-if="operatorModules.length">
      <h3 class="mb-3 text-xs font-semibold text-muted-foreground">Operasional</h3>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <DashboardModuleTile
          v-for="item in operatorModules"
          :key="item.to"
          :title="item.title"
          :description="item.description"
          :icon="item.icon"
          :to="item.to"
          :badge="item.badge"
        />
      </div>
    </section>

    <!-- Administration modules -->
    <section v-if="adminModules.length">
      <h3 class="mb-3 text-xs font-semibold text-muted-foreground">Administrasi</h3>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <DashboardModuleTile
          v-for="item in adminModules"
          :key="item.to"
          :title="item.title"
          :description="item.description"
          :icon="item.icon"
          :to="item.to"
          :badge="item.badge"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, markRaw } from 'vue'
import {
  LogIn,
  FileText,
  Users,
  BarChart3,
  Bell,
  Settings,
  Cpu,
} from 'lucide-vue-next'

definePageMeta({
  middleware: 'auth',
  layout: 'default',
})

const authStore = useAuthStore()
const posSession = usePosSessionStore()
const websiteStore = useWebsiteStore()
const { fetchApi } = useApi()

const loadingStatus = ref(true)
const activeCount = ref(0)
const unresolvedCount = ref(0)

const allModules = [
  { to: '/gate-in', title: 'Gate In Monitor', description: 'Pantau kendaraan masuk secara real-time', icon: markRaw(LogIn), adminOnly: false, badge: null },
  { to: '/transaksi', title: 'Transaksi', description: 'Riwayat dan pencarian transaksi parkir', icon: markRaw(FileText), adminOnly: false, badge: null },
  { to: '/member', title: 'Member', description: 'Kelola kartu member dan langganan', icon: markRaw(Users), adminOnly: false, badge: null },
  { to: '/report', title: 'Laporan', description: 'Laporan pendapatan dan statistik parkir', icon: markRaw(BarChart3), adminOnly: false, badge: null },
  { to: '/notification', title: 'Notifikasi', description: 'Peringatan sistem dan notifikasi gate', icon: markRaw(Bell), adminOnly: false, badge: null },
  { to: '/device', title: 'Perangkat', description: 'Konfigurasi perangkat keras dan gate', icon: markRaw(Cpu), adminOnly: true, badge: null },
  { to: '/setting', title: 'Pengaturan', description: 'Pengaturan sistem, tarif, dan shift', icon: markRaw(Settings), adminOnly: true, badge: null },
]

const modules = ref(allModules.map((m) => ({ ...m })))

const visibleModules = computed(() =>
  modules.value.filter((m) => !m.adminOnly || authStore.isAdmin)
)

const operatorModules = computed(() =>
  visibleModules.value.filter((m) => !m.adminOnly)
)

const adminModules = computed(() =>
  visibleModules.value.filter((m) => m.adminOnly)
)

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

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    minimumFractionDigits: 0,
  }).format(value || 0)
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const [activeRes, unresolvedRes] = await Promise.all([
      fetchApi('/api/transactions?status=ACTIVE&limit=1').catch(() => null),
      fetchApi('/api/transactions?status=LOST_CONTACT&limit=1').catch(() => null),
    ])
    activeCount.value = activeRes?.total ?? 0
    unresolvedCount.value = unresolvedRes?.total ?? 0

    // Badge on notification tile when there are unresolved e-money transactions
    if (unresolvedCount.value > 0) {
      const notifModule = modules.value.find((m) => m.to === '/notification')
      if (notifModule) notifModule.badge = unresolvedCount.value
    }
  } finally {
    loadingStatus.value = false
  }
}

onMounted(async () => {
  const loads = [websiteStore.loadAll(), loadStatus()]
  if (!authStore.isAdmin) loads.push(posSession.loadShiftSummary())
  await Promise.all(loads)
})
</script>
