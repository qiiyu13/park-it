<template>
  <div class="space-y-4">
    <!-- Toolbar -->
    <div class="flex items-center justify-between">
      <div class="relative w-72">
        <svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
        </svg>
        <Input
          v-model="searchQuery"
          placeholder="Cari..."
          class="pl-9"
          @input="handleSearch"
        />
      </div>
      <Button v-if="showAdd" @click="$emit('add')">
        <svg class="mr-2 h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Tambah
      </Button>
    </div>

    <!-- Table -->
    <div class="overflow-x-auto rounded-lg border border-border bg-surface shadow-brutal-sm">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border bg-muted/60 text-foreground">
            <th
              v-for="col in columns"
              :key="col.prop"
              class="px-4 py-3 text-left text-[11px] font-semibold tracking-wider text-muted-foreground"
              :style="col.width ? { width: col.width + 'px' } : {}"
            >
              <button
                v-if="col.sortable"
                class="flex items-center gap-1 hover:text-primary"
                @click="toggleSort(col.prop)"
              >
                {{ col.label }}
                <span v-if="sortProp === col.prop" class="text-xs">
                  {{ sortOrder === 'asc' ? '↑' : '↓' }}
                </span>
              </button>
              <span v-else>{{ col.label }}</span>
            </th>
            <th v-if="showActions" class="w-24 px-4 py-3 text-left font-bold  tracking-wider">Aksi</th>
          </tr>
        </thead>
        <tbody>
          <!-- Loading state -->
          <tr v-if="loading">
            <td :colspan="columns.length + (showActions ? 1 : 0)" class="px-4 py-8 text-center text-muted-foreground">
              <div class="flex items-center justify-center gap-2">
                <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 12a9 9 0 11-6.219-8.56" />
                </svg>
                Memuat data...
              </div>
            </td>
          </tr>

          <!-- Empty state -->
          <tr v-else-if="displayedData.length === 0">
            <td :colspan="columns.length + (showActions ? 1 : 0)" class="px-4 py-8 text-center text-muted-foreground">
              Tidak ada data
            </td>
          </tr>

          <!-- Data rows -->
          <tr
            v-for="(row, idx) in displayedData"
            :key="idx"
            class="border-b border-border last:border-0 hover:bg-primary/20 transition-colors"
          >
            <td
              v-for="col in columns"
              :key="col.prop"
              class="px-4 py-3 font-medium text-foreground"
            >
              <!-- Boolean type -->
              <span
                v-if="col.type === 'boolean'"
                :class="[
                  'inline-flex border border-border px-2 py-0.5 text-xs font-bold  shadow-brutal-sm',
                  row[col.prop] ? 'bg-success text-white' : 'bg-muted text-muted-foreground',
                ]"
              >
                {{ row[col.prop] ? 'Ya' : 'Tidak' }}
              </span>

              <!-- Enum type -->
              <span
                v-else-if="col.type === 'enum'"
                class="inline-flex border border-border bg-primary px-2 py-0.5 text-xs font-bold  shadow-brutal-sm"
              >
                {{ row[col.prop] }}
              </span>

              <!-- Custom formatter -->
              <span v-else-if="col.formatter">
                {{ col.formatter(row[col.prop], row) }}
              </span>

              <!-- Default -->
              <span v-else>{{ row[col.prop] ?? '-' }}</span>
            </td>

            <!-- Actions -->
            <td v-if="showActions" class="px-4 py-3">
              <div class="flex items-center gap-1">
                <slot name="row-actions" :row="row" />
                <button
                  v-if="showEdit"
                  class="border border-transparent p-1.5 text-muted-foreground transition-all hover:border-border hover:bg-primary hover:text-foreground hover:shadow-brutal-sm"
                  title="Edit"
                  @click="$emit('edit', row)"
                >
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
                <button
                  v-if="showDelete"
                  class="border border-transparent p-1.5 text-muted-foreground transition-all hover:border-border hover:bg-destructive hover:text-white hover:shadow-brutal-sm"
                  title="Hapus"
                  @click="$emit('delete', row)"
                >
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div v-if="showPagination && total > 0" class="flex items-center justify-between">
      <div class="text-sm text-muted-foreground">
        Menampilkan {{ startItem }}-{{ endItem }} dari {{ total }}
      </div>
      <div class="flex items-center gap-1">
        <select
          v-model="currentPageSize"
          class="border border-border bg-surface px-2 py-1 text-sm font-medium text-foreground shadow-brutal-sm"
          @change="handleSizeChange"
        >
          <option v-for="s in pageSizes" :key="s" :value="s">{{ s }}</option>
        </select>
        <Button variant="outline" size="sm" :disabled="currentPage <= 1" @click="handlePageChange(currentPage - 1)">
          &laquo;
        </Button>
        <template v-for="page in visiblePages" :key="page">
          <Button
            v-if="page !== '...'"
            :variant="page === currentPage ? 'default' : 'outline'"
            size="sm"
            @click="handlePageChange(page)"
          >
            {{ page }}
          </Button>
          <span v-else class="px-1 text-muted-foreground">...</span>
        </template>
        <Button variant="outline" size="sm" :disabled="currentPage >= totalPages" @click="handlePageChange(currentPage + 1)">
          &raquo;
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'

