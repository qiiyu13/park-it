<template>
  <SetupShell
    :steps="steps"
    :current-index="currentIndex"
    :can-advance="canAdvance"
    :busy="busy"
    :autosaved-label="autosavedLabel"
    :final-step="isFinalStep"
    @next="onNext"
    @back="onBack"
    @navigate="onNavigate"
    @finalize="onFinalize"
    @help="showHelp = !showHelp"
  >
    <!-- Step: Welcome / Token redeem -->
    <section v-if="step === 'welcome'" class="space-y-6">
      <header class="space-y-2">
        <h2 class="text-2xl font-bold text-foreground">Selamat datang</h2>
        <p class="text-sm text-muted-foreground">
          Ayo siapkan E-Parking. Sekitar 20 menit. Anda butuh: IP controller, jaringan booth PC, dan perangkat keras menyala.
        </p>
      </header>

      <TokenGate
        v-if="!sessionActive"
        :loading="tokenLoading"
        :error="tokenError"
        @submit="redeemManualToken"
      />

      <div v-else class="space-y-4">
        <div class="rounded-lg border border-success/30 bg-success/10 p-4 text-sm text-success">
          ✓ Token setup tervalidasi. Sesi setup aktif.
        </div>

        <section class="space-y-3">
          <div class="flex items-center justify-between gap-2">
            <h3 class="text-sm font-semibold text-foreground">Pemeriksaan awal</h3>
            <Button variant="outline" size="sm" :disabled="preflightLoading" @click="runPreflight">
              {{ preflightLoading ? 'Memeriksa…' : 'Jalankan' }}
            </Button>
          </div>
          <PreflightList :checks="preflight.checks" />
          <p v-if="preflight.failed > 0" class="text-xs text-destructive">
            Ada {{ preflight.failed }} pemeriksaan gagal. Perbaiki sebelum lanjut.
          </p>
        </section>
      </div>
    </section>

    <!-- Step: Create admin -->
    <section v-else-if="step === 'admin'" class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Buat akun administrator</h2>
        <p class="text-sm text-muted-foreground">
          Akun pertama. Anda bisa menambah operator lain dari menu setelah wizard selesai.
        </p>
      </header>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <WizardField label="Username" required helper="Tanpa spasi. Contoh: admin">
          <Input v-model="form.admin.username" autocomplete="username" />
        </WizardField>
        <WizardField label="Nama lengkap" required>
          <Input v-model="form.admin.full_name" autocomplete="name" />
        </WizardField>
        <WizardField label="Email" required>
          <Input v-model="form.admin.email" type="email" autocomplete="email" />
        </WizardField>
        <div class="hidden sm:block" />
        <WizardField label="Password" required helper="Min. 8 karakter">
          <Input v-model="form.admin.password" type="password" autocomplete="new-password" />
        </WizardField>
        <WizardField
          label="Konfirmasi password"
          required
          :error="form.admin.password && form.admin.confirm && form.admin.password !== form.admin.confirm ? 'Password tidak cocok.' : ''"
        >
          <Input v-model="form.admin.confirm" type="password" autocomplete="new-password" />
        </WizardField>
      </div>

      <div v-if="errors.admin" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
        {{ errors.admin }}
      </div>
    </section>

    <!-- Step: Config (site + tariff + areas merged into one step) -->
    <div v-else-if="step === 'config'" class="space-y-10">
    <section class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Informasi lokasi</h2>
        <p class="text-sm text-muted-foreground">Muncul di struk dan laporan.</p>
      </header>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div class="space-y-4">
          <WizardField label="Nama lokasi" required>
            <Input v-model="form.site.name" placeholder="Parkir Mall ABC" />
          </WizardField>
          <WizardField label="Alamat">
            <Input v-model="form.site.address" placeholder="Jl. Sudirman No. 1" />
          </WizardField>
          <div class="grid grid-cols-2 gap-3">
            <WizardField label="Kota">
              <Input v-model="form.site.city" />
            </WizardField>
            <WizardField label="Telepon">
              <Input v-model="form.site.phone" placeholder="021-xxxx" />
            </WizardField>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <WizardField label="Email">
              <Input v-model="form.site.email" type="email" />
            </WizardField>
            <WizardField label="NPWP / Tax ID">
              <Input v-model="form.site.tax_id" />
            </WizardField>
          </div>
        </div>

        <aside class="rounded-lg border border-border bg-background p-4 font-mono text-xs text-foreground">
          <p class="mb-2 text-center text-muted-foreground">— Pratinjau Struk —</p>
          <p class="text-center text-base font-bold">{{ form.site.name || 'Parkir Anda' }}</p>
          <p v-if="form.site.address" class="text-center">{{ form.site.address }}</p>
          <p v-if="form.site.city" class="text-center">{{ form.site.city }}</p>
          <p v-if="form.site.phone" class="text-center">Telp. {{ form.site.phone }}</p>
          <p v-if="form.site.tax_id" class="text-center">NPWP {{ form.site.tax_id }}</p>
          <p class="my-2 border-t border-dashed border-border" />
          <p>Tiket #000001</p>
          <p>Motor — {{ today }}</p>
          <p>Rp 2.000</p>
        </aside>
      </div>
    </section>

    <!-- Tariff (presets + table) -->
    <section class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Jenis kendaraan & tarif</h2>
        <p class="text-sm text-muted-foreground">
          Pilih preset terdekat, lalu sesuaikan harga di tabel di bawah.
        </p>
      </header>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <TariffPresetCard
          v-for="preset in tariffPresets.presets"
          :key="preset.id"
          :preset="preset"
          :selected="form.tariff.preset === preset.id"
          @apply="applyPreset"
        />
      </div>

      <div class="rounded-lg border border-border bg-background overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-surface-hover text-xs uppercase text-muted-foreground">
            <tr>
              <th class="px-3 py-2 text-left">Nama</th>
              <th class="px-3 py-2 text-left">Kode</th>
              <th class="px-3 py-2 text-right">Tarif jam-1</th>
              <th class="px-3 py-2 text-right">Per jam</th>
              <th class="px-3 py-2 text-right">Cap harian</th>
              <th class="px-3 py-2 text-center">Progresif</th>
              <th class="px-3 py-2" />
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="(item, idx) in form.tariff.items" :key="idx">
              <td class="px-3 py-2"><Input v-model="item.name" class="h-8" /></td>
              <td class="px-3 py-2"><Input v-model="item.code" class="h-8 font-mono" /></td>
              <td class="px-3 py-2"><Input v-model.number="item.base_tariff" type="number" min="0" class="h-8 text-right" /></td>
              <td class="px-3 py-2"><Input v-model.number="item.hourly_rate" type="number" min="0" class="h-8 text-right" /></td>
              <td class="px-3 py-2"><Input v-model.number="item.max_daily_cap" type="number" min="0" class="h-8 text-right" /></td>
              <td class="px-3 py-2 text-center">
                <input v-model="item.is_progressive" type="checkbox" class="h-4 w-4 accent-primary" >
              </td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" @click="removeTariffItem(idx)">Hapus</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex justify-between">
        <Button variant="outline" @click="addTariffItem">+ Tambah jenis</Button>
        <p v-if="errors.tariff" class="text-xs text-destructive">{{ errors.tariff }}</p>
      </div>
    </section>

    <!-- Areas -->
    <section class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Area parkir & kapasitas</h2>
        <p class="text-sm text-muted-foreground">
          Setidaknya satu area. Tambah lagi nanti kalau perlu.
        </p>
      </header>

      <div class="rounded-lg border border-border bg-background overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-surface-hover text-xs uppercase text-muted-foreground">
            <tr>
              <th class="px-3 py-2 text-left">Nama area</th>
              <th class="px-3 py-2 text-left">Kode</th>
              <th class="px-3 py-2 text-right">Kapasitas</th>
              <th class="px-3 py-2" />
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="(area, idx) in form.areas" :key="idx">
              <td class="px-3 py-2"><Input v-model="area.name" class="h-8" placeholder="Area Utama" /></td>
              <td class="px-3 py-2"><Input v-model="area.code" class="h-8 font-mono" placeholder="MAIN" /></td>
              <td class="px-3 py-2"><Input v-model.number="area.capacity" type="number" min="0" class="h-8 text-right" /></td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" :disabled="form.areas.length <= 1" @click="removeArea(idx)">Hapus</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Button variant="outline" @click="addArea">+ Tambah area</Button>
      <p v-if="errors.areas" class="text-sm text-destructive">{{ errors.areas }}</p>
    </section>
    </div>

    <!-- Step: Topology -->
    <section v-else-if="step === 'topology'" class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Topologi sistem</h2>
        <p class="text-sm text-muted-foreground">
          Deteksi otomatis: <span class="font-mono text-foreground">{{ topologyLabel }}</span>.
          Pilih jumlah gate, kami buat baris di database supaya bisa diatur per gate.
        </p>
      </header>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <TopologyCard
          v-for="opt in topologyPresets"
          :key="opt.id"
          :in-count="opt.in"
          :out-count="opt.out"
          :label="opt.label"
          :description="opt.description"
          :selected="form.topology.preset === opt.id"
          @select="applyTopologyPreset(opt)"
        />
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <WizardField label="Jumlah pintu masuk">
          <Input v-model.number="form.topology.in_count" type="number" min="0" max="8" />
        </WizardField>
        <WizardField label="Jumlah pintu keluar">
          <Input v-model.number="form.topology.out_count" type="number" min="0" max="8" />
        </WizardField>
      </div>

      <label class="flex items-center gap-2 text-sm text-foreground">
        <input v-model="form.topology.include_local_serial" type="checkbox" class="h-4 w-4 accent-primary" >
        Jalankan daemon gate lokal di mesin ini (combo PC).
      </label>
    </section>

    <!-- Step: Gates -->
    <section v-else-if="step === 'gates'" class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Perangkat per gate</h2>
        <p class="text-sm text-muted-foreground">
          Atur controller dan peripheral untuk setiap gate. Tekan Deteksi untuk
          memetakan perangkat USB otomatis.
        </p>
      </header>

      <div v-if="!gates.length" class="rounded-lg border border-border bg-background p-6 text-sm text-muted-foreground">
        Belum ada gate. Kembali ke langkah Topologi.
      </div>

      <div v-else class="flex flex-wrap gap-2">
        <button
          v-for="(g, idx) in gates"
          :key="g.code"
          type="button"
          :class="[
            'rounded-full border px-3 py-1.5 text-xs font-medium',
            idx === gateTab
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border bg-background text-muted-foreground hover:bg-surface-hover',
          ]"
          @click="gateTab = idx"
        >
          {{ g.code }} · {{ g.direction }}
        </button>
      </div>

      <div v-if="activeGate" class="space-y-5 rounded-lg border border-border bg-background p-5">
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <WizardField label="Nama gate" required>
            <Input v-model="activeGate.name" />
          </WizardField>
          <WizardField label="Kode gate" helper="Tidak bisa diubah nanti">
            <Input v-model="activeGate.code" class="font-mono" />
          </WizardField>
        </div>

        <section class="space-y-3 rounded-md border border-border bg-surface p-4">
          <h3 class="text-sm font-semibold text-foreground">Controller</h3>
          <div class="flex gap-2">
            <button
              v-for="proto in ['compass', 'enet', 'serial']"
              :key="proto"
              type="button"
              :class="[
                'flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                activeGate.protocol === proto
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:bg-surface-hover',
              ]"
              @click="activeGate.protocol = proto"
            >
              {{ protocolLabel(proto) }}
            </button>
          </div>

          <DeviceProbeRow
            v-if="activeGate.protocol === 'serial'"
            type="serial"
            role="gate"
            :device="activeGate.controller_device || ''"
            :baudrate="activeGate.controller_baudrate || 9600"
            @update:device="(v) => activeGate.controller_device = v"
            @update:baudrate="(v) => activeGate.controller_baudrate = v"
          />
          <DeviceProbeRow
            v-else
            type="tcp"
            :host="activeGate.controller_host || ''"
            :port="activeGate.controller_port || 0"
            @update:host="(v) => activeGate.controller_host = v"
            @update:port="(v) => activeGate.controller_port = v"
          />
        </section>

        <section v-if="activeGate.id" class="rounded-md border border-border bg-muted/30 p-3">
          <h3 class="mb-2 text-sm font-semibold text-foreground">
            Uji buka/tutup gate (end-to-end)
          </h3>
          <p class="mb-2 text-xs text-muted-foreground">
            Perintah buka dikirim ke daemon via Redis, lalu menunggu ACK dari
            controller. Konfirmasi seluruh jalur software→hardware bekerja
            sebelum lanjut.
          </p>
          <GateTestButton :gate-id="activeGate.id" :gate-code="activeGate.code" />
        </section>

        <section class="space-y-2">
          <h3 class="text-sm font-semibold text-foreground">Perangkat tambahan</h3>
          <p class="text-xs text-muted-foreground">
            Perangkat booth (e-money, printer struk, scanner) diatur di booth PC
            saat instalasi, bukan di sini.
          </p>
          <PeripheralAccordion
            title="RFID member"
            :enabled="!!activeGate.peripherals.rfid.enabled"
            @update:enabled="(v) => togglePeripheral('rfid', v)"
          />
          <PeripheralAccordion
            title="Kamera"
            :enabled="!!activeGate.peripherals.camera.enabled"
            @update:enabled="(v) => togglePeripheral('camera', v)"
          >
            <WizardField label="RTSP URL">
              <Input v-model="activeGate.peripherals.camera.url" placeholder="rtsp://user:pass@host/stream1" />
            </WizardField>
          </PeripheralAccordion>
        </section>
      </div>
    </section>


    <section v-else-if="step === 'finalize'" class="space-y-5">
      <header class="space-y-1">
        <h2 class="text-xl font-bold text-foreground">Siap aktifkan</h2>
        <p class="text-sm text-muted-foreground">
          Tinjau konfigurasi, lalu klik "Aktifkan Gate &amp; Selesai" untuk menjalankan
          daemon dan menandai setup selesai.
        </p>
      </header>

      <ul class="rounded-lg border border-border bg-background p-4 text-sm text-foreground space-y-1">
        <li>✓ Lokasi: {{ form.site.name || '—' }}</li>
        <li>✓ {{ gates.length }} gate ({{ form.topology.in_count }} masuk · {{ form.topology.out_count }} keluar)</li>
        <li>✓ {{ form.tariff.items.length }} jenis kendaraan</li>
        <li>✓ {{ form.areas.length }} area parkir</li>
      </ul>
      <p class="text-xs text-muted-foreground">
        Booth POS dan perubahan perangkat lain diatur di halaman Perangkat setelah wizard selesai.
      </p>

      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-foreground">Pemeriksaan koneksi</h3>
          <Button variant="outline" size="sm" :disabled="finalizeChecking" @click="runFinalizeChecks">
            {{ finalizeChecking ? 'Memeriksa…' : 'Periksa ulang' }}
          </Button>
        </div>
        <div v-if="!finalizeChecks.length" class="text-sm text-muted-foreground">
          Klik "Periksa ulang" untuk menguji controller dan peripheral setiap gate.
        </div>
        <ul v-else class="space-y-1 text-sm">
          <li
            v-for="check in finalizeChecks"
            :key="check.id"
            class="flex items-center justify-between rounded-md border border-border bg-background px-3 py-2"
          >
            <span class="font-medium">{{ check.label }}</span>
            <StatusPill :status="check.status" :label="check.detail" />
          </li>
        </ul>
      </section>

      <section v-if="finalizing || finalizeLog.length" class="space-y-2">
        <h3 class="text-sm font-semibold text-foreground">Aktivasi</h3>
        <div class="max-h-64 overflow-y-auto rounded-lg border border-border bg-black/40 p-4 font-mono text-xs text-foreground">
          <p v-for="(line, i) in finalizeLog" :key="i">{{ line }}</p>
          <p v-if="finalizing" class="text-muted-foreground">⟳ Mengaktifkan layanan…</p>
        </div>
      </section>

      <p v-if="finalizeError" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
        {{ finalizeError }}
      </p>
    </section>

    <!-- Generic error banner -->
    <div
      v-if="errors.generic"
      class="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
    >
      {{ errors.generic }}
    </div>
  </SetupShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import SetupShell from '~/components/setup/SetupShell.vue'
