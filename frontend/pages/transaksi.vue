<template>
  <div>
    <PageHeader title="Transaksi" subtitle="Riwayat transaksi parkir dan log peristiwa." />

    <TabStrip v-model="activeTab" :tabs="tabs" />

    <!-- Transactions tab -->
    <div v-if="activeTab === 'transactions'">
      <div class="mb-4 flex items-center gap-3">
        <input
          v-model="dateFrom"
          type="date"
          class="border-2 border-foreground bg-surface px-3 py-2 text-sm font-medium text-foreground shadow-brutal-sm"
        >
        <span class="font-bold text-foreground">s/d</span>
        <input
          v-model="dateTo"
          type="date"
          class="border-2 border-foreground bg-surface px-3 py-2 text-sm font-medium text-foreground shadow-brutal-sm"
        >
        <select
          v-model="statusFilter"
          class="border-2 border-foreground bg-surface px-3 py-2 text-sm font-medium text-foreground shadow-brutal-sm"
        >
          <option value="">Semua Status</option>
          <option value="ACTIVE">Aktif</option>
          <option value="COMPLETED">Selesai</option>
          <option value="LOST_CONTACT">Lost Contact</option>
        </select>
        <Button size="sm" @click="applyTransactionFilter">Filter</Button>
      </div>
      <DataTable
        :data="transactions"
        :columns="transactionColumns"
        :loading="loadingTransactions"
        :show-add="false"
        :show-edit="false"
        :show-delete="false"
        server-pagination
        :total-items="transactionTotal"
        @page-change="handleTransactionPageChange"
        @size-change="handleTransactionSizeChange"
      />
    </div>

    <!-- Manual Opens tab -->
    <div v-if="activeTab === 'manual-opens'">
      <DataTable
        :data="manualOpens"
        :columns="manualOpenColumns"
        :loading="loadingManualOpens"
        :show-add="false"
        :show-edit="false"
        :show-delete="false"
      />
    </div>

    <!-- Abandoned tab -->
    <div v-if="activeTab === 'abandoned'">
      <DataTable
        :data="abandonedVehicles"
        :columns="abandonedColumns"
        :loading="loadingAbandoned"
        :show-add="false"
        :show-edit="false"
        :show-delete="false"
      />
    </div>
  </div>
</template>

<script setup>
import { toast } from 'vue-sonner'
import { Button } from '~/components/ui/button'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()

// Gate id/code → name lookup so log tables show "Gate Keluar 1" not "5"/"GOUT-01".
const gateNameMap = ref({})
function gateLabel(v) {
  return gateNameMap.value[v] ?? (v ?? '-')
}
async function loadGateNames() {
  try {
    const res = await fetchApi('/api/gates')
    const rows = Array.isArray(res) ? res : (res?.items ?? [])
    const map = {}
    for (const g of rows) {
      map[g.id] = g.name
      if (g.code) map[g.code] = g.name
    }
    gateNameMap.value = map
  } catch { /* non-fatal; columns fall back to raw value */ }
}
onMounted(loadGateNames)

const tabs = [
  { key: 'transactions', label: 'Transaksi Parkir' },
  { key: 'manual-opens', label: 'Buka Manual' },
  { key: 'abandoned', label: 'Kendaraan Ditinggal' },
]

const activeTab = ref('transactions')
const loadingTransactions = ref(false)
const loadingManualOpens = ref(false)
const loadingAbandoned = ref(false)

const dateFrom = ref('')
const dateTo = ref('')
const statusFilter = ref('')

// Local YYYY-MM-DD. NEVER use toISOString() here: it converts to UTC, so in
// positive-offset zones (e.g. WIB UTC+7) midnight-local rolls back a day and
// the picker shows the previous day (the "stuck on April" bug).
function localDate(d = new Date()) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// Default range = today only (00:00 → end of today). Recomputed every page
// load, so it always tracks the current date.
dateFrom.value = localDate()
dateTo.value = localDate()

