<template>
  <div>
    <PageHeader
      title="Perangkat"
      subtitle="Ubah atau tambah gate, booth POS, kamera, printer, e-money reader satuan. Untuk perangkat serial baru, gunakan tab Alat Serial."
    />

    <TabStrip v-model="activeTab" :tabs="tabs" />

    <!-- Overview (status cards) -->
    <div v-if="activeTab === 'overview'">
      <div v-if="loadingGates" class="text-sm font-medium text-muted-foreground">Memuat gate…</div>
      <div v-else-if="!gates.length" class="rounded-lg border border-border bg-surface p-6 text-sm font-medium text-muted-foreground shadow-brutal-sm">
        Belum ada gate. Tambah dari tab Gates atau jalankan Setup Wizard.
      </div>
      <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <GateStatusCard
          v-for="gate in gates"
          :key="gate.id"
          :gate="gate"
          :testing="testingGateId === gate.id"
          :booths="posList"
          :camera-status="cameraStatus"
          @edit="openGateModal(gate)"
          @test="testGate(gate)"
          @logs="openGateLog(gate)"
          @enable-daemon="enableGateDaemon(gate)"
          @open="openGateRemotely(gate)"
        />
      </div>

      <!-- Peripheral health: printers + e-money readers + cameras at a glance -->
      <div v-if="!loadingGates && (printers.length || emoneyReaders.length || cameras.length)" class="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div v-if="cameras.length" class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
          <h3 class="mb-3 text-sm font-semibold text-foreground border-b border-border pb-2">Kamera</h3>
          <div class="space-y-2">
            <div v-for="c in cameras" :key="c.id" class="flex items-center justify-between gap-2 text-sm">
              <span class="truncate font-medium text-foreground">{{ c.name }}</span>
              <div class="flex shrink-0 items-center gap-2">
                <span class="max-w-40 truncate text-xs text-muted-foreground">{{ c.rtsp_url }}</span>
                <StatusPill v-bind="cameraPill(c)" />
              </div>
            </div>
          </div>
        </div>
        <div v-if="printers.length" class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
          <h3 class="mb-3 text-sm font-semibold text-foreground border-b border-border pb-2">Printer</h3>
          <div class="space-y-2">
            <div v-for="p in printers" :key="p.id" class="flex items-center justify-between gap-2 text-sm">
              <span class="truncate font-medium text-foreground">{{ p.name }}</span>
              <div class="flex shrink-0 items-center gap-2">
                <StatusPill :status="p.is_active ? 'online' : 'idle'" :label="p.is_active ? 'Aktif' : 'Nonaktif'" />
              </div>
            </div>
          </div>
        </div>
        <div v-if="emoneyReaders.length" class="rounded-lg border border-border bg-surface p-4 shadow-brutal-sm">
          <h3 class="mb-3 text-sm font-semibold text-foreground border-b border-border pb-2">E-Money Reader</h3>
          <div class="space-y-2">
            <div v-for="r in emoneyReaders" :key="r.id" class="flex items-center justify-between gap-2 text-sm">
              <span class="truncate font-medium text-foreground">{{ r.name }}</span>
              <StatusPill
                :status="r.is_online ? 'online' : (r.is_active ? 'warning' : 'idle')"
                :label="r.is_online ? 'Online' : (r.is_active ? 'Offline' : 'Nonaktif')"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Gates -->
    <div v-if="activeTab === 'gates'">
      <DataTable :data="gates" :columns="gateColumns" :loading="loadingGates" @add="openGateModal()" @edit="openGateModal" @delete="confirmDeleteGate">
        <template #row-actions="{ row }">
          <button
            class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground disabled:opacity-40"
            :title="testingGateId === row.id ? 'Menguji…' : 'Test koneksi'"
            :disabled="testingGateId === row.id"
            @click="testGate(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
          </button>
          <button
            v-if="row.direction === 'IN' && !row.is_online"
            class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground disabled:opacity-40"
            title="Aktifkan daemon lane"
            :disabled="enablingGateId === row.id"
            @click="enableGateDaemon(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0" /><path d="M12 2v10" /></svg>
          </button>
          <button
            class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
            title="Log perangkat (live)"
            @click="openGateLog(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
          </button>
          <button
            class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
            title="Buka gate"
            @click="openGateRemotely(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 9.9-1" /></svg>
          </button>
          <button
            class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
            title="Uji buka/tutup (end-to-end)"
            @click="openGateTest(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 11 3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>
          </button>
        </template>
      </DataTable>
    </div>

    <!-- POS Booths -->
    <div v-if="activeTab === 'pos'">
      <DataTable :data="posList" :columns="posColumns" :loading="loadingPos" @add="openPosModal()" @edit="openPosModal" @delete="confirmDeletePos" />
    </div>

    <!-- Cameras -->
    <div v-if="activeTab === 'cameras'">
      <DataTable :data="cameras" :columns="cameraColumns" :loading="loadingCameras" @add="openCameraModal()" @edit="openCameraModal" @delete="confirmDeleteCamera">
        <template #row-actions="{ row }">
          <div class="relative">
            <button
              class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
              title="Menu"
              @click.stop="toggleRowMenu('camera', row.id)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" /></svg>
            </button>
            <div
              v-if="rowMenu === `camera-${row.id}`"
              class="absolute right-0 z-30 mt-1 w-40 overflow-hidden rounded-md border border-border bg-surface shadow-lg"
            >
              <button
                class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover disabled:opacity-50"
                :disabled="testingCameraId === row.id"
                @click="testCameraRow(row)"
              >
                {{ testingCameraId === row.id ? 'Menguji…' : 'Test Kamera' }}
              </button>
            </div>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- Printers -->
    <div v-if="activeTab === 'printers'">
      <DataTable :data="printers" :columns="printerColumns" :loading="loadingPrinters" @add="openPrinterModal()" @edit="openPrinterModal" @delete="confirmDeletePrinter">
        <template #row-actions="{ row }">
          <div class="relative">
            <button
              class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
              title="Menu"
              @click.stop="toggleRowMenu('printer', row.id)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" /></svg>
            </button>
            <div
              v-if="rowMenu === `printer-${row.id}`"
              class="absolute right-0 z-30 mt-1 w-40 overflow-hidden rounded-md border border-border bg-surface shadow-lg"
            >
              <button
                class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover disabled:opacity-50"
                :disabled="testingPrinterId === row.id"
                @click="testPrinterRow(row)"
              >
                {{ testingPrinterId === row.id ? 'Menguji…' : 'Test Print' }}
              </button>
            </div>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- E-Money Readers -->
    <div v-if="activeTab === 'emoney-readers'">
      <DataTable :data="emoneyReaders" :columns="emoneyReaderColumns" :loading="loadingEmoneyReaders" @add="openEmoneyReaderModal()" @edit="openEmoneyReaderModal" @delete="confirmDeleteEmoneyReader" />
    </div>

    <!-- Serial Tools: detect ports + pin a stable /dev/parking-<role> udev symlink. -->
    <!-- Closes the post-setup gap where remapping a swapped USB device was wizard-only. -->
    <div v-if="activeTab === 'serial-tools'" class="max-w-2xl space-y-5">
      <div class="space-y-4 rounded-lg border border-border bg-surface p-5 shadow-brutal-sm">
        <div class="space-y-1">
          <h3 class="text-sm font-semibold text-foreground">Deteksi &amp; Pasang Perangkat Serial</h3>
          <p class="text-xs text-muted-foreground">
            Gunakan saat mengganti atau memasang ulang perangkat USB/serial. Pilih peran, deteksi port, uji,
            lalu pasang sebagai <span class="font-mono">/dev/parking-&lt;peran&gt;</span> agar nama perangkat tetap walau dicabut-pasang.
            Setelah terpasang, salin path tersebut ke field <em>Device</em> pada gate/printer/e-money terkait.
          </p>
        </div>

        <div class="space-y-2">
          <label class="text-sm font-semibold text-foreground">Peran perangkat</label>
          <select
            v-model="serialRole"
            class="form-control w-full sm:w-72"
          >
            <option v-for="r in serialRoles" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </div>

        <DeviceProbeRow
          :key="serialRole"
          type="serial"
          :role="serialRole"
          :device="serialDevice"
          :baudrate="serialBaudrate"
          @update:device="(v) => (serialDevice = v)"
          @update:baudrate="(v) => (serialBaudrate = v)"
          @write-udev="onUdevWritten"
        />

        <p v-if="lastSymlink" class="rounded-md bg-success/10 px-3 py-2 text-xs font-medium text-success">
          Terpasang: <span class="font-mono">{{ lastSymlink }}</span> — salin path ini ke field Device perangkat terkait.
        </p>
      </div>
    </div>

    <!-- End-to-end gate open/close test (software → daemon → controller ACK). -->
    <Dialog :open="gateTestVisible" @update:open="(v) => { if (!v) gateTestVisible = false }">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Uji buka/tutup — {{ gateTestTarget?.name }}</DialogTitle>
        </DialogHeader>
        <p class="text-xs text-muted-foreground">
          Perintah buka dikirim ke daemon via Redis lalu menunggu ACK dari controller.
          Konfirmasi seluruh jalur software → hardware bekerja.
        </p>
        <GateTestButton
          v-if="gateTestTarget"
          :key="gateTestTarget.id"
          :gate-id="gateTestTarget.id"
          :gate-code="gateTestTarget.code"
        />
      </DialogContent>
    </Dialog>

    <!-- Modals (keep Element Plus based CrudModal) -->
    <CrudModal v-model="gateModalVisible" :title="gateEditing ? 'Edit Gate' : 'Tambah Gate'" :fields="gateFields" :initial-data="gateForm" :submitting="submitting" @submit="saveGate" />
    <CrudModal v-model="posModalVisible" :title="posEditing ? 'Edit Booth POS' : 'Tambah Booth POS'" :fields="posFields" :initial-data="posForm" :submitting="submitting" @submit="savePos" />
    <CrudModal v-model="cameraModalVisible" :title="cameraEditing ? 'Edit Kamera' : 'Tambah Kamera'" :fields="cameraFields" :initial-data="cameraForm" :submitting="submitting" @submit="saveCamera" />
    <CrudModal v-model="printerModalVisible" :title="printerEditing ? 'Edit Printer' : 'Tambah Printer'" :fields="printerFields" :initial-data="printerForm" :submitting="submitting" @submit="savePrinter" />
    <CrudModal v-model="emoneyReaderModalVisible" :title="emoneyReaderEditing ? 'Edit E-Money Reader' : 'Tambah E-Money Reader'" :fields="emoneyReaderFields" :initial-data="emoneyReaderForm" :submitting="submitting" @submit="saveEmoneyReader" />
    <ConfirmDialog v-model="deleteDialogVisible" :title="`Hapus ${deleteTargetName}`" :message="`Apakah Anda yakin ingin menghapus ${deleteTargetName}?`" :loading="submitting" @confirm="executeDelete" />

    <GateLogDialog v-model:open="logDialogVisible" :gate="logTarget" />

    <Dialog :open="cameraTestVisible" @update:open="(v) => { if (!v) cameraTestVisible = false }">
      <DialogContent class="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Test Kamera — {{ cameraTestName }}</DialogTitle>
        </DialogHeader>
        <p v-if="cameraTestLoading" class="text-sm text-muted-foreground">Mengambil snapshot…</p>
        <p v-else-if="cameraTestError" class="text-sm font-medium text-destructive">{{ cameraTestError }}</p>
        <img v-else-if="cameraTestImage" :src="cameraTestImage" alt="Snapshot kamera" class="w-full rounded-md border border-border" >
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import GateStatusCard from '~/components/dashboard/GateStatusCard.vue'
import StatusPill from '~/components/setup/StatusPill.vue'
import DeviceProbeRow from '~/components/setup/DeviceProbeRow.vue'
import GateTestButton from '~/components/setup/GateTestButton.vue'
import GateLogDialog from '~/components/device/GateLogDialog.vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()
const gateCrud = useCrud('/api/gates', { label: 'Gate' })
const posCrud = useCrud('/api/pos', { label: 'Booth POS' })
const cameraCrud = useCrud('/api/cameras', { label: 'Kamera' })
const printerCrud = useCrud('/api/printers', { label: 'Printer' })
const readerCrud = useCrud('/api/emoney-readers', { label: 'E-Money Reader' })