import TokenGate from '~/components/setup/TokenGate.vue'
import PreflightList from '~/components/setup/PreflightList.vue'
import TariffPresetCard from '~/components/setup/TariffPresetCard.vue'
import TopologyCard from '~/components/setup/TopologyCard.vue'
import DeviceProbeRow from '~/components/setup/DeviceProbeRow.vue'
import GateTestButton from '~/components/setup/GateTestButton.vue'
import PeripheralAccordion from '~/components/setup/PeripheralAccordion.vue'
import StatusPill from '~/components/setup/StatusPill.vue'
import WizardField from '~/components/setup/WizardField.vue'
import { useTariffPresets } from '~/composables/useTariffPresets'

const topologyPresets = [
  { id: '1in_1out', in: 1, out: 1, label: '1 In + 1 Out', description: 'Lokasi kecil, satu pintu masuk-keluar.' },
  { id: '2in_2out', in: 2, out: 2, label: '2 In + 2 Out', description: 'Mall / perkantoran sedang.' },
  { id: '1in_2out', in: 1, out: 2, label: '1 In + 2 Out', description: 'Aliran keluar lebih sibuk dari masuk.' },
  { id: 'custom', in: 1, out: 1, label: 'Kustom', description: 'Atur sendiri jumlah pintu.' },
]

