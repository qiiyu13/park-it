<template>
  <div class="grid grid-cols-2 gap-3 h-full">
    <!-- Entry photo -->
    <div
      class="relative cursor-pointer overflow-hidden rounded-lg border border-border bg-surface"
      @click="entryPhotoUrl && (fullscreenPhoto = 'entry')"
    >
      <img
        v-if="entryPhotoUrl"
        :src="entryPhotoUrl"
        alt="Foto Masuk"
        class="h-full w-full object-cover"
        @error="$event.target.style.display = 'none'"
      >
      <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground/30">
        <Camera class="h-8 w-8" />
        <span class="text-xs font-medium">Foto Masuk</span>
      </div>
      <div v-if="entryPhotoUrl" class="absolute bottom-0 left-0 right-0 bg-black/60 px-2.5 py-1.5 text-xs text-white">
        <span v-if="entryTime">{{ formatTime(entryTime) }}</span>
        <span v-if="entryGateName" class="ml-1.5 opacity-70">@ {{ entryGateName }}</span>
      </div>
    </div>

    <!-- Exit photo -->
    <div
      class="relative cursor-pointer overflow-hidden rounded-lg border border-border bg-surface"
      @click="exitPhotoUrl && (fullscreenPhoto = 'exit')"
    >
      <img
        v-if="exitPhotoUrl"
        :src="exitPhotoUrl"
        alt="Foto Keluar"
        class="h-full w-full object-cover"
        @error="$event.target.style.display = 'none'"
      >
      <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground/30">
        <Camera class="h-8 w-8" />
        <span class="text-xs font-medium">Foto Keluar</span>
      </div>
    </div>

    <!-- Fullscreen dialog -->
    <Dialog :open="showFullscreen" @update:open="(v) => { if (!v) fullscreenPhoto = null }">
      <DialogContent class="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{{ fullscreenPhoto === 'entry' ? 'Foto Masuk' : 'Foto Keluar' }}</DialogTitle>
        </DialogHeader>
        <img
          :src="fullscreenPhoto === 'entry' ? entryPhotoUrl : exitPhotoUrl"
          class="w-full rounded-lg"
        >
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Camera } from 'lucide-vue-next'
import { useFormatters } from '~/composables/useFormatters'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog'

defineProps({
  entryPhotoUrl: { type: String, default: null },
  exitPhotoUrl: { type: String, default: null },
  entryTime: { type: String, default: null },
  entryGateName: { type: String, default: null },
  showEmptyState: { type: Boolean, default: false },
})

const { formatTime } = useFormatters()

const fullscreenPhoto = ref(null) // null | 'entry' | 'exit'
const showFullscreen = computed(() => fullscreenPhoto.value !== null)
</script>