const tabs = [
  { key: 'overview', label: 'Ringkasan' },
  { key: 'gates', label: 'Gates' },
  { key: 'pos', label: 'Booth POS' },
  { key: 'cameras', label: 'Kamera' },
  { key: 'printers', label: 'Printer' },
  { key: 'emoney-readers', label: 'E-Money Reader' },
  { key: 'serial-tools', label: 'Alat Serial' },
]

const activeTab = ref('overview')
const submitting = ref(false)
const testingGateId = ref(null)

// Serial Tools: detect ports + pin a stable /dev/parking-<role> symlink. Roles
// match scripts/detect-serial-devices.sh (ROLE_NAMES).
const serialRoles = [
  { value: 'gate', label: 'Controller Gate (RS232/USB)' },
  { value: 'rfid', label: 'RFID Reader' },
  { value: 'emoney', label: 'E-Money Reader (PASSTI)' },
  { value: 'printer', label: 'Printer Struk Termal' },
  { value: 'scanner', label: 'Barcode Scanner' },
]
const serialRole = ref('gate')
const serialDevice = ref('')
const serialBaudrate = ref(9600)
const lastSymlink = ref('')
function onUdevWritten(symlink) { lastSymlink.value = symlink }
watch(serialRole, () => { lastSymlink.value = ''; serialDevice.value = ''; serialBaudrate.value = 9600 })