const protocolLabels = {
  compass: 'Compass / TCP',
  enet: 'ENET / TCP',
  serial: 'Serial (USB)',
}
function protocolLabel(p) { return protocolLabels[p] || p }

definePageMeta({ layout: false, middleware: 'auth' })

const route = useRoute()
const router = useRouter()
const { fetchApi } = useApi()
const tariffPresets = useTariffPresets()

const today = new Date().toLocaleDateString('id-ID', { year: 'numeric', month: 'short', day: 'numeric' })

// Step order groups all paperwork (admin → site → tariff → areas) before any
// physical-hardware work (topology → gates), so the tech only walks to the
// gates once. Booth-bridge configuration is intentionally out of scope —
// configure booths from the Pengaturan page after the wizard finishes.
const steps = [
  { key: 'welcome', label: 'Mulai' },
  { key: 'admin', label: 'Admin' },
  { key: 'config', label: 'Konfigurasi' },
  { key: 'topology', label: 'Topologi' },
  { key: 'gates', label: 'Gate' },
  { key: 'finalize', label: 'Selesai' },
]

const currentIndex = ref(0)
const step = computed(() => steps[currentIndex.value].key)
const isFinalStep = computed(() => step.value === 'finalize')
const busy = ref(false)
const showHelp = ref(false)
const autosavedLabel = ref('')

