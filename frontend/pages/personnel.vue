<template>
  <div>
    <PageHeader title="Personil" subtitle="Manajemen akun pengguna dan PIN shift.">
      <template #action>
        <Button size="sm" @click="openCreate">+ Tambah Pengguna</Button>
      </template>
    </PageHeader>

    <!-- User table -->
    <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">Memuat...</div>
    <div v-else class="overflow-x-auto rounded-lg border border-border">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border bg-muted/50">
            <th class="px-4 py-3 text-left font-medium text-muted-foreground">Nama</th>
            <th class="px-4 py-3 text-left font-medium text-muted-foreground">Username</th>
            <th class="px-4 py-3 text-left font-medium text-muted-foreground">Role</th>
            <th class="px-4 py-3 text-left font-medium text-muted-foreground">Status</th>
            <th class="px-4 py-3 text-left font-medium text-muted-foreground">PIN</th>
            <th class="px-4 py-3 text-left font-medium text-muted-foreground w-32">Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="users.length === 0">
            <td colspan="6" class="py-8 text-center text-muted-foreground">Tidak ada pengguna</td>
          </tr>
          <tr
            v-for="user in users"
            :key="user.id"
            class="border-b border-border last:border-0 hover:bg-surface/50"
          >
            <td class="px-4 py-3">
              <div class="font-medium text-foreground">{{ user.full_name || '—' }}</div>
              <div v-if="user.email" class="text-xs text-muted-foreground">{{ user.email }}</div>
            </td>
            <td class="px-4 py-3 font-mono text-xs text-foreground">{{ user.username }}</td>
            <td class="px-4 py-3">
              <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', roleBadgeClass(user.role)]">
                {{ user.role }}
              </span>
            </td>
            <td class="px-4 py-3">
              <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', user.is_active ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground']">
                {{ user.is_active ? 'Aktif' : 'Nonaktif' }}
              </span>
            </td>
            <td class="px-4 py-3">
              <div v-if="pinEditingId === user.id" class="flex items-center gap-2">
                <input
                  v-model="pinValue"
                  type="password"
                  inputmode="numeric"
                  maxlength="4"
                  placeholder="••••"
                  class="w-20 rounded border border-border bg-surface px-2 py-1 text-center font-mono text-sm text-foreground focus:border-primary focus:outline-none"
                  @keydown.enter="savePin(user.id)"
                  @keydown.escape="cancelPinEdit"
                >
                <button
                  :disabled="pinValue.length < 4 || savingPin"
                  class="rounded bg-primary px-2 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-40"
                  @click="savePin(user.id)"
                >
                  {{ savingPin ? '...' : 'Simpan' }}
                </button>
                <button class="text-xs text-muted-foreground hover:text-foreground" @click="cancelPinEdit">Batal</button>
              </div>
              <div v-else class="flex items-center gap-2">
                <span :class="['text-xs', user.worker_pin ? 'text-success' : 'text-muted-foreground/50']">
                  {{ user.worker_pin ? '●●●●' : 'Belum diset' }}
                </span>
                <button
                  class="text-xs text-primary hover:underline"
                  @click="startPinEdit(user)"
                >
                  {{ user.worker_pin ? 'Ubah' : 'Set PIN' }}
                </button>
                <button
                  v-if="user.worker_pin"
                  class="text-xs text-destructive hover:underline"
                  @click="removePin(user)"
                >
                  Hapus
                </button>
              </div>
            </td>
            <td class="px-4 py-3">
              <div class="flex items-center gap-2">
                <button
                  class="rounded p-1.5 text-muted-foreground hover:text-foreground hover:bg-surface-hover transition-colors"
                  title="Edit"
                  @click="openEdit(user)"
                >
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button
                  class="rounded p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                  title="Hapus"
                  @click="deleteUser(user)"
                >
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create/Edit user modal -->
    <Dialog :open="showModal" @update:open="(v) => { if (!v) closeModal() }">
      <DialogContent class="max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ editingUser ? 'Edit Pengguna' : 'Tambah Pengguna' }}</DialogTitle>
        </DialogHeader>

        <div class="space-y-3">
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Username</label>
            <input v-model="form.username" type="text" class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none" >
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Nama Lengkap</label>
            <input v-model="form.full_name" type="text" class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none" >
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Role</label>
            <select v-model="form.role" class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none">
              <option value="operator">Operator</option>
              <option value="supervisor">Supervisor</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">
              {{ editingUser ? 'Password Baru (kosongkan jika tidak diubah)' : 'Password' }}
            </label>
            <input v-model="form.password" type="password" class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none" >
          </div>
          <div>
            <label class="block text-xs font-medium text-muted-foreground mb-1">Telepon</label>
            <input v-model="form.phone" type="text" class="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none" >
          </div>
          <div>
            <label class="flex items-center gap-2 cursor-pointer select-none text-sm text-muted-foreground">
              <input v-model="form.is_active" type="checkbox" class="accent-primary" >
              Akun aktif
            </label>
          </div>
        </div>

        <div v-if="modalError" class="mt-3 rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
          {{ modalError }}
        </div>

        <DialogFooter>
          <Button variant="outline" @click="closeModal">Batal</Button>
          <Button :disabled="!form.username || savingUser" @click="saveUser">
            {{ savingUser ? 'Menyimpan...' : 'Simpan' }}
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
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '~/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '~/components/ui/dialog'

