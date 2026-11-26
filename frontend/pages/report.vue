<template>
  <div>
    <PageHeader title="Laporan" subtitle="Ringkasan transaksi dan settlement e-money." />

    <!-- Date filter -->
    <div class="mb-4 rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
      <div class="mb-3 flex gap-2">
        <Button size="sm" variant="outline" @click="setToday">Hari Ini</Button>
        <Button size="sm" variant="outline" @click="setThisWeek">Minggu Ini</Button>
        <Button size="sm" variant="outline" @click="setThisMonth">Bulan Ini</Button>
        <Button size="sm" variant="outline" @click="setLastMonth">Bulan Lalu</Button>
      </div>
      <div class="flex items-center gap-3">
        <input v-model="dateFrom" type="date" class="form-control" >
        <span class="text-sm text-muted-foreground">s/d</span>
        <input v-model="dateTo" type="date" class="form-control" >
        <Button size="sm" :disabled="loading" @click="loadReports">Tampilkan</Button>
      </div>
    </div>

    <TabStrip v-model="activeTab" :tabs="tabs" />

    <!-- Summary tab -->
    <div v-if="activeTab === 'summary'">
      <div v-if="summaryReport" class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Total Transaksi" :value="summaryReport.total_transactions.toLocaleString('id-ID')" />
        <StatCard label="Total Pendapatan" :value="formatCurrency(summaryReport.total_revenue)" />
        <StatCard label="Pendapatan Cash" :value="formatCurrency(summaryReport.cash_revenue)" />
        <StatCard label="Pendapatan E-Money" :value="formatCurrency(summaryReport.emoney_revenue)" />
        <StatCard label="Pendapatan RFID" :value="formatCurrency(summaryReport.rfid_revenue)" />
        <StatCard label="Tarif Rata-rata" :value="formatCurrency(Math.round(summaryReport.average_fee))" />
        <StatCard label="Transaksi Aktif" :value="summaryReport.active_transactions.toLocaleString('id-ID')" />
        <StatCard label="Transaksi Selesai" :value="summaryReport.completed_transactions.toLocaleString('id-ID')" />
      </div>
      <div v-else class="py-12 text-center font-medium text-muted-foreground">Pilih rentang tanggal untuk melihat laporan</div>
      <div class="flex gap-2">
        <Button size="sm" variant="outline" @click="exportReport('csv')">Export CSV</Button>
        <Button size="sm" variant="outline" @click="exportReport('xlsx')">Export Excel</Button>
        <Button size="sm" variant="outline" @click="exportReport('pdf')">Export PDF</Button>
      </div>
    </div>

    <!-- Shift tab -->
    <div v-if="activeTab === 'shift'">
      <!-- Summary strip -->
      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div class="rounded-lg border border-border bg-surface p-3 shadow-brutal-sm">
          <p class="text-xs font-semibold  text-muted-foreground">Total Transaksi</p>
          <p class="text-xl font-semibold text-foreground">{{ (shiftReport?.total_transactions ?? 0).toLocaleString('id-ID') }}</p>
        </div>
        <div class="rounded-lg border border-border bg-surface p-3 shadow-brutal-sm">
          <p class="text-xs font-semibold  text-muted-foreground">Total Pendapatan</p>
          <p class="text-xl font-semibold text-foreground">Rp {{ (shiftReport?.total_revenue ?? 0).toLocaleString('id-ID') }}</p>
        </div>
      </div>
      <DataTable
        :data="shiftReport?.items ?? []"
        :columns="shiftReportColumns"
        :loading="loading"
        :show-add="false"
        :show-edit="false"
        :show-delete="false"
      />
    </div>

    <!-- Per exit booth tab (Compass "Laporan Penerimaan Uang Parkir") -->
    <div v-if="activeTab === 'exit-gate'">
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <select v-model="exitGateId" class="form-control w-auto" @change="loadExitGateReport">
          <option :value="null">Semua pos keluar</option>
          <option v-for="g in exitGates" :key="g.id" :value="g.id">{{ g.name }} ({{ g.code }})</option>
        </select>
        <Button size="sm" variant="outline" :disabled="!exitGateReport?.items?.length" @click="printExitGateReport">Cetak</Button>
      </div>
      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="card in exitGateCards" :key="card.label" class="rounded-lg border border-border bg-surface p-3 shadow-brutal-sm">
          <p class="text-xs font-semibold text-muted-foreground">{{ card.label }}</p>
          <p class="text-xl font-semibold text-foreground">{{ card.value }}</p>
        </div>
      </div>
      <DataTable
        :data="exitGateReport?.items ?? []"
        :columns="exitGateColumns"
        :loading="loading"
        :show-add="false"
        :show-edit="false"
        :show-delete="false"
      />
    </div>

    <!-- E-Money tab -->
    <div v-if="activeTab === 'emoney'">
      <div v-if="emoneyReport" class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Transaksi E-Money" :value="emoneyReport.total_emoney_transactions.toLocaleString('id-ID')" />
        <StatCard label="Total Deducted" :value="formatCurrency(emoneyReport.total_deducted)" />
        <StatCard label="Berhasil" :value="emoneyReport.success_count.toLocaleString('id-ID')" variant="success" />
        <StatCard label="Gagal" :value="emoneyReport.failed_count.toLocaleString('id-ID')" variant="destructive" />
        <StatCard label="Lost Contact" :value="emoneyReport.lost_contact_count.toLocaleString('id-ID')" variant="warning" />
        <StatCard label="Rata-rata Deduct" :value="formatCurrency(Math.round(emoneyReport.average_deduct_amount))" />
        <StatCard label="Belum Settlement" :value="emoneyReport.unsettled_count.toLocaleString('id-ID')" />
        <StatCard label="Sudah Settlement" :value="emoneyReport.settled_count.toLocaleString('id-ID')" />
      </div>
      <div v-else class="py-12 text-center font-medium text-muted-foreground">Pilih rentang tanggal untuk melihat laporan</div>
    </div>
  </div>
