<template>
  <Dialog :open="open" @update:open="$emit('update:open', $event)">
    <DialogContent class="max-w-sm">
      <DialogHeader>
        <DialogTitle>Pembayaran RFID</DialogTitle>
      </DialogHeader>

      <div class="space-y-4">
        <div class="rounded-lg border border-border bg-surface p-3 text-center">
          <div class="text-sm font-medium text-muted-foreground">
            Scan kartu RFID member atau ketik nomor kartu secara manual
          </div>
        </div>

        <div class="space-y-2">
          <label class="text-sm font-medium text-foreground">Nomor Kartu RFID</label>
          <Input
            ref="cardInput"
            v-model="cardNumber"
            class="h-12 text-lg font-mono font-semibold tracking-wider"
            placeholder="Scan atau ketik nomor kartu"
            @keydown.enter="onConfirm"
          />
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="$emit('update:open', false)">Batal</Button>
        <Button
          :disabled="!cardNumber.trim()"
          class="bg-rfid hover:bg-rfid/90 text-on-solid"
          @click="onConfirm"
        >
          Proses
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '~/components/ui/dialog'

const props = defineProps({
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['update:open', 'confirm'])

const cardInput = ref(null)
const cardNumber = ref('')

function onConfirm() {
  if (cardNumber.value.trim()) {
    emit('confirm', cardNumber.value.trim())
    emit('update:open', false)
    cardNumber.value = ''
  }
}

watch(() => props.open, (val) => {
  if (val) {
    cardNumber.value = ''
    nextTick(() => cardInput.value?.$el?.querySelector('input')?.focus())
  }
})
</script>
