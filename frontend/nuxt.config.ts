import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  devtools: { enabled: true },

  // Compatibility
  compatibilityDate: '2025-04-25',

  // Runtime config
  // NOTE: In production, set NUXT_PUBLIC_API_BASE_URL="" for relative URLs
  // through nginx. The default below is for development only.
  runtimeConfig: {
    public: {
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
      wsBaseUrl: process.env.NUXT_PUBLIC_WS_BASE_URL || 'ws://localhost:8000',
      boothBridgeUrl: process.env.NUXT_PUBLIC_BOOTH_BRIDGE_URL || 'ws://localhost:5678/',
    },
  },

  // CSS — self-hosted fonts (offline-safe) + Tailwind v4
  css: [
    '~/assets/css/fonts.css',
    '~/assets/css/tailwind.css',
  ],

  // Modules
  modules: [
    '@pinia/nuxt',
    'shadcn-nuxt',
    '@nuxt/eslint',
  ],

  // Pinia
  pinia: {
    storesDirs: ['./stores/**'],
  },

  // shadcn-vue
  shadcn: {
    prefix: '',
    componentDir: './components/ui',
  },

  // Vite — Tailwind v4 plugin
  vite: {
    plugins: [
      tailwindcss(),
    ],
  },

  // Nitro / server
  nitro: {
    preset: 'node-server',
    // Pre-compress static assets at build time (gzip + brotli). Nitro serves the
    // precompressed variant when the client sends Accept-Encoding. Pure transfer
    // win — no runtime/behavior change. Harmless if nginx already compresses.
    compressPublicAssets: { gzip: true, brotli: true },
  },

  // App
  app: {
    head: {
      title: 'E-Parking v2',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        // Fonts are self-hosted via @fontsource (see assets/css/fonts.css) —
        // no external CDN so the app renders fully offline / on isolated LAN.
      ],
    },
  },
})
