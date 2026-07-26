<template>
  <div>
    <PageHeader title="Jadwal & Sesi" subtitle="Jadwal penugasan petugas dan rekap sesi kerja harian." />

    <TabStrip :model-value="activeTab" :tabs="tabs" @update:model-value="switchTab" />

    <!-- Date filter (shared) -->
    <div class="mb-4 flex items-center gap-3">
      <button class="rounded-md border border-border bg-surface px-2 py-1.5 text-sm hover:bg-surface-hover" @click="changeDate(-1)">←</button>
      <input
        v-model="selectedDate"
        type="date"
        class="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
        @change="loadData"
      >
      <button class="rounded-md border border-border bg-surface px-2 py-1.5 text-sm hover:bg-surface-hover" @click="changeDate(1)">→</button>
      <button class="rounded-md border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-hover" @click="goToday">Hari ini</button>
      <span class="text-sm text-muted-foreground">{{ formattedDay }}</span>
    </div>

    <!-- Tab: Jadwal Penugasan -->
    <div v-if="activeTab === 'assignments'">
      <div v-if="loadingAssignments" class="py-8 text-center text-sm text-muted-foreground">Memuat jadwal...</div>
      <div v-else>
        <!-- Assignment grid: rows = gates, cols = shifts -->
        <div class="overflow-x-auto rounded-lg border border-border">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border bg-muted/50">
                <th class="px-4 py-3 text-left font-medium text-muted-foreground w-40">Gate</th>
                <th
                  v-for="shift in shifts"
                  :key="shift.id"
                  class="px-4 py-3 text-left font-medium text-muted-foreground min-w-[160px]"
                >
                  <div>{{ shift.name }}</div>
                  <div class="text-xs font-normal text-muted-foreground/70">{{ shift.start_time }} – {{ shift.end_time }}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="gates.length === 0">
                <td :colspan="shifts.length + 1" class="py-8 text-center text-muted-foreground">Tidak ada gate</td>
              </tr>
              <tr
                v-for="gate in gates"
                :key="gate.id"
                class="border-b border-border last:border-0"
              >
                <td class="px-4 py-3">
                  <div class="font-medium text-foreground">{{ gate.name }}</div>
                  <div class="text-xs text-muted-foreground">{{ gate.direction }}</div>
                </td>
                <td v-for="shift in shifts" :key="shift.id" class="px-4 py-3">
                  <template v-if="getAssignment(gate.id, shift.id)">
                    <div
                      :class="[
                        'flex items-start justify-between rounded-lg border px-3 py-2',
                        getAssignment(gate.id, shift.id).is_substitute
                          ? 'border-warning/40 bg-warning/5'
                          : 'border-border bg-surface',
                      ]"
                    >
                      <div>
                        <div class="font-medium text-foreground text-sm">
                          {{ getAssignment(gate.id, shift.id).worker?.full_name || getAssignment(gate.id, shift.id).worker?.username || '—' }}
                        </div>
                        <div v-if="getAssignment(gate.id, shift.id).is_substitute" class="text-xs text-warning mt-0.5">
                          Pengganti {{ getAssignment(gate.id, shift.id).original_worker?.full_name || '' }}
                        </div>
                      </div>
                      <div class="flex gap-1 ml-2 shrink-0">
                        <button
                          class="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-surface-hover transition-colors"
                          title="Edit"
                          @click="openEditAssignment(getAssignment(gate.id, shift.id))"
                        >
                          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </button>
                        <button
                          class="rounded p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                          title="Hapus"
                          @click="deleteAssignment(getAssignment(gate.id, shift.id))"
                        >
                          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
                        </button>
                      </div>
                    </div>
                  </template>
                  <template v-else>
                    <button
                      class="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-3 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors"
                      @click="openCreateAssignment(gate, shift)"
                    >
                      <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                      Tugaskan
                    </button>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Tab: Sesi Petugas -->
    <div v-if="activeTab === 'sessions'">
      <div v-if="loadingSessions" class="py-8 text-center text-sm text-muted-foreground">Memuat sesi...</div>
      <div v-else>
        <div v-if="sessions.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          Tidak ada sesi pada tanggal ini
        </div>
        <div v-else class="overflow-x-auto rounded-lg border border-border">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border bg-muted/50">
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Petugas</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Gate</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Shift</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Masuk</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Keluar</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Durasi</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Keterlambatan</th>
                <th class="px-4 py-3 text-left font-medium text-muted-foreground">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="session in sessions" :key="session.id" class="border-b border-border last:border-0 hover:bg-surface/50">
                <td class="px-4 py-3">
                  <div class="font-medium text-foreground">{{ session.worker?.full_name || session.worker?.username || '—' }}</div>
                  <div v-if="session.is_substitute" class="text-xs text-warning">Pengganti</div>
                </td>
                <td class="px-4 py-3 text-muted-foreground">{{ session.gate?.name || '—' }}</td>
                <td class="px-4 py-3 text-muted-foreground">{{ session.shift?.name || '—' }}</td>
                <td class="px-4 py-3 font-mono text-xs text-foreground">{{ formatTime(session.started_at) }}</td>
                <td class="px-4 py-3 font-mono text-xs text-muted-foreground">
                  {{ session.ended_at ? formatTime(session.ended_at) : '—' }}
                </td>
                <td class="px-4 py-3 text-muted-foreground">{{ sessionDuration(session) }}</td>
                <td class="px-4 py-3">
                  <span :class="['text-xs font-medium', latenessColor(session)]">
                    {{ latenessLabel(session) }}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusBadgeClass(session.status)]">
                    {{ statusLabel(session.status) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Uncovered gaps summary -->
        <div v-if="uncoveredGaps.length > 0" class="mt-4 rounded-lg border border-destructive/20 bg-destructive/5 p-4">
          <p class="mb-2 text-sm font-medium text-destructive">Periode Tidak Terjaga</p>
          <div v-for="gap in uncoveredGaps" :key="gap.key" class="text-xs text-destructive/80">
            {{ gap.gateName }}: {{ gap.from }} – {{ gap.to }} ({{ gap.duration }})
          </div>
        </div>
      </div>
    </div>

    <!-- Assignment modal -->
    <Dialog :open="showAssignmentModal" @update:open="(v) => { if (!v) closeAssignmentModal() }">
      <DialogContent class="max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ editingAssignment ? 'Edit Penugasan' : 'Tambah Penugasan' }}</DialogTitle>
        </DialogHeader>

        <div class="space-y-3">
          <div v-if="!editingAssignment">
            <label class="block text-xs font-medium text-muted-foreground mb-1">Gate</label>
            <div class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground">
              {{ assignmentForm.gateName }}
            </div>
          </div>
          <div v-if="!editingAssignment">
            <label class="block text-xs font-medium text-muted-foreground mb-1">Shift</label>
            <div class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground">
              {{ assignmentForm.shiftName }}
            </div>
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Petugas</label>
            <select
              v-model="assignmentForm.worker_id"
              class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
            >
              <option :value="null">— Pilih Petugas —</option>
              <option v-for="w in workers" :key="w.id" :value="w.id">{{ w.full_name || w.username }}</option>
            </select>
          </div>
          <div>
            <label class="flex items-center gap-2 cursor-pointer select-none text-sm text-muted-foreground">
              <input v-model="assignmentForm.is_substitute" type="checkbox" class="accent-primary" >
              Penugasan pengganti
            </label>
          </div>
          <div v-if="assignmentForm.is_substitute">
            <label class="block text-xs font-medium text-muted-foreground mb-1">Menggantikan</label>
            <select
              v-model="assignmentForm.original_worker_id"
              class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
            >
              <option :value="null">— Pilih Petugas Asli —</option>
              <option v-for="w in workers.filter(w => w.id !== assignmentForm.worker_id)" :key="w.id" :value="w.id">{{ w.full_name || w.username }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Catatan (opsional)</label>
            <input
              v-model="assignmentForm.notes"
              type="text"
              maxlength="255"
              class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
            >
          </div>
        </div>

        <div v-if="assignmentError" class="mt-3 rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
          {{ assignmentError }}
        </div>

        <DialogFooter>
          <Button variant="outline" @click="closeAssignmentModal">Batal</Button>
          <Button :disabled="!assignmentForm.worker_id || savingAssignment" @click="saveAssignment">
            {{ savingAssignment ? 'Menyimpan...' : 'Simpan' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <ConfirmDialog
      v-model="confirmVisible"
      :title="confirmTitle"
      :message="confirmMessage"
      :loading="confirmLoading"
      @confirm="executeConfirm"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '~/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '~/components/ui/dialog'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()

const tabs = [
  { key: 'assignments', label: 'Jadwal Penugasan' },
  { key: 'sessions', label: 'Sesi Petugas' },
]
const activeTab = ref('assignments')

// Date
const selectedDate = ref(new Date().toISOString().slice(0, 10))
const formattedDay = computed(() => {
  return new Date(selectedDate.value + 'T00:00:00').toLocaleDateString('id-ID', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
})

function changeDate(delta) {
  const d = new Date(selectedDate.value + 'T00:00:00')
  d.setDate(d.getDate() + delta)
  selectedDate.value = d.toISOString().slice(0, 10)
  loadData()
}

function goToday() {
  selectedDate.value = new Date().toISOString().slice(0, 10)
  loadData()
}

function switchTab(key) {
  activeTab.value = key
  loadData()
}

// Data
const shifts = ref([])
const gates = ref([])
const workers = ref([])
const assignments = ref([])
const sessions = ref([])
const loadingAssignments = ref(false)
const loadingSessions = ref(false)

function getAssignment(gateId, shiftId) {
  return assignments.value.find(a => a.gate_id === gateId && a.shift_id === shiftId) || null
}

async function loadData() {
  if (activeTab.value === 'assignments') await loadAssignments()
  else await loadSessions()
}

async function loadBaseData() {
  try {
    const [shiftsRes, gatesRes, workersRes] = await Promise.all([
      fetchApi('/api/shifts/active'),
      fetchApi('/api/gates'),
      fetchApi('/api/users/workers'),
    ])
    shifts.value = Array.isArray(shiftsRes) ? shiftsRes : []
    gates.value = Array.isArray(gatesRes) ? gatesRes : (gatesRes?.items ?? [])
    workers.value = Array.isArray(workersRes) ? workersRes : []
  } catch (err) {
    console.error('loadBaseData:', err.message)
  }
}

async function loadAssignments() {
  loadingAssignments.value = true
  try {
    const data = await fetchApi(`/api/shift-assignments?date_filter=${selectedDate.value}`)
    assignments.value = Array.isArray(data) ? data : []
  } catch (err) {
    console.error('loadAssignments:', err.message)
  } finally {
    loadingAssignments.value = false
  }
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const data = await fetchApi(`/api/worker-sessions?date_filter=${selectedDate.value}`)
    sessions.value = Array.isArray(data) ? data : []
  } catch (err) {
    console.error('loadSessions:', err.message)
  } finally {
    loadingSessions.value = false
  }
}

// Assignment modal
const showAssignmentModal = ref(false)
const editingAssignment = ref(null)
const savingAssignment = ref(false)
const assignmentError = ref('')
const assignmentForm = ref({
  gate_id: null, shift_id: null, worker_id: null,
  gateName: '', shiftName: '',
  is_substitute: false, original_worker_id: null, notes: '',
})

function openCreateAssignment(gate, shift) {
  editingAssignment.value = null
  assignmentError.value = ''
  assignmentForm.value = {
    gate_id: gate.id, shift_id: shift.id, worker_id: null,
    gateName: gate.name, shiftName: shift.name,
    is_substitute: false, original_worker_id: null, notes: '',
  }
  showAssignmentModal.value = true
}

function openEditAssignment(assignment) {
  editingAssignment.value = assignment
  assignmentError.value = ''
  assignmentForm.value = {
    gate_id: assignment.gate_id,
    shift_id: assignment.shift_id,
    worker_id: assignment.worker_id,
    gateName: assignment.gate?.name || '',
    shiftName: assignment.shift?.name || '',
    is_substitute: assignment.is_substitute,
    original_worker_id: assignment.original_worker_id,
    notes: assignment.notes || '',
  }
  showAssignmentModal.value = true
}

function closeAssignmentModal() {
  showAssignmentModal.value = false
  editingAssignment.value = null
}

async function saveAssignment() {
  if (!assignmentForm.value.worker_id) return
  savingAssignment.value = true
  assignmentError.value = ''
  const wasEdit = !!editingAssignment.value
  try {
    if (editingAssignment.value) {
      await fetchApi(`/api/shift-assignments/${editingAssignment.value.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          worker_id: assignmentForm.value.worker_id,
          is_substitute: assignmentForm.value.is_substitute,
          original_worker_id: assignmentForm.value.is_substitute ? assignmentForm.value.original_worker_id : null,
          notes: assignmentForm.value.notes || null,
        }),
      })
    } else {
      await fetchApi('/api/shift-assignments', {
        method: 'POST',
        body: JSON.stringify({
          shift_id: assignmentForm.value.shift_id,
          worker_id: assignmentForm.value.worker_id,
          gate_id: assignmentForm.value.gate_id,
          date: selectedDate.value,
          is_substitute: assignmentForm.value.is_substitute,
          original_worker_id: assignmentForm.value.is_substitute ? assignmentForm.value.original_worker_id : null,
          notes: assignmentForm.value.notes || null,
        }),
      })
    }
    closeAssignmentModal()
    await loadAssignments()
    toast.success(wasEdit ? 'Penugasan diperbarui' : 'Penugasan dibuat')
  } catch (err) {
    assignmentError.value = err.message || 'Gagal menyimpan penugasan'
  } finally {
    savingAssignment.value = false
  }
}

// Confirm dialog (replaces native confirm())
const confirmVisible = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmLoading = ref(false)
const confirmAction = ref(null)
function askConfirm(title, message, action) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmAction.value = action
  confirmVisible.value = true
}
async function executeConfirm() {
  if (!confirmAction.value) return
  confirmLoading.value = true
  try {
    await confirmAction.value()
    confirmVisible.value = false
  } finally {
    confirmLoading.value = false
  }
}

function deleteAssignment(assignment) {
  askConfirm('Hapus Penugasan', `Hapus penugasan ${assignment.worker?.full_name || assignment.worker?.username || ''}?`, async () => {
    try {
      await fetchApi(`/api/shift-assignments/${assignment.id}`, { method: 'DELETE' })
      await loadAssignments()
      toast.success('Penugasan dihapus')
    } catch (err) {
      toast.error(err.message || 'Gagal menghapus penugasan')
      throw err
    }
  })
}

// Session helpers
function formatTime(isoStr) {
  if (!isoStr) return '—'
  return new Date(isoStr).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })
}

function sessionDuration(session) {
  if (!session.started_at || !session.ended_at) return '—'
  const mins = Math.round((new Date(session.ended_at) - new Date(session.started_at)) / 60000)
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}j ${m}m` : `${m}m`
}

function latenessMinutes(session) {
  if (!session.started_at || !session.shift?.start_time) return 0
  const shiftStart = new Date(session.date + 'T' + session.shift.start_time)
  const actualStart = new Date(session.started_at)
  return Math.round((actualStart - shiftStart) / 60000)
}

function latenessLabel(session) {
  const mins = latenessMinutes(session)
  if (mins <= 0) return 'Tepat waktu'
  if (mins < 60) return `+${mins}m terlambat`
  return `+${Math.floor(mins / 60)}j ${mins % 60}m terlambat`
}

function latenessColor(session) {
  const mins = latenessMinutes(session)
  if (mins <= 5) return 'text-success'
  if (mins <= 15) return 'text-warning'
  return 'text-destructive'
}

function statusLabel(status) {
  return { ACTIVE: 'Aktif', PENDING_HANDOVER: 'Menunggu Serah', COMPLETED: 'Selesai' }[status] || status
}

function statusBadgeClass(status) {
  return {
    ACTIVE: 'bg-success/10 text-success',
    PENDING_HANDOVER: 'bg-warning/10 text-warning',
    COMPLETED: 'bg-muted text-muted-foreground',
  }[status] || 'bg-muted text-muted-foreground'
}

// Compute uncovered gaps per gate
const uncoveredGaps = computed(() => {
  const gaps = []
  const byGate = {}
  for (const s of sessions.value) {
    if (!byGate[s.gate_id]) byGate[s.gate_id] = []
    byGate[s.gate_id].push(s)
  }
  for (const [gateId, gateSessions] of Object.entries(byGate)) {
    const sorted = [...gateSessions].sort((a, b) => new Date(a.started_at) - new Date(b.started_at))
    for (let i = 0; i < sorted.length - 1; i++) {
      const curr = sorted[i]
      const next = sorted[i + 1]
      if (!curr.ended_at) continue
      const endT = new Date(curr.ended_at)
      const startT = new Date(next.started_at)
      const diffMins = Math.round((startT - endT) / 60000)
      if (diffMins > 2) {
        const gate = gates.value.find(g => g.id === parseInt(gateId))
        gaps.push({
          key: `${gateId}-${i}`,
          gateName: gate?.name || `Gate ${gateId}`,
          from: formatTime(curr.ended_at),
          to: formatTime(next.started_at),
          duration: diffMins < 60 ? `${diffMins}m` : `${Math.floor(diffMins/60)}j ${diffMins%60}m`,
        })
      }
    }
  }
  return gaps
})

onMounted(async () => {
  await loadBaseData()
  await loadData()
})
</script>