// End-to-end gate open/close test (distinct from the connection probe in testGate).
const gateTestVisible = ref(false)
const gateTestTarget = ref(null)
function openGateTest(gate) { gateTestTarget.value = gate; gateTestVisible.value = true }

// Enable the gate-in daemon for a lane added after installation.
const enablingGateId = ref(null)
async function enableGateDaemon(gate) {
  enablingGateId.value = gate.id
  const { toast } = await import('vue-sonner')
  try {
    const res = await fetchApi(`/api/gates/${gate.id}/enable-daemon`, { method: 'POST' })
    toast.success(`Daemon ${gate.code} aktif (${res.state})`)
    await loadGates()
  } catch (err) {
    const detail = err?.data?.detail
    toast.error(Array.isArray(detail) ? detail.map(d => d?.msg || d).join('; ') : (detail || err.message || 'Gagal mengaktifkan daemon'))
  } finally {
    enablingGateId.value = null
  }
}

// Live technician log for the lane's gate daemon.
const logDialogVisible = ref(false)
const logTarget = ref(null)
function openGateLog(gate) { logTarget.value = gate; logDialogVisible.value = true }

// Three-dot row menu (camera / printer test).
const rowMenu = ref(null)
function toggleRowMenu(kind, id) {
  rowMenu.value = rowMenu.value === `${kind}-${id}` ? null : `${kind}-${id}`
}

// Camera snapshot test (server proxies the RTSP frame).
const testingCameraId = ref(null)
const cameraTestVisible = ref(false)
const cameraTestLoading = ref(false)
const cameraTestError = ref('')
const cameraTestImage = ref('')
const cameraTestName = ref('')
async function testCameraRow(camera) {
  rowMenu.value = null
  testingCameraId.value = camera.id
  cameraTestName.value = camera.name
  cameraTestVisible.value = true
  cameraTestLoading.value = true
  cameraTestError.value = ''
  cameraTestImage.value = ''
  try {
    const res = await fetch(`/api/cameras/${camera.id}/test`, { credentials: 'include' })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
    cameraTestImage.value = `data:image/jpeg;base64,${data.snapshot}`
  } catch (err) {
    cameraTestError.value = err.message || 'Gagal mengambil snapshot'
  } finally {
    cameraTestLoading.value = false
    testingCameraId.value = null
  }
}

// Printer test (server picks the transport that answers).
const testingPrinterId = ref(null)
async function testPrinterRow(printer) {
  rowMenu.value = null
  testingPrinterId.value = printer.id
  const { toast } = await import('vue-sonner')
  try {
    const res = await fetch(`/api/printers/${printer.id}/test`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
    toast.success(`${printer.name}: ${data.detail || 'test print terkirim'}`)
  } catch (err) {
    toast.error(`Test print gagal: ${err.message}`)
  } finally {
    testingPrinterId.value = null
  }
}

async function testGate(gate) {
  testingGateId.value = gate.id
  try {
    const body = gate.protocol === 'serial'
      ? { type: 'serial', device: gate.controller_device, baudrate: gate.controller_baudrate || 9600, gate_id: gate.id }
      : { type: 'tcp', host: gate.controller_host, port: gate.controller_port }
    const res = await fetchApi('/api/setup/test-device', { method: 'POST', body: JSON.stringify(body) })
    const { toast } = await import('vue-sonner')
    if (res.ok) toast.success(`${gate.code}: ${Math.round(res.latency_ms || 0)}ms`)
    else toast.error(`${gate.code}: ${res.error || 'gagal'}`)
  } catch (err) {
    const { toast } = await import('vue-sonner')
    toast.error(`${gate.code}: ${err.message}`)
  } finally {
    testingGateId.value = null
  }
}

async function openGateRemotely(gate) {
  try {
    // Explicit body: the endpoint declares a pydantic request model, so an
    // empty POST body is rejected with 422 (surfaced as "[object Object]").
    await fetchApi(`/api/gates/${gate.id}/open`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'Manual open from device page' }),
    })
    const { toast } = await import('vue-sonner')
    toast.success(`${gate.code} dibuka`)
  } catch (err) {
    const { toast } = await import('vue-sonner')
    const detail = err?.data?.detail
    const msg = Array.isArray(detail)
      ? detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
      : (detail || err?.message || 'Gagal membuka gate')
    toast.error(msg)
  }
}

