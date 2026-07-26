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
      <div v-else-if="!gates.length" class="border-2 border-foreground bg-surface p-6 text-sm font-medium text-muted-foreground shadow-brutal">
        Belum ada gate. Tambah dari tab Gates atau jalankan Setup Wizard.
      </div>
      <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <GateStatusCard
          v-for="gate in gates"
          :key="gate.id"
          :gate="gate"
          :testing="testingGateId === gate.id"
          @edit="openGateModal(gate)"
          @test="testGate(gate)"
          @open="openGateRemotely(gate)"
        />
      </div>

      <!-- Peripheral health: printers + e-money readers at a glance -->
      <div v-if="!loadingGates && (printers.length || emoneyReaders.length)" class="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div v-if="printers.length" class="border-2 border-foreground bg-surface p-4 shadow-brutal">
          <h3 class="mb-3 text-sm font-black uppercase tracking-wide text-foreground border-b-2 border-foreground pb-2">Printer</h3>
          <div class="space-y-2">
            <div v-for="p in printers" :key="p.id" class="flex items-center justify-between gap-2 text-sm">
              <span class="truncate font-medium text-foreground">{{ p.name }}</span>
              <div class="flex shrink-0 items-center gap-2">
                <span v-if="p.paper_remaining != null" class="text-xs text-muted-foreground">kertas {{ p.paper_remaining }}</span>
                <StatusPill :status="p.is_active ? 'online' : 'idle'" :label="p.is_active ? 'Aktif' : 'Nonaktif'" />
              </div>
            </div>
          </div>
        </div>
        <div v-if="emoneyReaders.length" class="border-2 border-foreground bg-surface p-4 shadow-brutal">
          <h3 class="mb-3 text-sm font-black uppercase tracking-wide text-foreground border-b-2 border-foreground pb-2">E-Money Reader</h3>
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
            class="border-2 border-transparent p-1.5 text-muted-foreground transition-all hover:border-foreground hover:bg-primary hover:text-foreground hover:shadow-brutal-sm disabled:opacity-40"
            :title="testingGateId === row.id ? 'Menguji…' : 'Test koneksi'"
            :disabled="testingGateId === row.id"
            @click="testGate(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
          </button>
          <button
            class="border-2 border-transparent p-1.5 text-muted-foreground transition-all hover:border-foreground hover:bg-success hover:text-white hover:shadow-brutal-sm"
            title="Buka gate"
            @click="openGateRemotely(row)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 9.9-1" /></svg>
          </button>
          <button
            class="border-2 border-transparent p-1.5 text-muted-foreground transition-all hover:border-foreground hover:bg-warning hover:text-foreground hover:shadow-brutal-sm"
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
      <DataTable :data="cameras" :columns="cameraColumns" :loading="loadingCameras" @add="openCameraModal()" @edit="openCameraModal" @delete="confirmDeleteCamera" />
    </div>

    <!-- Printers -->
    <div v-if="activeTab === 'printers'">
      <DataTable :data="printers" :columns="printerColumns" :loading="loadingPrinters" @add="openPrinterModal()" @edit="openPrinterModal" @delete="confirmDeletePrinter" />
    </div>

    <!-- E-Money Readers -->
    <div v-if="activeTab === 'emoney-readers'">
      <DataTable :data="emoneyReaders" :columns="emoneyReaderColumns" :loading="loadingEmoneyReaders" @add="openEmoneyReaderModal()" @edit="openEmoneyReaderModal" @delete="confirmDeleteEmoneyReader" />
    </div>

    <!-- Serial Tools: detect ports + pin a stable /dev/parking-<role> udev symlink. -->
    <!-- Closes the post-setup gap where remapping a swapped USB device was wizard-only. -->
    <div v-if="activeTab === 'serial-tools'" class="max-w-2xl space-y-5">
      <div class="space-y-4 border-2 border-foreground bg-surface p-5 shadow-brutal">
        <div class="space-y-1">
          <h3 class="text-sm font-black uppercase tracking-wide text-foreground">Deteksi &amp; Pasang Perangkat Serial</h3>
          <p class="text-xs text-muted-foreground">
            Gunakan saat mengganti atau memasang ulang perangkat USB/serial. Pilih peran, deteksi port, uji,
            lalu pasang sebagai <span class="font-mono">/dev/parking-&lt;peran&gt;</span> agar nama perangkat tetap walau dicabut-pasang.
            Setelah terpasang, salin path tersebut ke field <em>Device</em> pada gate/printer/e-money terkait.
          </p>
        </div>

        <div class="space-y-2">
          <label class="text-sm font-bold uppercase tracking-wide text-foreground">Peran perangkat</label>
          <select
            v-model="serialRole"
            class="w-full border-2 border-foreground bg-background px-3 py-2 text-sm font-medium shadow-brutal-sm sm:w-72"
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

        <p v-if="lastSymlink" class="border-2 border-foreground bg-success px-3 py-2 text-xs font-bold text-white shadow-brutal-sm">
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
  </div>