const state = reactive({
  topology: 'unknown',
  setup_complete: false,
  has_admin: false,
  has_session: false,
})

const sessionActive = ref(false)
const tokenLoading = ref(false)
const tokenError = ref('')

const preflight = reactive({ checks: [], passed: 0, warnings: 0, failed: 0 })
const preflightLoading = ref(false)
const finalizeError = ref('')
const finalizeChecks = ref([])
const finalizeChecking = ref(false)
const finalizing = ref(false)
const finalizeLog = ref([])

const form = reactive({
  admin: { username: 'admin', full_name: '', email: '', password: '', confirm: '' },
  site: { name: '', address: '', city: '', phone: '', email: '', tax_id: '' },
  topology: { preset: null, in_count: 1, out_count: 1, include_local_serial: false },
  tariff: {
    preset: null,
    items: [],
  },
  areas: [{ name: 'Area Utama', code: 'MAIN', capacity: 100 }],
})

const gates = ref([])
const gateTab = ref(0)
const activeGate = computed(() => gates.value[gateTab.value] || null)

const topologyLabel = computed(() => {
  return {
    combo: 'Server + Booth lokal',
    server_only: 'Server saja',
    booth_only: 'Booth saja',
    unknown: 'Belum terdeteksi',
  }[state.topology] || state.topology
})

