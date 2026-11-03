<template>
  <div class="min-h-screen bg-background flex items-center justify-center p-4 sm:p-6">
    <div class="w-full max-w-3xl">
      <div class="overflow-hidden rounded-xl border border-border bg-surface shadow-brutal-lg">
        <!-- Top bar -->
        <header class="flex h-16 items-center justify-between border-b border-border px-6">
          <div class="flex items-center gap-3">
            <div class="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BrandIcon class="h-5 w-5" />
            </div>
            <div>
              <h1 class="text-sm font-semibold tracking-tight text-foreground">E-Parking Setup</h1>
              <p class="text-xs text-muted-foreground">Bantu kami menyiapkan sistem ini</p>
            </div>
          </div>
          <div class="flex items-center gap-3 text-xs font-medium text-muted-foreground">
            <span>Langkah {{ currentIndex + 1 }} dari {{ steps.length }}</span>
            <button
              type="button"
              class="rounded-md border border-border bg-surface p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
              aria-label="Bantuan"
              @click="$emit('help')"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01" />
              </svg>
            </button>
          </div>
        </header>

        <!-- Stepper -->
        <div class="border-b border-border bg-surface-hover/40 px-6 py-3">
          <SetupStepper :steps="steps" :current-index="currentIndex" @navigate="(i) => $emit('navigate', i)" />
        </div>

        <!-- Body -->
        <main class="min-h-[480px] px-6 py-8">
          <Transition name="step" mode="out-in">
            <div :key="currentIndex">
              <slot />
            </div>
          </Transition>
        </main>

        <!-- Footer -->
        <footer class="flex h-16 items-center justify-between border-t border-border px-6">
          <Button
            variant="ghost"
            :disabled="currentIndex === 0 || busy"
            @click="$emit('back')"
          >
            ← Kembali
          </Button>

          <div class="text-xs font-medium text-muted-foreground">
            <span v-if="autosavedLabel">{{ autosavedLabel }}</span>
          </div>

          <Button
            v-if="!finalStep"
            :disabled="!canAdvance || busy"
            @click="$emit('next')"
          >
            {{ busy ? 'Memproses…' : 'Lanjut →' }}
          </Button>
          <Button
            v-else
            variant="default"
            :disabled="!canAdvance || busy"
            class="bg-success text-white hover:bg-success/90"
            @click="$emit('finalize')"
          >
            {{ busy ? 'Menyelesaikan…' : 'Aktifkan Gate & Selesai' }}
          </Button>
        </footer>
      </div>

      <p class="mt-3 text-center text-xs font-medium text-muted-foreground">
        Konfigurasi tersimpan otomatis. Boleh tutup tab; lanjutkan dari langkah ini kapan saja.
      </p>
    </div>
  </div>
</template>

<script setup>
import { Button } from '~/components/ui/button'
import SetupStepper from '~/components/setup/SetupStepper.vue'

defineProps({
  steps: { type: Array, required: true },
  currentIndex: { type: Number, default: 0 },
  canAdvance: { type: Boolean, default: true },
  busy: { type: Boolean, default: false },
  autosavedLabel: { type: String, default: '' },
  finalStep: { type: Boolean, default: false },
})

defineEmits(['next', 'back', 'navigate', 'finalize', 'help'])
</script>

<style scoped>
.step-enter-active,
.step-leave-active {
  transition: opacity 200ms ease, transform 200ms ease;
}
.step-enter-from { opacity: 0; transform: translateX(8px); }
.step-leave-to { opacity: 0; transform: translateX(-8px); }
@media (prefers-reduced-motion: reduce) {
  .step-enter-active,
  .step-leave-active { transition: opacity 120ms ease; }
  .step-enter-from,
  .step-leave-to { transform: none; }
}
</style>