// Gates
const gates = ref([])
const loadingGates = ref(false)
const gateModalVisible = ref(false)
const gateEditing = ref(false)
const gateForm = ref({})
// Snapshot of the saved hardware_config while the edit modal is open: the
// modal only submits declared fields, so merging against the live form alone
// silently wiped lane_type / open_command / printer_id on every save.
const gateEditingHw = ref({})
const gateColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'code', label: 'Kode', width: 120, sortable: true },
  { prop: 'direction', label: 'Arah', width: 80, type: 'enum' },
  { prop: 'protocol', label: 'Protokol', width: 100 },
  { prop: 'controller_host', label: 'Host / Device', width: 160, formatter: (_, row) => row.protocol === 'serial' ? (row.controller_device || '-') : (row.controller_host || '-') },
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const RFID_CONN_OPTIONS = [{ label: 'Controller (Wiegand)', value: 'controller' }, { label: 'Serial Langsung / USB', value: 'direct_serial' }]
const EMONEY_CONN_OPTIONS = [{ label: 'Controller (QR5 Tunnel)', value: 'controller' }, { label: 'Serial Langsung / USB', value: 'direct_serial' }]

const cameraOptions = computed(() => [
  { label: '— tidak ada —', value: '' },
  ...cameras.value.map((c) => ({ label: c.name, value: c.id })),
])
const printerOptions = computed(() => [
  { label: '— tidak ada —', value: '' },
  ...printers.value.map((p) => ({ label: `${p.name} (${p.mode})`, value: p.id })),
])

const gateFields = computed(() => {
  const dir = gateForm.value.direction
  const proto = gateForm.value.protocol
  const rfidEnabled = gateForm.value._rfid_enabled
  const rfidDirect = gateForm.value._rfid_connection === 'direct_serial'
  const emoneyEnabled = gateForm.value._emoney_enabled
  const emoneyDirect = gateForm.value._emoney_connection === 'direct_serial'
  const uhfReaderEnabled = gateForm.value._uhf_reader_enabled

  const base = [
    { prop: 'name', label: 'Nama', type: 'text', required: true },
    { prop: 'code', label: 'Kode', type: 'text', required: true },
    { prop: 'direction', label: 'Arah', type: 'select', required: true, options: [{ label: 'Masuk', value: 'IN' }, { label: 'Keluar', value: 'OUT' }] },
    { prop: 'protocol', label: 'Protokol', type: 'select', required: true, options: [{ label: 'Compass (TCP)', value: 'compass' }, { label: 'ENET (TCP)', value: 'enet' }, { label: 'Serial / USB', value: 'serial' }] },
    ...(proto === 'serial'
      ? [
          { prop: 'controller_device', label: 'Device Serial', type: 'text', placeholder: '/dev/parking-gate', required: true },
          { prop: 'controller_baudrate', label: 'Baudrate', type: 'number', placeholder: '9600' },
          { prop: 'open_command', label: 'Perintah Buka (hex/ASCII)', type: 'text', placeholder: 'A00101A2 atau *TRIG1#' },
          { prop: 'close_command', label: 'Perintah Tutup (opsional)', type: 'text', placeholder: 'A00100A1' },
          { prop: 'close_delay_seconds', label: 'Tutup otomatis (detik)', type: 'number', placeholder: '3' },
        ]
      : [
          { prop: 'controller_host', label: 'Host Controller', type: 'ip-scan', portProp: 'controller_port', placeholder: '192.168.1.x', required: true },
          { prop: 'controller_port', label: 'Port Controller', type: 'number', placeholder: '4001', required: true },
        ]
    ),
    { prop: 'has_close_sensor', label: 'Sensor Tutup', type: 'boolean' },
    { prop: 'relay_mode', label: 'Mode Relay', type: 'select', options: [{ label: 'Single (1 relay)', value: 'SINGLE' }, { label: 'Dual (2 relay)', value: 'DUAL' }, { label: 'Triple (3 relay)', value: 'TRIPLE' }] },
    { prop: 'lane_reset_mode', label: 'Reset lane pakai', type: 'select', options: [
      { label: 'Ikut pengaturan global', value: '' },
      { label: 'Timer saja', value: 'time' },
      { label: 'IN3OFF saja', value: 'in3off' },
      { label: 'IN3OFF + timer', value: 'both' },
    ], helper: 'Khusus gate masuk: penentu kapan lane siap lagi untuk kendaraan berikutnya.' },
    { prop: 'lane_reset_seconds', label: 'Jeda reset lane (detik)', type: 'number', placeholder: 'kosong = ikut pengaturan global', helper: 'Dipakai untuk mode timer / IN3OFF + timer.' },
  ]

  if (dir === 'IN') {
    base.push(
      { prop: '_rfid_enabled', label: 'RFID Reader', type: 'boolean' },
      ...(rfidEnabled ? [
        { prop: '_rfid_connection', label: 'Koneksi RFID', type: 'select', options: RFID_CONN_OPTIONS },
        ...(rfidDirect ? [
          { prop: '_rfid_device', label: 'Device RFID', type: 'text', placeholder: '/dev/parking-rfid', required: true },
          { prop: '_rfid_baudrate', label: 'Baudrate RFID', type: 'number', placeholder: '9600' },
        ] : []),
      ] : []),
      { prop: '_ticket_printer_enabled', label: 'Printer Tiket', type: 'boolean' },
      { prop: '_printer_id', label: 'Printer (perangkat)', type: 'select', options: printerOptions.value },
      { prop: '_emoney_enabled', label: 'E-Money', type: 'boolean' },
      { prop: '_camera_enabled', label: 'Kamera', type: 'boolean' },
      { prop: '_camera_id', label: 'Kamera (perangkat)', type: 'select', options: cameraOptions.value },
      { prop: '_display_enabled', label: 'Modul Display (LED)', type: 'boolean', helper: 'Centang HANYA jika controller punya modul display. cmd_ds ke controller tanpa display akan disconnect.' },
      { prop: '_audio_enabled', label: 'Modul Audio (MP3)', type: 'boolean' },
    )
  } else if (dir === 'OUT') {
    base.push(
      { prop: 'pos_id', label: 'Booth POS', type: 'select', options: posOptions.value, helper: 'Kosongkan bila relay gate ini belum terpasang (tombol Buka Gate akan menolak).' },
      { prop: '_rfid_enabled', label: 'RFID Member Reader', type: 'boolean' },
      ...(rfidEnabled ? [
        { prop: '_rfid_connection', label: 'Koneksi RFID', type: 'select', options: RFID_CONN_OPTIONS },
        ...(rfidDirect ? [
          { prop: '_rfid_device', label: 'Device RFID', type: 'text', placeholder: '/dev/parking-rfid', required: true },
          { prop: '_rfid_baudrate', label: 'Baudrate RFID', type: 'number', placeholder: '9600' },
        ] : []),
      ] : []),
      { prop: '_emoney_enabled', label: 'E-Money Reader', type: 'boolean' },
      ...(emoneyEnabled ? [
        { prop: '_emoney_connection', label: 'Koneksi E-Money', type: 'select', options: EMONEY_CONN_OPTIONS },
        ...(emoneyDirect ? [
          { prop: '_emoney_device', label: 'Device E-Money', type: 'text', placeholder: '/dev/parking-emoney', required: true },
          { prop: '_emoney_baudrate', label: 'Baudrate E-Money', type: 'number', placeholder: '38400' },
        ] : []),
      ] : []),
      { prop: '_uhf_reader_enabled', label: 'UHF Reader (auto-exit)', type: 'boolean' },
      ...(uhfReaderEnabled ? [
        { prop: '_uhf_reader_host', label: 'Host UHF', type: 'text', placeholder: '192.168.1.50', required: true },
        { prop: '_uhf_reader_port', label: 'Port UHF', type: 'number', placeholder: '6000', required: true },
      ] : []),
      { prop: '_camera_enabled', label: 'Kamera', type: 'boolean' },
      { prop: '_camera_id', label: 'Kamera (perangkat)', type: 'select', options: cameraOptions.value },
      { prop: '_printer_id', label: 'Printer (perangkat)', type: 'select', options: printerOptions.value },
      { prop: '_display_enabled', label: 'Modul Display (LED)', type: 'boolean', helper: 'Centang HANYA jika controller punya modul display.' },
      { prop: '_audio_enabled', label: 'Modul Audio (MP3)', type: 'boolean' },
    )
  }

  base.push({ prop: 'is_active', label: 'Aktif', type: 'boolean' })
  return base
})

