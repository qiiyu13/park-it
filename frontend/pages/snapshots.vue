<template>
  <div class="mx-auto max-w-7xl space-y-5">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs font-semibold text-muted-foreground">Log</p>
        <h2 class="mt-1 text-2xl font-semibold tracking-tight text-foreground">Arsip Snapshot</h2>
        <p class="mt-1 text-sm text-muted-foreground">
          {{ stats.count }} snapshot · {{ formatSize(stats.total_size) }}
          <span v-if="retentionLabel"> · {{ retentionLabel }} · berjalan otomatis tiap hari 03:30</span>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <NuxtLink to="/setting" class="text-sm font-medium text-info hover:underline">Atur Hapus Otomatis</NuxtLink>
      </div>
    </header>

    <!-- Filters -->
    <div class="grid gap-2 rounded-lg border border-border bg-surface p-3 shadow-brutal-sm md:grid-cols-6">
      <label class="text-xs font-semibold text-muted-foreground">
        Dari
        <input v-model="filters.date_from" type="date" class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
      </label>
      <label class="text-xs font-semibold text-muted-foreground">
        Sampai
        <input v-model="filters.date_to" type="date" class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
      </label>
      <label class="text-xs font-semibold text-muted-foreground">
        Gate
        <select v-model="filters.gate_id" class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
          <option value="">Semua</option>
          <option v-for="g in gates" :key="g.id" :value="g.id">{{ g.code }} · {{ g.name }}</option>
        </select>
      </label>
      <label class="text-xs font-semibold text-muted-foreground">
        Tipe
        <select v-model="filters.snapshot_type" class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
          <option value="">Semua</option>
          <option value="entry">Masuk</option>
          <option value="exit">Keluar</option>
        </select>
      </label>
      <label class="text-xs font-semibold text-muted-foreground">
        Cari plat / barcode
        <input v-model="filters.q" type="text" placeholder="mis. H1234 atau 65151" class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground" @keydown.enter="applyFilters">
      </label>
      <div class="flex items-end gap-2">
        <Button class="w-full" @click="applyFilters">Terapkan</Button>
        <Button variant="ghost" @click="resetFilters">Reset</Button>
      </div>
    </div>

    <!-- Grid -->
    <div v-if="loading" class="text-sm text-muted-foreground">Memuat snapshot…</div>
    <div v-else-if="items.length === 0" class="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
      Tidak ada snapshot pada filter ini.
    </div>
    <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      <div
        v-for="item in items"
        :key="item.id"
        class="group overflow-hidden rounded-lg border border-border bg-surface shadow-brutal-sm"
      >
        <button type="button" class="block w-full" @click="openViewer(item)">
          <img :src="item.image_url" :alt="item.filename" class="aspect-video w-full object-cover" loading="lazy">
        </button>
        <div class="space-y-1 p-2.5">
          <div class="flex items-center justify-between text-[11px] font-semibold">
            <span class="rounded bg-muted px-1.5 py-0.5 uppercase tracking-wide text-muted-foreground">
              {{ item.snapshot_type === 'entry' ? 'Masuk' : 'Keluar' }}
            </span>
            <span class="text-muted-foreground">{{ item.gate_code || '-' }}</span>
          </div>
          <div class="font-mono text-sm font-semibold text-foreground">
            {{ item.plate_number || item.barcode || '—' }}
          </div>
          <div class="text-[11px] text-muted-foreground">
            {{ formatDateTime(item.created_at) }} · {{ item.camera_name || 'kamera' }}
          </div>
          <div class="flex items-center justify-between pt-0.5">
            <span class="text-[11px] text-muted-foreground">{{ formatSize(item.file_size) }}</span>
            <button
              v-if="authStore.isAdmin"
              type="button"
              class="text-[11px] font-semibold text-destructive hover:underline"
              @click="remove(item)"
            >
              Hapus
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div class="flex items-center justify-between text-sm">
      <span class="text-muted-foreground">Halaman {{ page }} / {{ totalPages }}</span>
      <div class="flex gap-2">
        <Button variant="outline" :disabled="page <= 1" @click="goPage(page - 1)">Sebelumnya</Button>
        <Button variant="outline" :disabled="page >= totalPages" @click="goPage(page + 1)">Berikutnya</Button>
      </div>
    </div>

    <!-- Viewer -->
    <Teleport to="body">
      <div v-if="viewer" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" @click.self="viewer = null">
        <div class="max-h-full w-full max-w-5xl overflow-hidden rounded-xl border border-border bg-surface shadow-brutal-lg">
          <div class="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
            <div class="text-sm font-semibold text-foreground">
              {{ viewer.gate_name || viewer.gate_code }}
              <span class="font-normal text-muted-foreground">· {{ formatDateTime(viewer.created_at) }}</span>
            </div>
            <div class="flex items-center gap-2">
              <a :href="viewer.image_url" :download="viewer.filename" class="text-xs font-semibold text-info hover:underline">Unduh</a>
              <button type="button" class="text-sm font-semibold text-muted-foreground hover:text-foreground" @click="viewer = null">Tutup</button>
            </div>
          </div>
          <img :src="viewer.image_url" :alt="viewer.filename" class="max-h-[75vh] w-full bg-black object-contain">
          <div class="flex flex-wrap items-center gap-4 px-4 py-2.5 text-xs text-muted-foreground">
            <span>Plat: <span class="font-mono text-foreground">{{ viewer.plate_number || '—' }}</span></span>
            <span>Barcode: <span class="font-mono text-foreground">{{ viewer.barcode || '—' }}</span></span>
            <span>Kamera: {{ viewer.camera_name || '—' }}</span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Button } from '~/components/ui/button'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()
