<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" tabindex="-1" @keydown.esc="close">
      <form class="w-full max-w-md rounded-xl border border-border bg-surface p-7 shadow-brutal-lg" @submit.prevent="onSubmit">
        <div class="text-xs font-semibold text-muted-foreground">Otorisasi Supervisor</div>
        <h2 class="mt-1 text-2xl font-semibold tracking-tight text-foreground">Buka Palang Manual</h2>
        <p class="mt-2 text-sm text-muted-foreground">
          {{ gateName || 'Gate keluar' }} — untuk tiket hilang, sensor gagal, atau uji palang. Semua pembukaan tercatat di audit.
        </p>

        <label class="mt-5 block text-xs font-semibold text-muted-foreground">Username supervisor/admin</label>
        <input
          ref="usernameInput"
          v-model="username"
          autocomplete="username"
          class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-base text-foreground outline-none focus:border-primary"
        >

        <label class="mt-4 block text-xs font-semibold text-muted-foreground">Password</label>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-base text-foreground outline-none focus:border-primary"
        >

        <label class="mt-4 block text-xs font-semibold text-muted-foreground">Keterangan (opsional)</label>
        <input
          v-model="reason"
          class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-base text-foreground outline-none focus:border-primary"
          placeholder="mis. tiket hilang / uji palang"
        >

        <p v-if="error" class="mt-3 text-sm font-medium text-destructive">{{ error }}</p>

        <div class="mt-6 flex items-center justify-end gap-2">
          <button type="button" class="pos-btn" @click="close">Batal</button>
          <button type="submit" class="pos-btn pos-btn-primary" :disabled="loading || !username || !password">
            {{ loading ? 'Memproses…' : 'Buka Palang' }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  gateName: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['update:open', 'confirm'])

const username = ref('')
const password = ref('')
const reason = ref('')
const usernameInput = ref(null)

watch(() => props.open, async (open) => {
  if (!open) return
  username.value = ''
  password.value = ''
  reason.value = ''
  await nextTick()
  usernameInput.value?.focus()
})

function close() {
  emit('update:open', false)
}

function onSubmit() {
  if (props.loading || !username.value || !password.value) return
  emit('confirm', {
    username: username.value.trim(),
    password: password.value,
    reason: reason.value.trim() || 'manual open dari POS',
  })
}
</script>
