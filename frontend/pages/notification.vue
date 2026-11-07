<template>
  <div>
    <PageHeader title="Notifikasi" subtitle="Pantau transaksi unresolved, alert, dan status settlement." />

    <TabStrip v-model="activeTab" :tabs="tabs" />

    <!-- Unresolved E-Money -->
    <div v-if="activeTab === 'unresolved'">
      <DataTable :data="unresolvedEmoney" :columns="unresolvedColumns" :loading="loadingUnresolved" :show-add="false" :show-edit="false" :show-delete="false" />
    </div>

    <!-- Active Transactions -->
    <div v-if="activeTab === 'active'">
      <DataTable :data="activeTransactions" :columns="activeTxColumns" :loading="loadingActive" :show-add="false" :show-edit="false" :show-delete="false" />
    </div>

    <!-- Alerts -->
    <div v-if="activeTab === 'alerts'">
      <DataTable :data="recentAlerts" :columns="alertColumns" :loading="loadingAlerts" :show-add="false" :show-edit="false" :show-delete="false" />
    </div>

    <!-- Settlement -->
    <div v-if="activeTab === 'settlement'">
      <div class="mb-4">
        <Button size="sm" :disabled="triggering" @click="triggerSettlement">
          {{ triggering ? 'Generating...' : 'Generate & Upload' }}
        </Button>
      </div>
      <DataTable :data="settlements" :columns="settlementColumns" :loading="loadingSettlements" :show-add="false" :show-edit="false" :show-delete="false" />
    </div>
  </div>
</template>

<script setup>
import { toast } from 'vue-sonner'
import { Button } from '~/components/ui/button'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()

// Gate id/code → name lookup so the alert table shows gate names, not raw ids.
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
  } catch { /* non-fatal */ }
}

const tabs = [
  { key: 'unresolved', label: 'E-Money Unresolved' },
  { key: 'active', label: 'Transaksi Aktif' },
  { key: 'alerts', label: 'Alert Terbaru' },
  { key: 'settlement', label: 'Settlement' },
]

const activeTab = ref('unresolved')
const loadingUnresolved = ref(false)
const loadingActive = ref(false)
const loadingAlerts = ref(false)
const loadingSettlements = ref(false)
const triggering = ref(false)

const unresolvedEmoney = ref([])
const unresolvedColumns = [
  { prop: 'barcode', label: 'Barcode', width: 140 },
  { prop: 'plate_number', label: 'Plat', width: 120 },
  { prop: 'card_number', label: 'No. Kartu', width: 150 },
  { prop: 'entry_time', label: 'Masuk', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
  { prop: 'payment_method', label: 'Metode', width: 110 },
  { prop: 'status', label: 'Status', width: 120, type: 'enum' },
  { prop: 'gate_in_name', label: 'Gate Masuk', width: 130 },
]

const activeTransactions = ref([])
const activeTxColumns = [
  { prop: 'barcode', label: 'Barcode', width: 140 },
  { prop: 'plate_number', label: 'Plat', width: 120 },
  { prop: 'card_number', label: 'No. Kartu', width: 150 },
  { prop: 'entry_time', label: 'Masuk', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
  { prop: 'vehicle_type_name', label: 'Jenis', width: 100 },
  { prop: 'gate_in_name', label: 'Gate Masuk', width: 130 },
]

const recentAlerts = ref([])
const alertColumns = [
  { prop: 'type', label: 'Tipe', width: 150, type: 'enum' },
  { prop: 'gate_id', label: 'Gate', width: 140, formatter: (v) => gateLabel(v) },
  { prop: 'message', label: 'Pesan' },
  { prop: 'timestamp', label: 'Waktu', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
]

const settlements = ref([])
const settlementColumns = [
  { prop: 'filename', label: 'Filename', width: 300 },
  { prop: 'batch_date', label: 'Tanggal', width: 120 },
  { prop: 'batch_number', label: 'Batch', width: 80 },
  { prop: 'total_transactions', label: 'Transaksi', width: 100 },
  { prop: 'total_amount', label: 'Jumlah (Rp)', width: 130, formatter: (v) => v?.toLocaleString('id-ID') },
  { prop: 'status', label: 'Status', width: 120, type: 'enum' },
  { prop: 'created_at', label: 'Dibuat', width: 160, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
]

onMounted(() => { loadGateNames(); loadUnresolved(); loadActive(); loadAlerts(); loadSettlements() })

async function loadUnresolved() {
  loadingUnresolved.value = true
  try { unresolvedEmoney.value = (await fetchApi('/api/transactions?status=LOST_CONTACT&limit=50')).items ?? [] }
  catch (e) { console.error(e) }
  finally { loadingUnresolved.value = false }
}

async function loadActive() {
  loadingActive.value = true
  try { activeTransactions.value = (await fetchApi('/api/transactions?status=ACTIVE&limit=50')).items ?? [] }
  catch (e) { console.error(e) }
  finally { loadingActive.value = false }
}

async function loadAlerts() {
  loadingAlerts.value = true
  try {
    const [manualOpens, abandoned] = await Promise.all([
      fetchApi('/api/manual-open-logs?limit=20'),
      fetchApi('/api/abandoned-vehicle-logs?limit=20'),
    ])
    const alerts = []
    for (const item of (manualOpens.items || [])) alerts.push({ type: 'BUKA MANUAL', gate_id: item.gate_id, message: item.reason, timestamp: item.created_at })
    for (const item of (abandoned.items || [])) alerts.push({ type: 'KENDARAAN DITINGGAL', gate_id: item.gate_out_id, message: `Resolusi: ${item.resolution_type}`, timestamp: item.created_at })
    alerts.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    recentAlerts.value = alerts
  } catch (e) { console.error(e) }
  finally { loadingAlerts.value = false }
}

async function loadSettlements() {
  loadingSettlements.value = true
  try { settlements.value = (await fetchApi('/api/settlements?limit=50')) || [] }
  catch (e) { console.error(e) }
  finally { loadingSettlements.value = false }
}

async function triggerSettlement() {
  triggering.value = true
  try {
    await fetchApi('/api/settlements/trigger', { method: 'POST' })
    await loadSettlements()
    toast.success('Settlement berhasil dibuat & diunggah')
  } catch (e) {
    toast.error(`Gagal generate settlement: ${e.message}`)
  } finally { triggering.value = false }
}
</script>