</template>

<script setup>
import { toast } from 'vue-sonner'
import { Button } from '~/components/ui/button'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()
const { formatCurrency } = useFormatters()

const tabs = [
  { key: 'summary', label: 'Ringkasan' },
  { key: 'shift', label: 'Per Shift' },
  { key: 'exit-gate', label: 'Per Pos Keluar' },
  { key: 'emoney', label: 'E-Money' },
]

const activeTab = ref('summary')
const loading = ref(false)

// Calendar day in the browser's timezone; toISOString() is UTC and gave
// yesterday's date before 07:00 WIB.
function localDay(d) { return d.toLocaleDateString('en-CA') }

const today = new Date()
const firstDayOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
const dateFrom = ref(localDay(firstDayOfMonth))
const dateTo = ref(localDay(today))

const summaryReport = ref(null)
const emoneyReport = ref(null)
const shiftReport = ref(null)

const rupiah = (v) => `Rp ${(v ?? 0).toLocaleString('id-ID')}`
const shiftReportColumns = [
  { prop: 'date', label: 'Tanggal', width: 120, sortable: true, formatter: (v) => v ? new Date(v).toLocaleDateString('id-ID') : '-' },
  { prop: 'shift_name', label: 'Shift', width: 120 },
  { prop: 'operator_name', label: 'Operator', width: 150, formatter: (v) => v || '-' },
  { prop: 'total_transactions', label: 'Transaksi', width: 100, sortable: true },
  { prop: 'cash_revenue', label: 'Tunai', width: 130, formatter: rupiah },
  { prop: 'emoney_revenue', label: 'E-Money', width: 130, formatter: rupiah },
  { prop: 'rfid_revenue', label: 'Member', width: 130, formatter: rupiah },
  { prop: 'total_revenue', label: 'Total', width: 140, sortable: true, formatter: rupiah },
  { prop: 'average_fee', label: 'Rata-rata', width: 120, formatter: rupiah },
]

const METHOD_LABELS = { CASH: 'Tunai', EMONEY: 'E-Money', RFID_MEMBER: 'Member' }
const exitGates = ref([])
const exitGateId = ref(null)
const exitGateReport = ref(null)
const exitGateColumns = [
  { prop: 'no', label: 'No', width: 60 },
  { prop: 'barcode', label: 'Tiket', width: 150 },
  { prop: 'plate_number', label: 'Plat', width: 110, formatter: (v) => v || '-' },
  { prop: 'exit_time', label: 'Jam Keluar', width: 170, sortable: true, formatter: (v) => v ? new Date(v).toLocaleString('id-ID') : '-' },
  { prop: 'gate_name', label: 'Pos Keluar', width: 140 },
  { prop: 'operator_name', label: 'Petugas', width: 140, formatter: (v) => v || '-' },
  { prop: 'vehicle_type', label: 'Tarif', width: 100, formatter: (v) => v || '-' },
  { prop: 'payment_method', label: 'Bayar', width: 100, formatter: (v) => METHOD_LABELS[v] || v },
  { prop: 'fee', label: 'Penerimaan', width: 130, sortable: true, formatter: rupiah },
]
const exitGateCards = computed(() => {
  const r = exitGateReport.value
  const by = r?.by_method || {}
  return [
    { label: 'Total Penerimaan', value: rupiah(r?.total_amount) },
    { label: `Tunai`, value: rupiah(by.CASH) },
    { label: 'E-Money', value: rupiah(by.EMONEY) },
    { label: 'Jumlah Tiket', value: (r?.total_count ?? 0).toLocaleString('id-ID') },
  ]
})

