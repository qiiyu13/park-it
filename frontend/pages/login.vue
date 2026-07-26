<template>
  <div class="flex min-h-screen items-center justify-center bg-background relative overflow-hidden">
    <!-- Background grid -->
    <div class="pointer-events-none absolute inset-0">
      <div class="absolute inset-0 opacity-[0.08]" style="background-image: linear-gradient(rgba(26,26,26,1) 2px, transparent 2px), linear-gradient(90deg, rgba(26,26,26,1) 2px, transparent 2px); background-size: 60px 60px;" />
    </div>

    <!-- Login card -->
    <div class="relative z-10 w-full max-w-sm border-4 border-foreground bg-surface p-8 shadow-brutal-lg">
      <!-- Header -->
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center border-4 border-foreground bg-primary text-foreground shadow-brutal">
          <BrandIcon class="h-7 w-7" />
        </div>
        <h1 class="text-3xl font-black uppercase tracking-wide text-foreground">E-Parking v2</h1>
        <p class="text-sm font-medium text-muted-foreground">Sistem Manajemen Parkir</p>
      </div>

      <!-- Form -->
      <form class="space-y-4" @submit.prevent="handleLogin">
        <div class="space-y-2">
          <label class="text-sm font-bold uppercase tracking-wide text-foreground">Username</label>
          <Input
            v-model="form.username"
            placeholder="Masukkan username"
            class="h-10"
            autofocus
          />
        </div>

        <div class="space-y-2">
          <label class="text-sm font-bold uppercase tracking-wide text-foreground">Password</label>
          <Input
            v-model="form.password"
            type="password"
            placeholder="Masukkan password"
            class="h-10"
          />
        </div>

        <Button
          type="submit"
          class="w-full h-10"
          :disabled="authStore.isLoading"
        >
          {{ authStore.isLoading ? 'Memproses...' : 'Masuk' }}
        </Button>

        <Transition name="fade">
          <div
            v-if="authStore.error"
            class="flex items-center gap-2 border-2 border-foreground bg-destructive p-3 text-sm font-bold text-white shadow-brutal-sm"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="10" /><path d="M15 9l-6 6M9 9l6 6" />
            </svg>
            {{ authStore.error }}
          </div>
        </Transition>
      </form>

      <!-- Help text -->
      <p class="mt-5 text-center text-xs font-medium text-muted-foreground">
        Lupa password? Hubungi administrator.
      </p>

      <!-- Footer -->
      <div class="mt-4 border-t-2 border-foreground pt-4 text-center text-xs font-bold uppercase text-muted-foreground">
        PT Mitra Teknik &copy; {{ new Date().getFullYear() }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'

definePageMeta({
  layout: false,
  middleware: 'auth',
})

const authStore = useAuthStore()
const router = useRouter()

const form = reactive({
  username: '',
  password: '',
})

async function handleLogin() {
  if (!form.username || !form.password) return

  try {
    await authStore.login(form.username, form.password)
    router.push(authStore.isAdmin ? '/' : '/pos')
  } catch {
    // Error is stored in authStore.error
  }
}
</script>

<style scoped>
.fade-enter-active { transition: all 0.3s ease; }
.fade-leave-active { transition: all 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
