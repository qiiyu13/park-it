<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
  <!-- Global toast surface — registered by plugins/toast.client.js. -->
  <Toaster
    position="top-center"
    rich-colors
    :theme="theme"
    close-button
  />
</template>

<script setup>
import { onMounted } from 'vue'
import { Toaster } from 'vue-sonner'

const { theme, loadTheme } = useTheme()
onMounted(loadTheme)

useHead({
  titleTemplate: (title) => (title ? `${title} — E-Parking v2` : 'E-Parking v2'),
})
</script>
