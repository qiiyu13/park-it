<template>
  <div>
    <PageHeader title="Laporan" subtitle="Ringkasan transaksi dan settlement e-money." />

    <!-- Date filter -->
    <div class="mb-4 border-2 border-foreground bg-surface p-4 shadow-brutal">
      <div class="mb-3 flex gap-2">
        <Button size="sm" variant="outline" @click="setToday">Hari Ini</Button>
        <Button size="sm" variant="outline" @click="setThisWeek">Minggu Ini</Button>
        <Button size="sm" variant="outline" @click="setThisMonth">Bulan Ini</Button>
        <Button size="sm" variant="outline" @click="setLastMonth">Bulan Lalu</Button>
      </div>
      <div class="flex items-center gap-3">
        <input v-model="dateFrom" type="date" class="border-2 border-foreground bg-background px-3 py-2 text-sm font-medium text-foreground shadow-brutal-sm" >
        <span class="font-bold text-foreground">s/d</span>
        <input v-model="dateTo" type="date" class="border-2 border-foreground bg-background px-3 py-2 text-sm font-medium text-foreground shadow-brutal-sm" >
        <Button size="sm" :disabled="loading" @click="loadReports">Tampilkan</Button>
      </div>
    </div>

    <TabStrip v-model="activeTab" :tabs="tabs" />

    <!-- Summary tab -->
    <div v-if="activeTab === 'summary'">
      <div v-if="summaryReport" class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Total Transaksi" :value="summaryReport.total_transactions.toLocaleString()" />
        <StatCard label="Total Pendapatan" :value="`Rp ${summaryReport.total_revenue.toLocaleString()}`" />
        <StatCard label="Pendapatan Cash" :value="`Rp ${summaryReport.cash_revenue.toLocaleString()}`" />
        <StatCard label="Pendapatan E-Money" :value="`Rp ${summaryReport.emoney_revenue.toLocaleString()}`" />
        <StatCard label="Pendapatan RFID" :value="`Rp ${summaryReport.rfid_revenue.toLocaleString()}`" />
        <StatCard label="Tarif Rata-rata" :value="`Rp ${Math.round(summaryReport.average_fee).toLocaleString()}`" />
        <StatCard label="Transaksi Aktif" :value="summaryReport.active_transactions.toLocaleString()" />
        <StatCard label="Transaksi Selesai" :value="summaryReport.completed_transactions.toLocaleString()" />
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
        <div class="border-2 border-foreground bg-surface p-3 shadow-brutal">
          <p class="text-xs font-bold uppercase text-muted-foreground">Total Transaksi</p>
          <p class="text-xl font-black text-foreground">{{ (shiftReport?.total_transactions ?? 0).toLocaleString('id-ID') }}</p>
        </div>
        <div class="border-2 border-foreground bg-surface p-3 shadow-brutal">
          <p class="text-xs font-bold uppercase text-muted-foreground">Total Pendapatan</p>
          <p class="text-xl font-black text-foreground">Rp {{ (shiftReport?.total_revenue ?? 0).toLocaleString('id-ID') }}</p>
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

    <!-- E-Money tab -->
    <div v-if="activeTab === 'emoney'">
      <div v-if="emoneyReport" class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Transaksi E-Money" :value="emoneyReport.total_emoney_transactions.toLocaleString()" />
        <StatCard label="Total Deducted" :value="`Rp ${emoneyReport.total_deducted.toLocaleString()}`" />
        <StatCard label="Berhasil" :value="emoneyReport.success_count.toLocaleString()" variant="success" />
        <StatCard label="Gagal" :value="emoneyReport.failed_count.toLocaleString()" variant="destructive" />
        <StatCard label="Lost Contact" :value="emoneyReport.lost_contact_count.toLocaleString()" variant="warning" />
        <StatCard label="Rata-rata Deduct" :value="`Rp ${Math.round(emoneyReport.average_deduct_amount).toLocaleString()}`" />
        <StatCard label="Belum Settlement" :value="emoneyReport.unsettled_count.toLocaleString()" />
        <StatCard label="Sudah Settlement" :value="emoneyReport.settled_count.toLocaleString()" />
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

const tabs = [
  { key: 'summary', label: 'Ringkasan' },
  { key: 'shift', label: 'Per Shift' },
  { key: 'emoney', label: 'E-Money' },
]

const activeTab = ref('summary')
const loading = ref(false)

const today = new Date()
const firstDayOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
const dateFrom = ref(firstDayOfMonth.toISOString().split('T')[0])
const dateTo = ref(today.toISOString().split('T')[0])

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

onMounted(() => { loadReports() })

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
  } catch (err) {
    toast.error(`Gagal memuat laporan: ${err.message}`)
  } finally {
    loading.value = false
  }
}

function setToday() { const d = new Date().toISOString().split('T')[0]; dateFrom.value = d; dateTo.value = d; loadReports() }
function setThisWeek() { const now = new Date(); const mon = new Date(now.setDate(now.getDate() - now.getDay() + 1)); dateFrom.value = mon.toISOString().split('T')[0]; dateTo.value = new Date().toISOString().split('T')[0]; loadReports() }
function setThisMonth() { const now = new Date(); dateFrom.value = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0]; dateTo.value = new Date().toISOString().split('T')[0]; loadReports() }
function setLastMonth() { const now = new Date(); dateFrom.value = new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString().split('T')[0]; dateTo.value = new Date(now.getFullYear(), now.getMonth(), 0).toISOString().split('T')[0]; loadReports() }

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
const StatCard = {
  props: {
    label: String,
    value: String,
    variant: { type: String, default: '' },
  },
  template: `
    <div class="border-2 border-foreground bg-surface p-4 text-center shadow-brutal">
      <div class="mb-1 text-xs font-bold uppercase text-muted-foreground">{{ label }}</div>
      <div :class="['text-xl font-black font-mono', variantClass]">{{ value }}</div>
    </div>
  `,
  computed: {
    variantClass() {
      if (this.variant === 'success') return 'text-success'
      if (this.variant === 'destructive') return 'text-destructive'
      if (this.variant === 'warning') return 'text-warning'
      return 'text-foreground'
    },
  },
}
</script>