function flattenHardwareConfig(hw = {}) {
  return {
    _rfid_enabled: hw.rfid?.enabled ?? false,
    _rfid_connection: hw.rfid?.connection ?? 'controller',
    _rfid_device: hw.rfid?.device ?? '',
    _rfid_baudrate: hw.rfid?.baudrate ?? 9600,
    _ticket_printer_enabled: hw.ticket_printer?.enabled ?? false,
    _emoney_enabled: hw.emoney?.enabled ?? false,
    _emoney_connection: hw.emoney?.connection ?? 'controller',
    _emoney_device: hw.emoney?.device ?? '',
    _emoney_baudrate: hw.emoney?.baudrate ?? 38400,
    _camera_enabled: hw.camera?.enabled ?? false,
    lane_reset_mode: hw.lane_reset_mode ?? '',
    lane_reset_seconds: hw.lane_reset_seconds ?? '',
    open_command: hw.open_command ?? '',
    close_command: hw.close_command ?? '',
    close_delay_seconds: hw.close_delay_seconds ?? 3,
    _camera_id: (hw.camera_ids && hw.camera_ids[0]) || hw.camera_id || null,
    _printer_id: hw.printer_id ?? null,
    _uhf_reader_enabled: hw.uhf_reader?.enabled ?? false,
    _uhf_reader_host: hw.uhf_reader?.host ?? '',
    _uhf_reader_port: hw.uhf_reader?.port ?? 6000,
    _display_enabled: hw.display?.enabled ?? false,
    _audio_enabled: hw.audio?.enabled ?? false,
  }
}
function buildHardwareConfig(form) {
  // Preserve keys this form does not expose (track_map, inline cameras, ...).
  const hw = { ...(form.hardware_config || gateEditingHw.value || {}) }
  // `cameras` is a response-only expansion of camera_ids; never persist it.
  delete hw.cameras

  if (form.lane_reset_mode) {
    hw.lane_reset_mode = form.lane_reset_mode
  } else {
    delete hw.lane_reset_mode
  }

  if (form.lane_reset_seconds !== '' && form.lane_reset_seconds !== null && form.lane_reset_seconds !== undefined) {
    hw.lane_reset_seconds = Number(form.lane_reset_seconds)
  } else {
    delete hw.lane_reset_seconds
  }

  const cameraId = form._camera_id ? Number(form._camera_id) : null
  hw.camera_ids = cameraId ? [cameraId] : []
  hw.printer_id = form._printer_id ? Number(form._printer_id) : null
  hw.camera = { ...(hw.camera || {}), enabled: !!cameraId }
  hw.ticket_printer = { ...(hw.ticket_printer || {}), enabled: !!hw.printer_id }
  if (form.protocol === 'serial') {
    hw.open_command = form.open_command ?? hw.open_command ?? ''
    hw.close_command = form.close_command ?? hw.close_command ?? ''
    hw.close_delay_seconds = Number(form.close_delay_seconds ?? hw.close_delay_seconds ?? 3) || 3
  }

  if (form._rfid_enabled !== undefined) {
    hw.rfid = {
      enabled: form._rfid_enabled,
      wiegand_channel: 'W',
      connection: form._rfid_connection ?? 'controller',
      ...(form._rfid_connection === 'direct_serial' ? { device: form._rfid_device, baudrate: Number(form._rfid_baudrate) || 9600 } : {}),
    }
  }
  if (form._ticket_printer_enabled !== undefined) hw.ticket_printer = { enabled: form._ticket_printer_enabled }
  if (form._emoney_enabled !== undefined) {
    hw.emoney = {
      enabled: form._emoney_enabled,
      minimum_balance: 10000,
      connection: form._emoney_connection ?? 'controller',
      ...(form._emoney_connection === 'direct_serial' ? { device: form._emoney_device, baudrate: Number(form._emoney_baudrate) || 38400 } : {}),
    }
  }
  if (form._camera_enabled !== undefined) hw.camera = { enabled: form._camera_enabled }
  if (form._uhf_reader_enabled !== undefined) {
    hw.uhf_reader = {
      enabled: form._uhf_reader_enabled,
      ...(form._uhf_reader_enabled ? { host: form._uhf_reader_host || '', port: Number(form._uhf_reader_port) || 6000 } : {}),
    }
  }
  if (form._display_enabled !== undefined) hw.display = { enabled: form._display_enabled }
  if (form._audio_enabled !== undefined) hw.audio = { enabled: form._audio_enabled }
  return hw
}
function openGateModal(row = null) {
  gateEditing.value = !!row
  gateEditingHw.value = row?.hardware_config ? { ...row.hardware_config } : {}
  gateForm.value = row
    ? { ...row, ...flattenHardwareConfig(row.hardware_config) }
    : { direction: 'IN', protocol: 'compass', relay_mode: 'SINGLE', has_close_sensor: false, is_active: true, _rfid_connection: 'controller', _rfid_baudrate: 9600, _emoney_connection: 'controller', _emoney_baudrate: 38400 }
  gateModalVisible.value = true
}
async function saveGate(data) {
  submitting.value = true
  try {
    const payload = { ...data, hardware_config: buildHardwareConfig(data) }
    for (const k of ['_rfid_enabled', '_rfid_connection', '_rfid_device', '_rfid_baudrate', '_ticket_printer_enabled', '_emoney_enabled', '_emoney_connection', '_emoney_device', '_emoney_baudrate', '_camera_enabled', '_camera_id', '_printer_id', '_uhf_reader_enabled', '_display_enabled', '_audio_enabled', 'lane_reset_seconds', 'lane_reset_mode']) delete payload[k]
    if (gateEditing.value) await gateCrud.update(data.id, payload); else await gateCrud.create(payload)
    gateModalVisible.value = false
    await loadGates()
  } catch (err) { console.error(err) } finally { submitting.value = false }
}
function confirmDeleteGate(row) { deleteTargetName.value = row.name; deleteAction.value = () => deleteGate(row.id); deleteDialogVisible.value = true }
async function deleteGate(id) { submitting.value = true; try { await gateCrud.remove(id); deleteDialogVisible.value = false; await loadGates() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadGates() { loadingGates.value = true; try { gates.value = await gateCrud.list() } catch (err) { console.error(err) } finally { loadingGates.value = false } }

// POS Booths
const posList = ref([])
const loadingPos = ref(false)
const posModalVisible = ref(false)
const posEditing = ref(false)
const posForm = ref({})

// Foreign-key dropdown sources — show name+code, store id/code. Replaces the
// old raw numeric/text-code inputs (mislink-prone).
const gateOutOptions = computed(() =>
  gates.value.filter((g) => g.direction === 'OUT').map((g) => ({ label: `${g.name} (${g.code})`, value: g.id })),
)
const gateCodeOptions = computed(() =>
  gates.value.map((g) => ({ label: `${g.name} (${g.code})`, value: g.code })),
)
const posOptions = computed(() =>
  posList.value.map((p) => ({ label: `${p.name} (${p.code})`, value: p.id })),
)
function gateNameById(id) {
  const g = gates.value.find((x) => x.id === id)
  return g ? `${g.name} (${g.code})` : (id ?? '-')
}
const posColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'code', label: 'Kode', width: 120, sortable: true },
  { prop: 'ip_address', label: 'IP Address', width: 150 },
  { prop: 'default_gate_id', label: 'Gate Default', width: 180, formatter: (v) => gateNameById(v) },
  { prop: 'last_seen_at', label: 'Bridge', width: 110, formatter: (v) => {
    if (!v) return 'Belum pernah'
    const age = Date.now() - new Date(v).getTime()
    return age < 90_000 ? 'Online' : 'Offline'
  } },
  { prop: 'last_status', label: 'Relay', width: 110, formatter: (_, row) => {
    const st = row.last_status || {}
    if (!row.last_seen_at) return '-'
    return st.gate_connected ? 'Terhubung' : 'Tidak ada'
  } },
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const plateModeOptions = [
  { label: 'Tampil dengan awalan', value: 'prefix' },
  { label: 'Tampil tanpa awalan', value: 'plain' },
  { label: 'Sembunyikan', value: 'hidden' },
]
const posFields = computed(() => [
  { prop: 'name', label: 'Nama', type: 'text', required: true },
  { prop: 'code', label: 'Kode', type: 'text', required: true },
  { prop: 'ip_address', label: 'IP Address', type: 'text' },
  { prop: 'default_gate_id', label: 'Gate Default', type: 'select', options: gateOutOptions.value },
  { prop: '_camera_id', label: 'Kamera (perangkat)', type: 'select', options: cameraOptions.value },
  { prop: '_printer_id', label: 'Printer (perangkat)', type: 'select', options: printerOptions.value },
  { prop: '_plate_mode', label: 'Isian plat nomor di POS', type: 'select', options: plateModeOptions, helper: 'Awalan diambil dari Pengaturan (Awalan plat nomor di POS keluar). Pilih Sembunyikan bila kasir tidak memakai plat nomor.' },
  { prop: 'is_active', label: 'Aktif', type: 'boolean' },
])
function openPosModal(row = null) {
  posEditing.value = !!row
  const periph = row?.booth_peripherals || {}
  posForm.value = row
    ? {
        ...row,
        _camera_id: (periph.camera_ids && periph.camera_ids[0]) || null,
        _printer_id: periph.printer_id ?? null,
        _plate_mode: periph.ui?.plate_mode || (periph.ui?.show_plate === false ? 'hidden' : 'prefix'),
      }
    : { is_active: true, ip_address: '', _plate_mode: 'prefix' }
  posModalVisible.value = true
}
async function savePos(data) {
  submitting.value = true
  try {
    const payload = { ...data }
    payload.booth_peripherals = {
      ...(data.booth_peripherals || {}),
      camera_ids: data._camera_id ? [Number(data._camera_id)] : [],
      printer_id: data._printer_id ? Number(data._printer_id) : null,
      ui: { ...(data.booth_peripherals?.ui || {}), plate_mode: data._plate_mode || 'prefix' },
    }
    delete payload._camera_id
    delete payload._printer_id
    delete payload._plate_mode
    delete payload.booth_peripherals.ui.show_plate
    delete payload.booth_peripherals_patch
    if (posEditing.value) await posCrud.update(data.id, payload); else await posCrud.create(payload)
    posModalVisible.value = false
    await loadPos()
  } catch (err) { console.error(err) } finally { submitting.value = false }
}
function confirmDeletePos(row) { deleteTargetName.value = row.name; deleteAction.value = () => deletePos(row.id); deleteDialogVisible.value = true }
async function deletePos(id) { submitting.value = true; try { await posCrud.remove(id); deleteDialogVisible.value = false; await loadPos() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadPos() { loadingPos.value = true; try { posList.value = await posCrud.list() } catch (err) { console.error(err) } finally { loadingPos.value = false } }

// Cameras
const cameras = ref([])
const loadingCameras = ref(false)
const cameraModalVisible = ref(false)
const cameraEditing = ref(false)
const cameraForm = ref({})
const cameraColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'rtsp_url', label: 'RTSP URL', width: 250 },
  { prop: 'type', label: 'Tipe', width: 80 },
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const cameraFields = [
  { prop: 'name', label: 'Nama', type: 'text', required: true },
  { prop: 'rtsp_url', label: 'RTSP URL', type: 'text' },
  { prop: 'snapshot_url', label: 'Snapshot URL', type: 'text' },
  { prop: 'username', label: 'Username', type: 'text' },
  { prop: 'password', label: 'Password', type: 'text' },
  { prop: 'type', label: 'Tipe', type: 'select', options: [{ label: 'RTSP', value: 'rtsp' }, { label: 'ONVIF', value: 'onvif' }] },
  { prop: 'is_active', label: 'Aktif', type: 'boolean' },
]
function openCameraModal(row = null) { cameraEditing.value = !!row; cameraForm.value = row ? { ...row } : { type: 'rtsp', is_active: true }; cameraModalVisible.value = true }
async function saveCamera(data) { submitting.value = true; try { if (cameraEditing.value) await cameraCrud.update(data.id, data); else await cameraCrud.create(data); cameraModalVisible.value = false; await Promise.all([loadCameras(), loadCameraStatus()]) } catch (err) { console.error(err) } finally { submitting.value = false } }
function confirmDeleteCamera(row) { deleteTargetName.value = row.name; deleteAction.value = () => deleteCamera(row.id); deleteDialogVisible.value = true }
async function deleteCamera(id) { submitting.value = true; try { await cameraCrud.remove(id); deleteDialogVisible.value = false; await loadCameras() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadCameras() { loadingCameras.value = true; try { cameras.value = await cameraCrud.list() } catch (err) { console.error(err) } finally { loadingCameras.value = false } }

// Live reachability per camera id; a missing id means not probed yet.
const cameraStatus = ref({})
async function loadCameraStatus() { try { cameraStatus.value = await fetchApi('/api/cameras/status/summary') } catch (err) { cameraStatus.value = {}; console.error(err) } }
function cameraPill(camera) {
  if (!camera.is_active) return { status: 'idle', label: 'Nonaktif' }
  const ok = cameraStatus.value[camera.id]
  if (ok === undefined) return { status: 'idle', label: 'Belum diketahui' }
  return ok ? { status: 'online', label: 'Terhubung' } : { status: 'offline', label: 'Tidak terhubung' }
}

// Printers
const printers = ref([])
const loadingPrinters = ref(false)
const printerModalVisible = ref(false)
const printerEditing = ref(false)
const printerForm = ref({})
const printerColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'mode', label: 'Mode', width: 180 },
  { prop: 'gate_id', label: 'Gate', width: 100 },
  { prop: 'koneksi', label: 'Koneksi', width: 160, formatter: (_, row) => {
    if (row.mode === 'NETWORK') return `${row.ip_address || '-'}:${row.port || 9100}`
    if (row.mode === 'SERIAL') return `${row.serial_device || '-'} @ ${row.baudrate}`
    return 'Controller'
  }},
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const printerFields = computed(() => {
  const mode = printerForm.value.mode
  return [
    { prop: 'name', label: 'Nama', type: 'text', required: true },
    { prop: 'gate_id', label: 'Gate', type: 'select', required: true, options: gateCodeOptions.value },
    { prop: 'mode', label: 'Mode', type: 'select', required: true, options: [{ label: 'Otomatis (deteksi sendiri)', value: 'AUTO' }, { label: 'Controller Passthrough', value: 'CONTROLLER_PASSTHROUGH' }, { label: 'Network (TCP/IP)', value: 'NETWORK' }, { label: 'Serial / USB', value: 'SERIAL' }] },
    ...(mode === 'NETWORK'
      ? [
          { prop: 'ip_address', label: 'IP Address', type: 'text', required: true, placeholder: '192.168.1.x' },
          { prop: 'port', label: 'Port', type: 'number', placeholder: '9100' },
        ]
      : mode === 'SERIAL'
      ? [
          { prop: 'serial_device', label: 'Device Serial', type: 'text', required: true, placeholder: '/dev/parking-printer' },
          { prop: 'baudrate', label: 'Baudrate', type: 'number', placeholder: '9600' },
        ]
      : []
    ),
    { prop: 'is_active', label: 'Aktif', type: 'boolean' },
  ]
})
function openPrinterModal(row = null) { printerEditing.value = !!row; printerForm.value = row ? { ...row } : { mode: 'CONTROLLER_PASSTHROUGH', baudrate: 9600, port: 9100, is_active: true }; printerModalVisible.value = true }
async function savePrinter(data) { submitting.value = true; try { if (printerEditing.value) await printerCrud.update(data.id, data); else await printerCrud.create(data); printerModalVisible.value = false; await loadPrinters() } catch (err) { console.error(err) } finally { submitting.value = false } }
function confirmDeletePrinter(row) { deleteTargetName.value = row.name; deleteAction.value = () => deletePrinter(row.id); deleteDialogVisible.value = true }
async function deletePrinter(id) { submitting.value = true; try { await printerCrud.remove(id); deleteDialogVisible.value = false; await loadPrinters() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadPrinters() { loadingPrinters.value = true; try { printers.value = await printerCrud.list() } catch (err) { console.error(err) } finally { loadingPrinters.value = false } }

// E-Money Readers
const emoneyReaders = ref([])
const loadingEmoneyReaders = ref(false)
const emoneyReaderModalVisible = ref(false)
const emoneyReaderEditing = ref(false)
const emoneyReaderForm = ref({})
const emoneyReaderColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'code', label: 'Kode', width: 120, sortable: true },
  { prop: 'serial_port', label: 'Port Serial', width: 150 },
  { prop: 'baudrate', label: 'Baudrate', width: 100 },
  { prop: 'connection_type', label: 'Koneksi', width: 150, type: 'enum' },
  { prop: 'is_online', label: 'Online', type: 'boolean', width: 80 },
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const emoneyReaderFields = [
  { prop: 'name', label: 'Nama', type: 'text', required: true },
  { prop: 'code', label: 'Kode', type: 'text', required: true },
  { prop: 'connection_type', label: 'Tipe Koneksi', type: 'select', required: true, options: [{ label: 'Controller Passthrough', value: 'CONTROLLER_PASSTHROUGH' }, { label: 'Direct Serial', value: 'DIRECT_SERIAL' }, { label: 'Direct USB', value: 'DIRECT_USB' }] },
  { prop: 'serial_port', label: 'Port Serial', type: 'text', required: true },
  { prop: 'baudrate', label: 'Baudrate', type: 'number', required: true },
  { prop: 'mid', label: 'Merchant ID (MID)', type: 'text' },
  { prop: 'tid', label: 'Terminal ID (TID)', type: 'text' },
  { prop: 'encrypted_init_key', label: 'Init Key (Encrypted)', type: 'text' },
  { prop: 'is_active', label: 'Aktif', type: 'boolean' },
]
function openEmoneyReaderModal(row = null) { emoneyReaderEditing.value = !!row; emoneyReaderForm.value = row ? { ...row } : {}; emoneyReaderModalVisible.value = true }
async function saveEmoneyReader(data) { submitting.value = true; try { if (emoneyReaderEditing.value) await readerCrud.update(data.id, data); else await readerCrud.create(data); emoneyReaderModalVisible.value = false; await loadEmoneyReaders() } catch (err) { console.error(err) } finally { submitting.value = false } }
function confirmDeleteEmoneyReader(row) { deleteTargetName.value = row.name; deleteAction.value = () => deleteEmoneyReader(row.id); deleteDialogVisible.value = true }
async function deleteEmoneyReader(id) { submitting.value = true; try { await readerCrud.remove(id); deleteDialogVisible.value = false; await loadEmoneyReaders() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadEmoneyReaders() { loadingEmoneyReaders.value = true; try { emoneyReaders.value = await readerCrud.list() } catch (err) { console.error(err) } finally { loadingEmoneyReaders.value = false } }

// Delete dialog
const deleteDialogVisible = ref(false)
const deleteTargetName = ref('')
const deleteAction = ref(null)
function executeDelete() { if (deleteAction.value) deleteAction.value() }

// Auto-refresh the Overview tab so gate/peripheral status stays live without a
// manual reload. Only refetches while Overview is visible.
let overviewTimer = null
onMounted(() => {
  loadGates(); loadPos(); loadCameras(); loadCameraStatus(); loadPrinters(); loadEmoneyReaders()
  overviewTimer = setInterval(() => {
    if (activeTab.value === 'overview') {
      loadGates(); loadCameraStatus(); loadPrinters(); loadEmoneyReaders()
    }
  }, 15000)
})
onUnmounted(() => { if (overviewTimer) clearInterval(overviewTimer) })
</script>