function applyTopologyPreset(opt) {
  form.topology.preset = opt.id
  if (opt.id !== 'custom') {
    form.topology.in_count = opt.in
    form.topology.out_count = opt.out
  }
}

// Only gate-attached peripherals belong here. Booth devices (e-money reader,
// receipt printer, scanner) live in booth.json on the booth PC, configured by
// the installer — not per gate. rfid is read by gate_in; camera by the gate
// model. printer/emoney/uhf were set-but-never-read, so they're gone.
function blankPeripherals() {
  return {
    rfid: { enabled: false },
    camera: { enabled: false, url: '' },
  }
}

function togglePeripheral(key, on) {
  if (!activeGate.value) return
  activeGate.value.peripherals[key].enabled = on
}

async function loadGatesFromBackend() {
  try {
    const res = await fetchApi('/api/gates')
    const rows = Array.isArray(res) ? res : (res?.items || [])
    gates.value = rows.map((g, idx) => {
      const isTcp = (g.protocol || 'compass') !== 'serial'
      return {
        id: g.id,
        name: g.name,
        code: g.code,
        direction: g.direction,
        protocol: g.protocol || 'compass',
        // Prefill an incrementing controller IP for fresh TCP gates (.100,
        // .101, .102…) so the tech mostly hits Enter instead of typing each
        // one. A saved value always wins; this only fills blanks.
        controller_host: g.controller_host || (isTcp ? `192.168.1.${100 + idx}` : ''),
        controller_port: g.controller_port || (isTcp ? 5000 : 0),
        controller_device: g.controller_device || '',
        controller_baudrate: g.controller_baudrate || 9600,
        peripherals: hydratePeripherals(g.hardware_config),
      }
    })
    if (gateTab.value >= gates.value.length) gateTab.value = 0
  } catch (err) {
    console.warn('load_gates_failed', err)
  }
}

