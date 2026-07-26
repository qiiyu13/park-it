<template>
  <div class="space-y-4">
    <div v-if="loading" class="flex items-center gap-3 text-sm text-muted-foreground">
      <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" class="opacity-25" />
        <path d="M22 12a10 10 0 0 1-10 10" />
      </svg>
      Memvalidasi token setup…
    </div>

    <div v-else-if="error" class="rounded-lg border border-destructive/30 bg-destructive/10 p-4">
      <p class="font-medium text-destructive">Token setup ditolak</p>
      <p class="mt-1 text-sm text-destructive/90">{{ error }}</p>
      <p class="mt-3 text-xs text-muted-foreground">
        Jalankan ulang installer di server untuk mendapatkan token baru.
      </p>
    </div>

    <form v-else class="space-y-3" @submit.prevent="handleSubmit">
      <p class="text-sm text-muted-foreground">
        Tempel token setup yang ditampilkan oleh installer.
      </p>
      <Input v-model="manualToken" placeholder="Token setup…" autofocus class="font-mono" />
      <Button type="submit" class="w-full" :disabled="!manualToken">
        Lanjut →
      </Button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'

defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['submit'])
const manualToken = ref('')

function handleSubmit() {
  if (!manualToken.value) return
  emit('submit', manualToken.value.trim())
}
</script>
