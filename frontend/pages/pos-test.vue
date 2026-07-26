<template>
  <div class="p-8 space-y-4">
    <h1 class="text-2xl font-bold">POS Test Page</h1>
    <p class="text-muted-foreground">Use these buttons to test different POS states</p>

    <div class="space-y-2">
      <button
        class="px-4 py-2 bg-primary text-white rounded"
        @click="simulateActiveTransaction"
      >
        Simulate Active Transaction (Motor)
      </button>

      <button
        class="px-4 py-2 bg-primary text-white rounded"
        @click="simulateExpensiveTransaction"
      >
        Simulate Expensive Transaction (Mobil)
      </button>

      <button
        class="px-4 py-2 bg-success text-white rounded"
        @click="simulateGateOpen"
      >
        Simulate Gate Open State
      </button>

      <button
        class="px-4 py-2 bg-destructive text-white rounded"
        @click="simulateTimeout"
      >
        Simulate Timeout Error
      </button>

      <button
        class="px-4 py-2 bg-muted text-foreground rounded"
        @click="clearState"
      >
        Clear / Back to IDLE
      </button>
    </div>

    <div class="pt-4">
      <NuxtLink to="/pos" class="text-primary underline">
        Go to POS Page →
      </NuxtLink>
    </div>
  </div>
</template>

<script setup>
// Dev-only fixture page — redirect away in production builds.
definePageMeta({
  middleware: [
    function () {
      if (import.meta.env.PROD) {
        return navigateTo('/')
      }
    },
  ],
})

const gateStore = useGateStore()

function simulateActiveTransaction() {
  gateStore.$patch({
    currentTransaction: {
      id: 999,
      barcode: 'TEST001',
      plate_number: 'B 1234 CD',
      vehicle_type_id: 1,
      vehicle_type: 'Motor',
      entry_time: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
      tariff: 5000,
      fee: 5000,
      entry_snapshot_id: null,
      entry_gate_name: 'Gate Masuk Utama'
    },
    paymentState: 'WAITING_PAYMENT',
    durationSeconds: 3600,
    waitingSeconds: 45,
    awaitingGateOpen: false
  })

  navigateTo('/pos')
}

function simulateExpensiveTransaction() {
  gateStore.$patch({
    currentTransaction: {
      id: 888,
      barcode: 'TEST002',
      plate_number: 'D 5678 EF',
      vehicle_type_id: 2,
      vehicle_type: 'Mobil',
      entry_time: new Date(Date.now() - 7200000).toISOString(), // 2 hours ago
      tariff: 15000,
      fee: 15000,
      entry_snapshot_id: null,
      entry_gate_name: 'Gate Masuk Utama'
    },
    paymentState: 'WAITING_PAYMENT',
    durationSeconds: 7200,
    waitingSeconds: 30,
    awaitingGateOpen: false
  })

  navigateTo('/pos')
}

function simulateGateOpen() {
  gateStore.$patch({
    currentTransaction: {
      id: 777,
      barcode: 'TEST003',
      plate_number: 'B 9999 XY',
      vehicle_type_id: 1,
      vehicle_type: 'Motor',
      entry_time: new Date(Date.now() - 1800000).toISOString(),
      tariff: 5000,
      fee: 5000,
      entry_snapshot_id: null,
      entry_gate_name: 'Gate Masuk Utama'
    },
    paymentState: 'PAID',
    awaitingGateOpen: true,
    changeAmount: 5000, // Paid 10k for 5k
    durationSeconds: 1800
  })

  navigateTo('/pos')
}

function simulateTimeout() {
  gateStore.$patch({
    currentTransaction: {
      id: 666,
      barcode: 'TEST004',
      plate_number: 'B 4321 ZZ',
      vehicle_type_id: 1,
      vehicle_type: 'Motor',
      entry_time: new Date(Date.now() - 5400000).toISOString(),
      tariff: 5000,
      fee: 5000,
      entry_snapshot_id: null,
      entry_gate_name: 'Gate Masuk Utama'
    },
    paymentState: 'TIMEOUT_ALERT',
    durationSeconds: 5400,
    waitingSeconds: 125,
    awaitingGateOpen: false
  })

  navigateTo('/pos')
}

function clearState() {
  gateStore.clearTransaction()
  navigateTo('/pos')
}
</script>