definePageMeta({ middleware: 'auth' })

const { fetchApi } = useApi()

const users = ref([])
const loading = ref(false)

// User modal
const showModal = ref(false)
const editingUser = ref(null)
const savingUser = ref(false)
const modalError = ref('')
const form = ref({ username: '', full_name: '', role: 'operator', password: '', phone: '', is_active: true })

// PIN inline edit
const pinEditingId = ref(null)
const pinValue = ref('')
const savingPin = ref(false)

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

async function loadUsers() {
  loading.value = true
  try {
    const data = await fetchApi('/api/users')
    users.value = Array.isArray(data) ? data : (data?.items ?? [])
  } catch (err) {
    console.error('loadUsers:', err.message)
  } finally {
    loading.value = false
  }
}

function roleBadgeClass(role) {
  return {
    admin: 'bg-destructive/10 text-destructive',
    supervisor: 'bg-warning/10 text-warning',
    operator: 'bg-primary/10 text-primary',
  }[role] || 'bg-muted text-muted-foreground'
}

function openCreate() {
  editingUser.value = null
  modalError.value = ''
  form.value = { username: '', full_name: '', role: 'operator', password: '', phone: '', is_active: true }
  showModal.value = true
}

function openEdit(user) {
  editingUser.value = user
  modalError.value = ''
  form.value = { username: user.username, full_name: user.full_name || '', role: user.role, password: '', phone: user.phone || '', is_active: user.is_active }
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  editingUser.value = null
}

async function saveUser() {
  if (!form.value.username) return
  savingUser.value = true
  modalError.value = ''
  try {
    const wasEdit = !!editingUser.value
    const payload = { ...form.value }
    if (!payload.password) delete payload.password
    if (wasEdit) {
      await fetchApi(`/api/users/${editingUser.value.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
    } else {
      await fetchApi('/api/users', { method: 'POST', body: JSON.stringify(payload) })
    }
    closeModal()
    await loadUsers()
    toast.success(wasEdit ? 'Pengguna diperbarui' : 'Pengguna dibuat')
  } catch (err) {
    modalError.value = err.message || 'Gagal menyimpan'
  } finally {
    savingUser.value = false
  }
}

function deleteUser(user) {
  askConfirm('Hapus Pengguna', `Hapus pengguna ${user.username}?`, async () => {
    try {
      await fetchApi(`/api/users/${user.id}`, { method: 'DELETE' })
      await loadUsers()
      toast.success(`Pengguna ${user.username} dihapus`)
    } catch (err) {
      toast.error(err.message || 'Gagal menghapus pengguna')
      throw err
    }
  })
}

// PIN management
function startPinEdit(user) {
  pinEditingId.value = user.id
  pinValue.value = ''
}

function cancelPinEdit() {
  pinEditingId.value = null
  pinValue.value = ''
}

async function savePin(userId) {
  if (pinValue.value.length < 4) return
  savingPin.value = true
  try {
    await fetchApi(`/api/users/${userId}/set-pin`, {
      method: 'POST',
      body: JSON.stringify({ pin: pinValue.value }),
    })
    cancelPinEdit()
    await loadUsers()
    toast.success('PIN tersimpan')
  } catch (err) {
    toast.error(err.message || 'Gagal menyimpan PIN')
  } finally {
    savingPin.value = false
  }
}

function removePin(user) {
  askConfirm('Hapus PIN', `Hapus PIN ${user.full_name || user.username}?`, async () => {
    try {
      await fetchApi(`/api/users/${user.id}/pin`, { method: 'DELETE' })
      await loadUsers()
      toast.success('PIN dihapus')
    } catch (err) {
      toast.error(err.message || 'Gagal menghapus PIN')
      throw err
    }
  })
}

onMounted(loadUsers)
</script>
