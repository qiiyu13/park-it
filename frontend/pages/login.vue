<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-background">
    <!-- Quiet infrastructure grid + amber wash -->
    <div class="pointer-events-none absolute inset-0">
      <div
        class="absolute inset-0 opacity-40"
        style="background-image: linear-gradient(var(--border-default) 1px, transparent 1px), linear-gradient(90deg, var(--border-default) 1px, transparent 1px); background-size: 48px 48px;"
      />
      <div class="absolute -right-32 -top-40 h-96 w-96 rounded-full bg-primary/15 blur-3xl" />
    </div>

    <!-- Login card -->
    <div class="relative z-10 w-full max-w-sm rounded-xl border border-border bg-surface/95 p-8 shadow-brutal-lg backdrop-blur">
      <!-- Header -->
      <div class="mb-8">
        <div class="mb-5 flex h-12 w-12 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <BrandIcon class="h-6 w-6" />
        </div>
        <h1 class="text-2xl font-semibold tracking-tight text-foreground">E-Parking v2</h1>
        <p class="mt-1 text-sm text-muted-foreground">Sistem manajemen parkir</p>
      </div>

      <!-- Form -->
      <form class="space-y-4" @submit.prevent="handleLogin">
        <div class="space-y-2">
          <label class="text-xs font-semibold text-foreground">Username</label>
          <Input
            v-model="form.username"
            placeholder="Masukkan username"
            class="h-11"
            autofocus
          />
        </div>

        <div class="space-y-2">
          <label class="text-xs font-semibold text-foreground">Password</label>
          <Input
            v-model="form.password"
            type="password"
            placeholder="Masukkan password"
            class="h-11"
          />
        </div>

        <Button
          type="submit"
          class="h-11 w-full"
          :disabled="authStore.isLoading"
        >
          {{ authStore.isLoading ? 'Memproses...' : 'Masuk' }}
        </Button>

        <Transition name="fade">
          <div
            v-if="authStore.error"
            class="flex items-center gap-2 rounded-md border border-destructive/25 bg-destructive/10 p-3 text-sm font-medium text-destructive"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="10" /><path d="M15 9l-6 6M9 9l6 6" />
            </svg>
            {{ authStore.error }}
          </div>
        </Transition>
      </form>

      <!-- Help text -->
      <p class="mt-5 text-center text-xs text-muted-foreground">
        Lupa password? Hubungi administrator.
      </p>

      <!-- Footer -->
      <div class="mt-5 border-t border-border pt-4 text-center text-xs text-muted-foreground">
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