const transactions = ref([])
const transactionTotal = ref(0)
const transactionPage = ref(1)
const transactionPageSize = ref(20)
const transactionColumns = [
  { prop: 'barcode', label: 'Barcode', width: 140, sortable: true },
  { prop: 'vehicle_type_name', label: 'Jenis', width: 100 },
  { prop: 'entry_time', label: 'Masuk', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
  { prop: 'exit_time', label: 'Keluar', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
  { prop: 'duration_minutes', label: 'Durasi (menit)', width: 120 },
  { prop: 'payment_method', label: 'Metode', width: 110 },
  { prop: 'fee', label: 'Tarif', width: 120, formatter: (v) => v ? `Rp ${v.toLocaleString()}` : '-' },
  { prop: 'status', label: 'Status', width: 120, type: 'enum' },
]

const manualOpens = ref([])
const manualOpenColumns = [
  { prop: 'gate_id', label: 'Gate', width: 140, formatter: (v) => gateLabel(v) },
  { prop: 'gate_type', label: 'Tipe', width: 100 },
  { prop: 'reason', label: 'Alasan' },
  { prop: 'notes', label: 'Catatan' },
]

const abandonedVehicles = ref([])
const abandonedColumns = [
  { prop: 'gate_out_id', label: 'Gate Keluar', width: 140, formatter: (v) => gateLabel(v) },
  { prop: 'waiting_seconds', label: 'Tunggu (detik)', width: 130, sortable: true },
  { prop: 'resolution_type', label: 'Resolusi', width: 150, type: 'enum' },
  { prop: 'notes', label: 'Catatan' },
]

// Lazy-load tabs: fetch only on first activation, cache thereafter.
const _loaded = reactive({ transactions: false, 'manual-opens': false, abandoned: false })

watch(
  activeTab,
  (tab) => {
    if (_loaded[tab]) return
    if (tab === 'transactions') loadTransactions()
    else if (tab === 'manual-opens') loadManualOpens()
    else if (tab === 'abandoned') loadAbandoned()
    _loaded[tab] = true
  },
  { immediate: true },
)

async function loadTransactions() {
  loadingTransactions.value = true
  try {
    const params = {
      skip: (transactionPage.value - 1) * transactionPageSize.value,
      limit: transactionPageSize.value,
    }
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    if (statusFilter.value) params.status = statusFilter.value
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.append(k, v)
    }
    // Backend returns {items, total, skip, limit} — see
    // api/app/routes/transactions.py::TransactionListResponse.
    const result = await fetchApi(`/api/transactions?${qs.toString()}`)
    transactions.value = result.items ?? []
    transactionTotal.value = typeof result.total === 'number' ? result.total : transactions.value.length
  } catch (err) {
    toast.error(`Gagal memuat transaksi: ${err.message}`)
  } finally {
    loadingTransactions.value = false
  }
}

// Applying a new filter must reset to page 1, otherwise a narrower result set
// can leave the operator stranded on an out-of-range (empty) page.
function applyTransactionFilter() {
  transactionPage.value = 1
  loadTransactions()
}

function handleTransactionPageChange(page, size) {
  transactionPage.value = page
  transactionPageSize.value = size
  loadTransactions()
}

function handleTransactionSizeChange(page, size) {
  transactionPage.value = page
  transactionPageSize.value = size
  loadTransactions()
}

async function loadManualOpens() {
  loadingManualOpens.value = true
  try {
    const result = await fetchApi('/api/manual-open-logs')
    manualOpens.value = result.items || []
  } catch (err) {
    toast.error(`Gagal memuat log buka manual: ${err.message}`)
  } finally {
    loadingManualOpens.value = false
  }
}

async function loadAbandoned() {
  loadingAbandoned.value = true
  try {
    const result = await fetchApi('/api/abandoned-vehicle-logs')
    abandonedVehicles.value = result.items || []
  } catch (err) {
    toast.error(`Gagal memuat kendaraan ditinggal: ${err.message}`)
  } finally {
    loadingAbandoned.value = false
  }
}
</script>