function hydratePeripherals(hardware_config) {
  const out = blankPeripherals()
  const hc = hardware_config || {}
  for (const k of ['rfid', 'camera']) {
    if (hc[k]) Object.assign(out[k], hc[k])
  }
  return out
}

const errors = reactive({ admin: '', tariff: '', areas: '', generic: '' })

const authStore = useAuthStore()

const canAdvance = computed(() => {
  if (step.value === 'welcome') return sessionActive.value && preflight.failed === 0
  if (step.value === 'admin') {
    if (state.has_admin) return true
    return (
      form.admin.username && form.admin.full_name && form.admin.email &&
      form.admin.password && form.admin.password === form.admin.confirm
    )
  }
  if (step.value === 'config') {
    return (
      !!form.site.name &&
      form.tariff.items.length > 0 &&
      form.areas.every((a) => a.name && a.code && a.capacity >= 0)
    )
  }
  if (step.value === 'topology') return (form.topology.in_count + form.topology.out_count) > 0
  if (step.value === 'gates') return gates.value.length > 0
  return true
})

async function refreshState() {
  try {
    const s = await fetchApi('/api/setup/state')
    state.topology = s.topology
    state.setup_complete = s.setup_complete
    state.has_admin = s.has_admin
    state.has_session = s.has_session
    sessionActive.value = s.has_session || (!!authStore.user && authStore.user.role === 'admin')
  } catch (err) {
    console.warn('setup_state_failed', err)
  }
}

async function redeemAutoToken() {
  const token = route.query.token
  if (!token) return
  tokenLoading.value = true
  try {
    await fetchApi('/api/setup/redeem-token', {
      method: 'POST',
      body: JSON.stringify({ token }),
    })
    sessionActive.value = true
    tokenError.value = ''
    router.replace({ path: '/setup', query: { ...route.query, token: undefined } })
  } catch (err) {
    tokenError.value = err.message
  } finally {
    tokenLoading.value = false
  }
}

async function redeemManualToken(token) {
  tokenLoading.value = true
  tokenError.value = ''
  try {
    await fetchApi('/api/setup/redeem-token', {
      method: 'POST',
      body: JSON.stringify({ token }),
    })
    sessionActive.value = true
  } catch (err) {
    tokenError.value = err.message
  } finally {
    tokenLoading.value = false
  }
}

async function runPreflight() {
  preflightLoading.value = true
  try {
    const result = await fetchApi('/api/setup/preflight')
    Object.assign(preflight, result)
  } catch (err) {
    errors.generic = `Preflight gagal: ${err.message}`
  } finally {
    preflightLoading.value = false
  }
}

function applyPreset(presetId) {
  const preset = tariffPresets.clonePreset(presetId)
  if (!preset) return
  form.tariff.preset = presetId
  form.tariff.items = preset.items.map((item, idx) => ({
    name: item.name,
    code: item.name.toUpperCase().slice(0, 4) + (idx > 0 ? String(idx) : ''),
    base_tariff: item.first_hour_rate,
    hourly_rate: item.per_hour_rate,
    max_daily_cap: item.daily_cap,
    overnight_mode: 'midnight',
    overnight_tariff: 0,
    lost_ticket_penalty: 0,
    is_progressive: item.rate_type === 'progressive',
  }))
}