async function loadExitGateReport() {
  const qs = new URLSearchParams({ date_from: dateFrom.value, date_to: dateTo.value })
  if (exitGateId.value) qs.set('gate_out_id', exitGateId.value)
  try {
    exitGateReport.value = await fetchApi(`/api/reports/exit-gate?${qs}`)
  } catch (err) {
    toast.error(`Gagal memuat laporan pos keluar: ${err.message}`)
  }
}

// Printable copy in its own window, so the sidebar and filters stay off paper.
function printExitGateReport() {
  const r = exitGateReport.value
  const gate = exitGates.value.find((g) => g.id === exitGateId.value)
  const esc = (v) => String(v ?? '-').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
  const rows = r.items.map((i) => `<tr><td>${i.no}</td><td>${esc(i.barcode)}</td><td>${esc(i.plate_number)}</td><td>${esc(new Date(i.exit_time).toLocaleString('id-ID'))}</td><td>${esc(i.gate_name)}</td><td>${esc(i.operator_name)}</td><td>${esc(i.vehicle_type)}</td><td>${esc(METHOD_LABELS[i.payment_method] || i.payment_method)}</td><td class="r">${rupiah(i.fee)}</td></tr>`).join('')
  const w = window.open('', '_blank')
  if (!w) { toast.error('Popup diblokir browser — izinkan popup untuk mencetak'); return }
  w.document.write(`<!doctype html><title>Laporan Penerimaan Uang Parkir</title><style>body{font:12px sans-serif;margin:24px}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #ccc;padding:4px;text-align:left}.r{text-align:right}tfoot td{font-weight:bold;border-top:2px solid #000}</style>
<h2>LAPORAN PENERIMAAN UANG PARKIR</h2><p>Tanggal: ${esc(dateFrom.value)} s/d ${esc(dateTo.value)}<br>Pos: ${esc(gate ? gate.name : 'Semua pos keluar')}</p>
<table><thead><tr><th>No</th><th>Tiket</th><th>Plat</th><th>Jam Keluar</th><th>Pos</th><th>Petugas</th><th>Tarif</th><th>Bayar</th><th class="r">Penerimaan</th></tr></thead><tbody>${rows}</tbody>
<tfoot><tr><td colspan="8">Total Penerimaan (${r.total_count} tiket)</td><td class="r">${rupiah(r.total_amount)}</td></tr></tfoot></table>`)
  w.document.close()
  w.focus()
  w.print()
}

onMounted(async () => {
  loadReports()
  try { exitGates.value = await fetchApi('/api/gates?direction=OUT') } catch { exitGates.value = [] }
})

async function loadReports() {
  if (!dateFrom.value || !dateTo.value) return
  loading.value = true
  try {
    const qs = new URLSearchParams({ date_from: dateFrom.value, date_to: dateTo.value })
    const [summary, emoney, shift] = await Promise.all([
      fetchApi(`/api/reports/summary?${qs}`),
      fetchApi(`/api/reports/emoney?${qs}`),
      fetchApi(`/api/reports/shift?${qs}`),
    ])
    summaryReport.value = summary
    emoneyReport.value = emoney
    shiftReport.value = shift
    await loadExitGateReport()
  } catch (err) {
    toast.error(`Gagal memuat laporan: ${err.message}`)
  } finally {
    loading.value = false
  }
}

function setToday() { const d = localDay(new Date()); dateFrom.value = d; dateTo.value = d; loadReports() }
function setThisWeek() { const now = new Date(); const mon = new Date(now.setDate(now.getDate() - now.getDay() + 1)); dateFrom.value = localDay(mon); dateTo.value = localDay(new Date()); loadReports() }
function setThisMonth() { const now = new Date(); dateFrom.value = localDay(new Date(now.getFullYear(), now.getMonth(), 1)); dateTo.value = localDay(new Date()); loadReports() }
function setLastMonth() { const now = new Date(); dateFrom.value = localDay(new Date(now.getFullYear(), now.getMonth() - 1, 1)); dateTo.value = localDay(new Date(now.getFullYear(), now.getMonth(), 0)); loadReports() }

async function exportReport(format) {
  try {
    const url = `/api/reports/summary/export?format=${format}&date_from=${dateFrom.value}&date_to=${dateTo.value}`
    const blob = await fetchApi(url, { responseType: 'blob' })
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = `EParking_Report_${dateFrom.value}_${dateTo.value}.${format}`
    link.click()
    URL.revokeObjectURL(objectUrl)
    toast.success(`Laporan ${format.toUpperCase()} diunduh`)
  } catch (e) {
    toast.error(`Gagal export laporan: ${e.message}`)
  }
}
</script>

<script>
</script>
