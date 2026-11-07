<template>
  <button
    type="button"
    class="flex h-9 w-9 items-center justify-center rounded-md transition-colors duration-150"
    :title="label"
    :aria-label="label"
    @mousedown.prevent
    @click="toggleTheme"
  >
    <component :is="theme === 'dark' ? Sun : Moon" class="h-[18px] w-[18px]" />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { Moon, Sun } from 'lucide-vue-next'

const { theme, toggleTheme } = useTheme()
const label = computed(() => (theme.value === 'dark' ? 'Tema terang' : 'Tema gelap'))
</script>
