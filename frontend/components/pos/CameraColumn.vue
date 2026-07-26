<template>
  <div class="flex flex-col gap-2">
    <!-- Skeleton slots when no cameras configured -->
    <template v-if="slots.length === 0">
      <div
        v-for="n in placeholderCount"
        :key="`skeleton-${n}`"
        class="w-full aspect-video relative overflow-hidden rounded-lg border border-border/20 bg-muted/10"
      >
        <div class="w-full h-full flex flex-col items-center justify-center gap-2">
          <Camera class="h-8 w-8 text-muted-foreground/15" />
          <span class="text-[10px] text-muted-foreground/20">Kamera {{ n }}</span>
        </div>
      </div>
    </template>

    <!-- Live camera slots -->
    <template v-else>
      <div
        v-for="(cam, i) in slots"
        :key="i"
        class="w-full aspect-video relative overflow-hidden rounded-lg bg-black border border-border/40"
      >
        <img
          v-if="cam.url && !imgErrors[i]"
          :src="imgSrcs[i]"
          :alt="cam.label || `Kamera ${i + 1}`"
          class="w-full h-full object-cover"
          @error="imgErrors[i] = true"
        >
        <div
          v-else
          class="w-full h-full flex flex-col items-center justify-center gap-2 text-muted-foreground/20"
        >
          <CameraOff class="h-8 w-8" />
          <span class="text-xs">Tidak ada sinyal</span>
        </div>
        <div
          v-if="cam.label"
          class="absolute bottom-1.5 left-1.5 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded"
        >
          {{ cam.label }}
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Camera, CameraOff } from 'lucide-vue-next'

const props = defineProps({
  cameras: { type: Array, default: () => [] },
  placeholderCount: { type: Number, default: 2 },
  refreshIntervalMs: { type: Number, default: 2000 },
})

const slots = computed(() => props.cameras)

const imgSrcs = ref([])
const imgErrors = ref([])
let refreshTimer = null

function buildSrc(url) {
  return `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`
}

function refreshImages() {
  props.cameras.forEach((cam, i) => {
    if (cam.url && !imgErrors.value[i]) {
      imgSrcs.value[i] = buildSrc(cam.url)
    }
  })
}

watch(
  () => props.cameras,
  (cams) => {
    imgErrors.value = cams.map(() => false)
    imgSrcs.value = cams.map((c) => (c.url ? buildSrc(c.url) : null))
  },
  { immediate: true },
)

onMounted(() => {
  refreshTimer = setInterval(refreshImages, props.refreshIntervalMs)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>
