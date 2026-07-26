<template>
  <Dialog :open="modelValue" @update:open="$emit('update:modelValue', $event)">
    <DialogContent class="max-w-lg">
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
      </DialogHeader>

      <form class="space-y-6 max-h-[60vh] overflow-y-auto pr-1" @submit.prevent="handleSubmit">
        <fieldset
          v-for="(group, gIdx) in groups"
          :key="group.title || gIdx"
          class="space-y-4"
          :class="group.title ? 'border-2 border-foreground p-4 shadow-brutal-sm' : ''"
        >
          <legend
            v-if="group.title"
            class="border-2 border-foreground bg-primary px-2 py-0.5 text-xs font-black uppercase tracking-wider text-foreground shadow-brutal-sm"
          >
            {{ group.title }}
          </legend>

          <div v-for="field in group.items" :key="field.prop" class="space-y-2">
            <label class="text-sm font-bold uppercase tracking-wide text-foreground">
              {{ field.label }}
              <span v-if="field.required" class="text-destructive">*</span>
            </label>

            <!-- Text / Number / Password -->
            <Input
              v-if="field.type === 'text' || field.type === 'number' || field.type === 'password'"
              v-model="formData[field.prop]"
              :type="field.type === 'password' ? 'password' : (field.inputType || 'text')"
              :placeholder="field.placeholder || ''"
              :disabled="field.disabled"
            />

            <!-- Textarea -->
            <textarea
              v-else-if="field.type === 'textarea'"
              v-model="formData[field.prop]"
              :rows="field.rows || 3"
              :placeholder="field.placeholder || ''"
              :disabled="field.disabled"
              class="w-full border-2 border-foreground bg-background px-3 py-2 text-sm font-medium text-foreground placeholder:text-muted-foreground focus:outline-none focus:shadow-brutal-sm focus:translate-x-[2px] focus:translate-y-[2px] transition-all duration-100"
            />

            <!-- Select -->
            <select
              v-else-if="field.type === 'select'"
              v-model="formData[field.prop]"
              :disabled="field.disabled"
              class="w-full border-2 border-foreground bg-background px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:shadow-brutal-sm focus:translate-x-[2px] focus:translate-y-[2px] transition-all duration-100"
            >
              <option value="" disabled>{{ field.placeholder || 'Pilih...' }}</option>
              <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>

            <!-- Boolean / Switch -->
            <div v-else-if="field.type === 'boolean'" class="flex items-center gap-3">
              <button
                type="button"
                :class="[
                  'relative inline-flex h-7 w-12 shrink-0 cursor-pointer border-2 border-foreground transition-all duration-100',
                  formData[field.prop] ? 'bg-primary shadow-brutal-sm' : 'bg-muted',
                ]"
                @click="formData[field.prop] = !formData[field.prop]"
              >
                <span
                  :class="[
                    'pointer-events-none inline-block h-5 w-5 border-2 border-foreground bg-background transition-transform',
                    formData[field.prop] ? 'translate-x-5' : 'translate-x-0',
                  ]"
                />
              </button>
              <span class="text-sm font-bold uppercase text-foreground">
                {{ formData[field.prop] ? 'Ya' : 'Tidak' }}
              </span>
            </div>

            <!-- IP scan (TCP host with LAN discovery button) -->
            <div v-else-if="field.type === 'ip-scan'" class="space-y-1">
              <div class="flex gap-2">
                <select
                  v-if="ipScanResults[field.prop]?.length"
                  class="w-40 rounded-md border border-border bg-background px-2 py-2 text-xs font-mono"
                  @change="(e) => { formData[field.prop] = e.target.value }"
                >
                  <option value="">— hasil scan —</option>
                  <option v-for="c in ipScanResults[field.prop]" :key="c.host" :value="c.host">
                    {{ c.host }}{{ c.confirmed ? ' ✓' : '' }} · {{ Math.round(c.latency_ms) }}ms
                  </option>
                </select>
                <Input
                  v-model="formData[field.prop]"
                  :placeholder="field.placeholder || ''"
                  :disabled="field.disabled"
                  class="flex-1"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  :disabled="ipScanning[field.prop]"
                  @click="scanIpField(field)"
                >
                  {{ ipScanning[field.prop] ? 'Memindai…' : 'Scan LAN' }}
                </Button>
              </div>
              <p v-if="ipScanError[field.prop]" class="text-xs text-destructive">
                {{ ipScanError[field.prop] }}
              </p>
            </div>

            <!-- Time -->
            <Input
              v-else-if="field.type === 'time'"
              v-model="formData[field.prop]"
              type="time"
              :disabled="field.disabled"
            />

            <!-- Date -->
            <Input
              v-else-if="field.type === 'date'"
              v-model="formData[field.prop]"
              type="date"
              :disabled="field.disabled"
            />

            <!-- Validation error -->
            <p v-if="errors[field.prop]" class="text-xs text-destructive">
              {{ errors[field.prop] }}
            </p>
          </div>
        </fieldset>
      </form>

      <DialogFooter>
        <Button variant="outline" @click="handleClose">Batal</Button>
        <Button :disabled="submitting" @click="handleSubmit">
          {{ submitting ? 'Menyimpan...' : 'Simpan' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, nextTick, reactive, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: 'Form' },
  /**
   * Either a flat field array (legacy):
   *   [{prop, label, type, ...}, ...]
   *
   * or a grouped form for entities with many fields:
   *   [
   *     { group: 'Identitas', items: [{prop, label, ...}, ...] },
   *     { group: 'Kontak',    items: [...] },
   *   ]
   */
  fields: { type: Array, required: true },
  initialData: { type: Object, default: () => ({}) },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'submit'])