const authStore = useAuthStore()

const items = ref([])
const gates = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 24
const total = ref(0)
const stats = ref({ count: 0, total_size: 0 })
const viewer = ref(null)
const retentionMonths = ref(null)

const filters = reactive({
  date_from: '',
  date_to: '',
  gate_id: '',
  snapshot_type: '',
  q: '',
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const retentionLabel = computed(() => {
  const months = retentionMonths.value
  if (months === null) return ''
  if (months === 0) return 'Hapus Otomatis mati — snapshot disimpan selamanya'
  return `Hapus Otomatis: simpan ${months} bulan`
})

function formatSize(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDateTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize),
    })
    if (filters.date_from) params.set('date_from', filters.date_from)
    if (filters.date_to) params.set('date_to', filters.date_to)
    if (filters.gate_id) params.set('gate_id', filters.gate_id)
    if (filters.snapshot_type) params.set('snapshot_type', filters.snapshot_type)
    if (filters.q.trim()) params.set('q', filters.q.trim())
    const res = await fetchApi(`/api/snapshots?${params.toString()}`)
    items.value = res.items || []
    total.value = res.total || 0
    stats.value = res.stats || { count: res.total || 0, total_size: 0 }
  } catch (err) {
    console.error(err)
  } finally {
    loading.value = false
  }
}

async function loadGates() {
  try {
    gates.value = await fetchApi('/api/gates') || []
  } catch {
    gates.value = []
  }
}

async function loadRetention() {
  try {
    const rows = await fetchApi('/api/settings')
    const row = (rows || []).find((r) => r.key === 'snapshot_keep_months')
    const n = row ? Number(row.value) : NaN
    retentionMonths.value = Number.isFinite(n) ? n : 6
  } catch {
    retentionMonths.value = null
  }
}

function applyFilters() {
  page.value = 1
  load()
}

function resetFilters() {
  filters.date_from = ''
  filters.date_to = ''
  filters.gate_id = ''
  filters.snapshot_type = ''
  filters.q = ''
  applyFilters()
}

function goPage(next) {
  page.value = next
  load()
}

function openViewer(item) {
  viewer.value = item
}

async function remove(item) {
  if (!confirm(`Hapus snapshot ${item.filename}?`)) return
  try {
    await fetchApi(`/api/snapshots/${item.id}`, { method: 'DELETE' })
    items.value = items.value.filter((x) => x.id !== item.id)
    total.value = Math.max(0, total.value - 1)
    stats.value = { ...stats.value, count: Math.max(0, stats.value.count - 1) }
    if (viewer.value?.id === item.id) viewer.value = null
  } catch (err) {
    alert(err?.data?.detail || err.message || 'Gagal menghapus snapshot')
  }
}


onMounted(async () => {
  await Promise.all([load(), loadGates(), loadRetention()])
})
</script>