function addTariffItem() {
  form.tariff.items.push({
    name: '', code: '', base_tariff: 0, hourly_rate: 0, max_daily_cap: 0,
    overnight_mode: 'midnight', overnight_tariff: 0, lost_ticket_penalty: 0,
    is_progressive: false,
  })
}

function removeTariffItem(idx) {
  form.tariff.items.splice(idx, 1)
}

function addArea() {
  form.areas.push({ name: '', code: '', capacity: 0 })
}

function removeArea(idx) {
  if (form.areas.length <= 1) return
  form.areas.splice(idx, 1)
}

async function persistStep(stepKey, data) {
  if (!sessionActive.value && !(authStore.user && authStore.user.role === 'admin')) return
  try {
    await fetchApi('/api/setup/state', {
      method: 'POST',
      body: JSON.stringify({ step: stepKey, data }),
    })
    autosavedLabel.value = `Tersimpan ${new Date().toLocaleTimeString('id-ID')}`
  } catch (err) {
    console.warn('save_step_failed', err)
  }
}

async function saveCurrentStep() {
  if (step.value === 'admin' && !state.has_admin) {
    if (form.admin.password !== form.admin.confirm) {
      errors.admin = 'Password tidak cocok.'
      return false
    }
    try {
      busy.value = true
      const { confirm, ...payload } = form.admin
      await fetchApi('/api/setup/create-admin', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      state.has_admin = true
      await authStore.fetchUser()
      errors.admin = ''
    } catch (err) {
      errors.admin = err.message
      return false
    } finally {
      busy.value = false
    }
  } else if (step.value === 'config') {
    if (!form.tariff.items.length) {
      errors.tariff = 'Tambahkan minimal satu jenis kendaraan.'
      return false
    }
    try {
      busy.value = true
      await fetchApi('/api/site-config', {
        method: 'PUT',
        body: JSON.stringify(form.site),
      })
      for (const item of form.tariff.items) {
        await fetchApi('/api/vehicle-types', {
          method: 'POST',
          body: JSON.stringify({
            name: item.name,
            code: item.code,
            base_tariff: item.base_tariff,
            hourly_rate: item.hourly_rate,
            max_daily_cap: item.max_daily_cap,
            overnight_mode: item.overnight_mode,
            overnight_tariff: item.overnight_tariff,
            lost_ticket_penalty: item.lost_ticket_penalty,
            is_progressive: item.is_progressive,
          }),
        }).catch((err) => {
          if (err.status !== 409) throw err
        })
      }
      for (const area of form.areas) {
        await fetchApi('/api/areas', {
          method: 'POST',
          body: JSON.stringify(area),
        }).catch((err) => {
          if (err.status !== 409) throw err
        })
      }
      errors.tariff = ''
      errors.areas = ''
    } catch (err) {
      errors.generic = `Gagal simpan konfigurasi: ${err.message}`
      return false
    } finally {
      busy.value = false
    }
  } else if (step.value === 'topology') {
    try {
      busy.value = true
      await fetchApi('/api/setup/topology', {
        method: 'POST',
        body: JSON.stringify({
          in_count: form.topology.in_count,
          out_count: form.topology.out_count,
          include_local_serial: form.topology.include_local_serial,
        }),
      })
      await loadGatesFromBackend()
    } catch (err) {
      errors.generic = `Gagal apply topologi: ${err.message}`
      return false
    } finally {
      busy.value = false
    }
  } else if (step.value === 'gates') {
    try {
      busy.value = true
      for (const g of gates.value) {
        const hc = {}
        for (const [k, cfg] of Object.entries(g.peripherals)) {
          if (cfg.enabled) hc[k] = { ...cfg }
        }
        await fetchApi(`/api/gates/${g.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            name: g.name,
            protocol: g.protocol,
            controller_host: g.controller_host || null,
            controller_port: g.controller_port || null,
            controller_device: g.controller_device || null,
            controller_baudrate: g.controller_baudrate || null,
            hardware_config: hc,
          }),
        })
      }
    } catch (err) {
      errors.generic = `Gagal simpan gate: ${err.message}`
      return false
    } finally {
      busy.value = false
    }
  }
  await persistStep(step.value, snapshotForStep(step.value))
  return true
}

function snapshotForStep(stepKey) {
  if (stepKey === 'admin') {
    const { password, confirm, ...safe } = form.admin
    return safe
  }
  if (stepKey === 'config') {
    return {
      site: { ...form.site },
      tariff: { preset: form.tariff.preset, items: form.tariff.items },
      areas: form.areas,
    }
  }
  if (stepKey === 'topology') return { ...form.topology }
  if (stepKey === 'gates') return { gates: gates.value }
  return {}
}

async function onNext() {
  errors.generic = ''
  const ok = await saveCurrentStep()
  if (!ok) return
  currentIndex.value = Math.min(steps.length - 1, currentIndex.value + 1)
}

function onBack() {
  currentIndex.value = Math.max(0, currentIndex.value - 1)
}

function onNavigate(idx) {
  if (idx <= currentIndex.value) currentIndex.value = idx
}

async function runFinalizeChecks() {
  finalizeChecking.value = true
  const checks = []
  try {
    for (const g of gates.value) {
      const id = `${g.code}-controller`
      const body = g.protocol === 'serial'
        ? { type: 'serial', device: g.controller_device || '', baudrate: g.controller_baudrate || 9600 }
        : { type: 'tcp', host: g.controller_host || '', port: g.controller_port || 0 }
      if (!body.device && !(body.host && body.port)) {
        checks.push({ id, label: `${g.code} controller`, status: 'warning', detail: 'belum diatur' })
        continue
      }
      try {
        const res = await fetchApi('/api/setup/test-device', { method: 'POST', body: JSON.stringify(body) })
        checks.push({
          id,
          label: `${g.code} controller`,
          status: res.ok ? 'online' : 'offline',
          detail: res.ok ? `${Math.round(res.latency_ms || 0)}ms` : (res.error || 'gagal'),
        })
      } catch (err) {
        checks.push({ id, label: `${g.code} controller`, status: 'offline', detail: err.message })
      }

      for (const [name, cfg] of Object.entries(g.peripherals)) {
        if (!cfg.enabled || !cfg.device) continue
        try {
          const res = await fetchApi('/api/setup/test-device', {
            method: 'POST',
            body: JSON.stringify({ type: 'serial', device: cfg.device, baudrate: cfg.baudrate || 9600 }),
          })
          checks.push({
            id: `${g.code}-${name}`,
            label: `${g.code} ${name}`,
            status: res.ok ? 'online' : 'offline',
            detail: res.ok ? 'siap' : (res.error || 'gagal'),
          })
        } catch (err) {
          checks.push({ id: `${g.code}-${name}`, label: `${g.code} ${name}`, status: 'offline', detail: err.message })
        }
      }
    }
  } finally {
    finalizeChecks.value = checks
    finalizeChecking.value = false
  }
}

async function onFinalize() {
  finalizeError.value = ''
  finalizing.value = true
  finalizeLog.value = []
  busy.value = true
  try {
    const res = await fetchApi('/api/setup/finalize', { method: 'POST' })
    if (res.log) finalizeLog.value = res.log
    if (!res.ok) {
      finalizeError.value = res.error || 'Aktivasi gagal.'
      return
    }
    await router.push('/')
  } catch (err) {
    finalizeError.value = err.message
  } finally {
    finalizing.value = false
    busy.value = false
  }
}

watch(
  () => [form.site, form.admin, form.tariff, form.areas],
  () => { autosavedLabel.value = '' },
  { deep: true },
)

onMounted(async () => {
  await refreshState()
  // Post-setup the wizard is locked. Steady-state config lives in Device + Settings.
  // The ONLY re-entry is an installer action: regen-setup-token.sh (or field-reconfig.sh)
  // mints a fresh disk token, opened as /setup?token=…, which TokenGate redeems into a
  // session. No live session AND no token presented ⇒ bounce. Admins cannot re-run the
  // wizard merely by navigating here — they must hold the disk token.
  if (state.setup_complete && !state.has_session && !route.query.token) {
    router.replace('/')
    return
  }
  await redeemAutoToken()
  if (state.has_admin) {
    // Skip admin creation step when an admin already exists.
    currentIndex.value = 1
    await loadGatesFromBackend()
  }
})

watch(() => step.value, async (next) => {
  if (next === 'gates' && !gates.value.length) {
    await loadGatesFromBackend()
  }
})
</script>