// Normalise fields into the grouped form so the template has one shape.
const groups = computed(() => {
  if (!props.fields.length) return []
  const first = props.fields[0]
  const isGrouped = first && typeof first === 'object' && 'group' in first && Array.isArray(first.items)
  if (isGrouped) {
    return props.fields.map((g) => ({ title: g.group, items: g.items }))
  }
  return [{ title: '', items: props.fields }]
})

const flatFields = computed(() => groups.value.flatMap((g) => g.items))

const formData = reactive({})
const errors = reactive({})
const ipScanning = reactive({})
const ipScanResults = reactive({})
const ipScanError = reactive({})

const { fetchApi } = useApi()

async function scanIpField(field) {
  ipScanning[field.prop] = true
  ipScanError[field.prop] = ''
  ipScanResults[field.prop] = []
  try {
    const octets = (formData[field.prop] || '').split('.')
    const prefix = octets.length === 4 ? octets.slice(0, 3).join('.') : '192.168.1'
    const port = (field.portProp && Number(formData[field.portProp])) || 5000
    const res = await fetchApi('/api/setup/discover-gates', {
      method: 'POST',
      body: JSON.stringify({ subnet: `${prefix}.0/24`, port }),
    })
    ipScanResults[field.prop] = res.candidates || []
    if (!ipScanResults[field.prop].length) {
      ipScanError[field.prop] = `Tidak ada controller ditemukan di ${prefix}.0/24 — cek kabel LAN atau isi IP manual.`
    }
  } catch (err) {
    ipScanError[field.prop] = `Gagal scan: ${err.message}`
  } finally {
    ipScanning[field.prop] = false
  }
}

watch(
  () => props.modelValue,
  async (val) => {
    if (val) {
      await nextTick()
      Object.keys(errors).forEach((k) => delete errors[k])
      for (const field of flatFields.value) {
        formData[field.prop] =
          props.initialData[field.prop] ?? (field.type === 'boolean' ? false : '')
      }
      if (props.initialData.id != null) {
        formData.id = props.initialData.id
      } else {
        delete formData.id
      }
    }
  },
  { immediate: true },
)

function handleClose() {
  emit('update:modelValue', false)
}

function validate() {
  let valid = true
  Object.keys(errors).forEach((k) => delete errors[k])
  for (const field of flatFields.value) {
    if (field.required) {
      const val = formData[field.prop]
      if (val === undefined || val === null || val === '') {
        errors[field.prop] = `${field.label} wajib diisi`
        valid = false
      }
    }
  }
  return valid
}

function handleSubmit() {
  if (!validate()) return
  emit('submit', { ...formData })
}
</script>