</template>

<script setup>
import GateStatusCard from '~/components/dashboard/GateStatusCard.vue'
import StatusPill from '~/components/setup/StatusPill.vue'
import DeviceProbeRow from '~/components/setup/DeviceProbeRow.vue'
import GateTestButton from '~/components/setup/GateTestButton.vue'
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

async function testGate(gate) {
  testingGateId.value = gate.id
  try {
    const body = gate.protocol === 'serial'
      ? { type: 'serial', device: gate.controller_device, baudrate: gate.controller_baudrate || 9600 }
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
    await fetchApi(`/api/gates/${gate.id}/open`, { method: 'POST' })
    const { toast } = await import('vue-sonner')
    toast.success(`${gate.code} dibuka`)
  } catch (err) {
    const { toast } = await import('vue-sonner')
    toast.error(err.message)
  }
}

// Gates
const gates = ref([])
const loadingGates = ref(false)
const gateModalVisible = ref(false)
const gateEditing = ref(false)
const gateForm = ref({})
const gateColumns = [
  { prop: 'name', label: 'Nama', sortable: true },
  { prop: 'code', label: 'Kode', width: 120, sortable: true },
  { prop: 'direction', label: 'Arah', width: 80, type: 'enum' },
  { prop: 'protocol', label: 'Protokol', width: 100 },
  { prop: 'controller_host', label: 'Host / Device', width: 160, formatter: (row) => row.protocol === 'serial' ? (row.controller_device || '-') : (row.controller_host || '-') },
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const RFID_CONN_OPTIONS = [{ label: 'Controller (Wiegand)', value: 'controller' }, { label: 'Serial Langsung / USB', value: 'direct_serial' }]
const EMONEY_CONN_OPTIONS = [{ label: 'Controller (QR5 Tunnel)', value: 'controller' }, { label: 'Serial Langsung / USB', value: 'direct_serial' }]

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
        ]
      : [
          { prop: 'controller_host', label: 'Host Controller', type: 'ip-scan', portProp: 'controller_port', placeholder: '192.168.1.x', required: true },
          { prop: 'controller_port', label: 'Port Controller', type: 'number', placeholder: '4001', required: true },
        ]
    ),
    { prop: 'has_close_sensor', label: 'Sensor Tutup', type: 'boolean' },
    { prop: 'relay_mode', label: 'Mode Relay', type: 'select', options: [{ label: 'Single (1 relay)', value: 'SINGLE' }, { label: 'Dual (2 relay)', value: 'DUAL' }, { label: 'Triple (3 relay)', value: 'TRIPLE' }] },
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
      { prop: '_emoney_enabled', label: 'E-Money', type: 'boolean' },
      { prop: '_camera_enabled', label: 'Kamera', type: 'boolean' },
      { prop: '_display_enabled', label: 'Modul Display (LED)', type: 'boolean', helper: 'Centang HANYA jika controller punya modul display. cmd_ds ke controller tanpa display akan disconnect.' },
      { prop: '_audio_enabled', label: 'Modul Audio (MP3)', type: 'boolean' },
    )
  } else if (dir === 'OUT') {
    base.push(
      { prop: 'pos_id', label: 'Booth POS', type: 'select', options: posOptions.value },
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
    _uhf_reader_enabled: hw.uhf_reader?.enabled ?? false,
    _uhf_reader_host: hw.uhf_reader?.host ?? '',
    _uhf_reader_port: hw.uhf_reader?.port ?? 6000,
    _display_enabled: hw.display?.enabled ?? false,
    _audio_enabled: hw.audio?.enabled ?? false,
  }
}
function buildHardwareConfig(form) {
  const hw = {}
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
  gateForm.value = row
    ? { ...row, ...flattenHardwareConfig(row.hardware_config) }
    : { direction: 'IN', protocol: 'compass', relay_mode: 'SINGLE', has_close_sensor: false, is_active: true, _rfid_connection: 'controller', _rfid_baudrate: 9600, _emoney_connection: 'controller', _emoney_baudrate: 38400 }
  gateModalVisible.value = true
}
async function saveGate(data) {
  submitting.value = true
  try {
    const payload = { ...data, hardware_config: buildHardwareConfig(data) }
    for (const k of ['_rfid_enabled', '_rfid_connection', '_rfid_device', '_rfid_baudrate', '_ticket_printer_enabled', '_emoney_enabled', '_emoney_connection', '_emoney_device', '_emoney_baudrate', '_camera_enabled', '_uhf_reader_enabled', '_display_enabled', '_audio_enabled']) delete payload[k]
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
  { prop: 'is_active', label: 'Aktif', type: 'boolean', width: 80 },
]
const posFields = computed(() => [
  { prop: 'name', label: 'Nama', type: 'text', required: true },
  { prop: 'code', label: 'Kode', type: 'text', required: true },
  { prop: 'ip_address', label: 'IP Address', type: 'text' },
  { prop: 'default_gate_id', label: 'Gate Default', type: 'select', options: gateOutOptions.value },
  { prop: 'is_active', label: 'Aktif', type: 'boolean' },
])
function openPosModal(row = null) { posEditing.value = !!row; posForm.value = row ? { ...row } : { is_active: true }; posModalVisible.value = true }
async function savePos(data) { submitting.value = true; try { if (posEditing.value) await posCrud.update(data.id, data); else await posCrud.create(data); posModalVisible.value = false; await loadPos() } catch (err) { console.error(err) } finally { submitting.value = false } }
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
async function saveCamera(data) { submitting.value = true; try { if (cameraEditing.value) await cameraCrud.update(data.id, data); else await cameraCrud.create(data); cameraModalVisible.value = false; await loadCameras() } catch (err) { console.error(err) } finally { submitting.value = false } }
function confirmDeleteCamera(row) { deleteTargetName.value = row.name; deleteAction.value = () => deleteCamera(row.id); deleteDialogVisible.value = true }
async function deleteCamera(id) { submitting.value = true; try { await cameraCrud.remove(id); deleteDialogVisible.value = false; await loadCameras() } catch (err) { console.error(err) } finally { submitting.value = false } }
async function loadCameras() { loadingCameras.value = true; try { cameras.value = await cameraCrud.list() } catch (err) { console.error(err) } finally { loadingCameras.value = false } }

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
  { prop: 'gate_type', label: 'Tipe', width: 70 },
  { prop: 'paper_remaining', label: 'Sisa Kertas', width: 110 },
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
    { prop: 'gate_type', label: 'Tipe Gate', type: 'select', required: true, options: [{ label: 'Masuk (IN)', value: 'IN' }, { label: 'Keluar (OUT)', value: 'OUT' }] },
    { prop: 'mode', label: 'Mode', type: 'select', required: true, options: [{ label: 'Controller Passthrough', value: 'CONTROLLER_PASSTHROUGH' }, { label: 'Network (TCP/IP)', value: 'NETWORK' }, { label: 'Serial / USB', value: 'SERIAL' }] },
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
    { prop: 'paper_remaining', label: 'Sisa Kertas', type: 'number' },
    { prop: 'is_active', label: 'Aktif', type: 'boolean' },
  ]
})
function openPrinterModal(row = null) { printerEditing.value = !!row; printerForm.value = row ? { ...row } : { mode: 'CONTROLLER_PASSTHROUGH', gate_type: 'OUT', baudrate: 9600, port: 9100, is_active: true }; printerModalVisible.value = true }
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
  loadGates(); loadPos(); loadCameras(); loadPrinters(); loadEmoneyReaders()
  overviewTimer = setInterval(() => {
    if (activeTab.value === 'overview') {
      loadGates(); loadPrinters(); loadEmoneyReaders()
    }
  }, 15000)
})
onUnmounted(() => { if (overviewTimer) clearInterval(overviewTimer) })
</script>