const props = defineProps({
  data: { type: Array, default: () => [] },
  columns: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  showAdd: { type: Boolean, default: true },
  showEdit: { type: Boolean, default: true },
  showDelete: { type: Boolean, default: true },
  showActions: { type: Boolean, default: true },
  showPagination: { type: Boolean, default: true },
  pageSize: { type: Number, default: 10 },
  serverPagination: { type: Boolean, default: false },
  totalItems: { type: Number, default: 0 },
})

const emit = defineEmits(['add', 'edit', 'delete', 'page-change', 'size-change', 'search'])

const searchQuery = ref('')
const currentPage = ref(1)
const currentPageSize = ref(props.pageSize)
const sortProp = ref('')
const sortOrder = ref('')
const pageSizes = [10, 20, 50, 100]

let searchTimeout = null
function handleSearch() {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    currentPage.value = 1
    emit('search', searchQuery.value)
  }, 300)
}

function handlePageChange(page) {
  currentPage.value = page
  if (props.serverPagination) {
    emit('page-change', page, currentPageSize.value)
  }
}

function handleSizeChange() {
  currentPage.value = 1
  if (props.serverPagination) {
    emit('size-change', 1, currentPageSize.value)
  }
}

function toggleSort(prop) {
  if (sortProp.value === prop) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : ''
    if (!sortOrder.value) sortProp.value = ''
  } else {
    sortProp.value = prop
    sortOrder.value = 'asc'
  }
}

const filteredData = computed(() => {
  let result = [...props.data]
  if (searchQuery.value && !props.loading) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter((row) =>
      props.columns.some((col) => String(row[col.prop] || '').toLowerCase().includes(q))
    )
  }
  if (sortProp.value && sortOrder.value) {
    const dir = sortOrder.value === 'asc' ? 1 : -1
    result.sort((a, b) => {
      const av = a[sortProp.value], bv = b[sortProp.value]
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }
  return result
})

const total = computed(() => props.serverPagination ? props.totalItems : filteredData.value.length)
const totalPages = computed(() => Math.ceil(total.value / currentPageSize.value))

const displayedData = computed(() => {
  if (props.serverPagination) return props.data
  const start = (currentPage.value - 1) * currentPageSize.value
  return filteredData.value.slice(start, start + currentPageSize.value)
})

const startItem = computed(() => (currentPage.value - 1) * currentPageSize.value + 1)
const endItem = computed(() => Math.min(currentPage.value * currentPageSize.value, total.value))

const visiblePages = computed(() => {
  const pages = []
  const tp = totalPages.value
  if (tp <= 7) {
    for (let i = 1; i <= tp; i++) pages.push(i)
  } else {
    pages.push(1)
    if (currentPage.value > 3) pages.push('...')
    for (let i = Math.max(2, currentPage.value - 1); i <= Math.min(tp - 1, currentPage.value + 1); i++) {
      pages.push(i)
    }
    if (currentPage.value < tp - 2) pages.push('...')
    pages.push(tp)
  }
  return pages
})
</script>
