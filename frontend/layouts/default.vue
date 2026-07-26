<template>
  <div class="flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Sidebar -->
    <aside
      v-if="authStore.isLoggedIn"
      :class="[
        'flex shrink-0 flex-col border-r-4 border-foreground bg-foreground text-background transition-all duration-200',
        collapsed ? 'w-16' : 'w-60',
      ]"
    >
      <!-- Logo -->
      <div
        class="flex h-14 items-center gap-3 border-b-2 border-background/20 px-4 cursor-pointer"
        @click="collapsed = !collapsed"
      >
        <div class="flex h-8 w-8 shrink-0 items-center justify-center border-2 border-background bg-primary text-foreground">
          <BrandIcon class="h-[18px] w-[18px]" />
        </div>
        <Transition name="fade-text">
          <span v-show="!collapsed" class="text-sm font-black uppercase tracking-wide">E-Parking</span>
        </Transition>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto p-2 space-y-1">
        <NuxtLink
          v-for="item in visibleItems"
          :key="item.path"
          :to="item.path"
          :class="[
            'flex items-center gap-3 border-2 px-3 py-2 text-sm font-bold uppercase tracking-wide transition-all duration-100',
            isActive(item.path)
              ? 'border-background bg-primary text-foreground shadow-brutal-sm'
              : 'border-transparent text-background/70 hover:border-background hover:bg-background/10 hover:text-background',
          ]"
          :title="item.label"
        >
          <component :is="item.icon" class="h-5 w-5 shrink-0" :stroke-width="2" />
          <Transition name="fade-text">
            <span v-show="!collapsed">{{ item.label }}</span>
          </Transition>
        </NuxtLink>
      </nav>

      <!-- Footer -->
      <div class="border-t-2 border-background/20 p-2">
        <button
          class="flex w-full items-center gap-3 border-2 border-transparent px-3 py-2 text-sm font-bold uppercase text-destructive transition-all hover:border-destructive hover:bg-destructive hover:text-white"
          @click="logout"
        >
          <svg class="h-5 w-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
          <Transition name="fade-text">
            <span v-show="!collapsed">Keluar</span>
          </Transition>
        </button>
      </div>
    </aside>

    <!-- Main area -->
    <div class="flex flex-1 flex-col overflow-hidden min-w-0">
      <!-- Header -->
      <header v-if="authStore.isLoggedIn" class="flex h-14 shrink-0 items-center justify-between border-b-4 border-foreground bg-background px-6">
        <h1 class="text-lg font-black uppercase tracking-wide text-foreground">{{ pageTitle }}</h1>
        <div class="flex items-center gap-4">
          <span class="font-mono text-sm font-bold text-foreground">{{ clock }}</span>
          <span
:class="[
            'border-2 border-foreground px-2 py-0.5 text-xs font-bold uppercase shadow-brutal-sm',
            authStore.isAdmin ? 'bg-destructive text-white' : 'bg-primary text-foreground',
          ]">
            {{ authStore.user?.role }}
          </span>
          <div class="flex items-center gap-2">
            <div class="flex h-7 w-7 items-center justify-center border-2 border-foreground bg-primary text-xs font-black text-foreground">
              {{ avatarInitial }}
            </div>
            <span class="text-sm font-medium text-foreground">{{ authStore.user?.username }}</span>
          </div>
        </div>
      </header>

      <!-- Content -->
      <main class="flex-1 overflow-y-auto p-6">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, markRaw } from 'vue'
import {
  LayoutGrid,
  Monitor,
  LogIn,
  FileText,
  Users,
  BarChart3,
  Bell,
  Settings,
  Cpu,
  Activity,
  Wrench,
  CalendarDays,
  UserCog,
} from 'lucide-vue-next'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()

const collapsed = ref(false)
const clock = ref('')
let clockTimer = null

// markRaw on icon components — they never need reactivity tracking.
const operatorItems = [
  { path: '/pos', label: 'POS Kiosk', icon: markRaw(Monitor) },
  { path: '/gate-in', label: 'Gate In', icon: markRaw(LogIn) },
  { path: '/gates-status', label: 'Gate Status', icon: markRaw(Activity) },
  { path: '/transaksi', label: 'Transaksi', icon: markRaw(FileText) },
  { path: '/notification', label: 'Notifikasi', icon: markRaw(Bell) },
]

const adminItems = [
  { path: '/', label: 'Dashboard', icon: markRaw(LayoutGrid) },
  { path: '/gates-status', label: 'Gate Status', icon: markRaw(Activity) },
  { path: '/transaksi', label: 'Transaksi', icon: markRaw(FileText) },
  { path: '/member', label: 'Member', icon: markRaw(Users) },
  { path: '/shifts-schedule', label: 'Jadwal Shift', icon: markRaw(CalendarDays) },
  { path: '/personnel', label: 'Personil', icon: markRaw(UserCog) },
  { path: '/report', label: 'Laporan', icon: markRaw(BarChart3) },
  { path: '/notification', label: 'Notifikasi', icon: markRaw(Bell) },
  { path: '/setting', label: 'Pengaturan', icon: markRaw(Settings) },
  { path: '/device', label: 'Perangkat', icon: markRaw(Cpu) },
  { path: '/setup', label: 'Setup', icon: markRaw(Wrench) },
]

const visibleItems = computed(() =>
  authStore.isAdmin ? adminItems : operatorItems,
)

const pageTitle = computed(() => {
  const titles = {
    '/': 'Dashboard',
    '/pos': 'POS — Gate Out',
    '/gate-in': 'Gate In Monitor',
    '/gates-status': 'Gate Status',
    '/transaksi': 'Transaksi',
    '/shifts-schedule': 'Jadwal Shift',
    '/personnel': 'Personil',
    '/setting': 'Pengaturan',
    '/device': 'Perangkat',
    '/setup': 'Setup',
    '/member': 'Member',
    '/report': 'Laporan',
    '/notification': 'Notifikasi',
    '/login': 'Login',
  }
  return titles[route.path] || 'E-Parking'
})

const avatarInitial = computed(() => {
  const name = authStore.user?.username || '?'
  return name.charAt(0).toUpperCase()
})

function isActive(path) {
  if (path === '/') return route.path === '/'
  if (path === '/pos') return route.path === '/pos'
  return route.path.startsWith(path)
}

function updateClock() {
  clock.value = new Date().toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})

async function logout() {
  await authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.fade-text-enter-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.fade-text-leave-active { transition: opacity 0.1s ease, transform 0.1s ease; }
.fade-text-enter-from { opacity: 0; transform: translateX(-4px); }
.fade-text-leave-to { opacity: 0; transform: translateX(-4px); }
</style>
