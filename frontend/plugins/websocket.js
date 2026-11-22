/**
 * WebSocket Plugin
 *
 * Provides a global $ws object with auto-reconnect.
 * Each gate gets its own WebSocket connection authenticated via httpOnly cookie.
 */

export default defineNuxtPlugin((nuxtApp) => {
  const config = useRuntimeConfig()
  // Empty runtime config = same-origin: derive wss://<current host> so the
  // operator opens http(s)://<server-ip>/ and nothing points at localhost.
  const sameOrigin =
    import.meta.client
      ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`
      : ''
  const wsBaseUrl = config.public.wsBaseUrl || sameOrigin

  class ParkingWebSocket {
    constructor() {
      this.connections = new Map() // gate_id -> WebSocket
      this.reconnectTimers = new Map() // gate_id -> timeout id
      this.listeners = new Map() // gate_id -> Set(callbacks)
      this.reconnectDelays = new Map() // gate_id -> current delay ms
    }

    /**
     * Connect to a gate's WebSocket endpoint.
     */
    connect(gateId) {
      if (this.connections.has(gateId)) {
        const existing = this.connections.get(gateId)
        if (existing.readyState === WebSocket.OPEN) {
          return existing
        }
        // Close stale connection before reconnecting
        existing.close()
      }

      const url = `${wsBaseUrl}/ws/${encodeURIComponent(gateId)}`
      const ws = new WebSocket(url)

      ws.onopen = () => {
        this.reconnectDelays.set(gateId, 1000) // Reset delay
        this._emit(gateId, { type: 'ws_open', gate_id: gateId })
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          // Normalize Pydantic event_type → type so handlers can use event.type consistently
          this._emit(gateId, { type: data.event_type, ...data, gate_id: gateId })
        } catch {
          this._emit(gateId, { type: 'ws_raw', data: event.data, gate_id: gateId })
        }
      }

      ws.onclose = (event) => {
        this.connections.delete(gateId)
        this._emit(gateId, { type: 'ws_close', code: event.code, gate_id: gateId })
        // Auto-reconnect unless cleanly closed by us
        if (event.code !== 1000 && event.code !== 1005) {
          this._scheduleReconnect(gateId)
        }
      }

      ws.onerror = () => {
        this._emit(gateId, { type: 'ws_error', gate_id: gateId })
      }

      this.connections.set(gateId, ws)
      return ws
    }

    /**
     * Disconnect from a gate.
     */
    disconnect(gateId) {
      // Cancel pending reconnect
      if (this.reconnectTimers.has(gateId)) {
        clearTimeout(this.reconnectTimers.get(gateId))
        this.reconnectTimers.delete(gateId)
      }

      const ws = this.connections.get(gateId)
      if (ws) {
        ws.close(1000, 'Client disconnect')
        this.connections.delete(gateId)
      }

      this.listeners.delete(gateId)
      this.reconnectDelays.delete(gateId)
    }

    /**
     * Disconnect all gates.
     */
    disconnectAll() {
      for (const gateId of Array.from(this.connections.keys())) {
        this.disconnect(gateId)
      }
    }

    /**
     * Subscribe to events for a gate.
     */
    on(gateId, callback) {
      if (!this.listeners.has(gateId)) {
        this.listeners.set(gateId, new Set())
      }
      this.listeners.get(gateId).add(callback)

      // Auto-connect if not already connected
      if (!this.connections.has(gateId)) {
        this.connect(gateId)
      }

      // Return unsubscribe function
      return () => {
        const set = this.listeners.get(gateId)
        if (set) {
          set.delete(callback)
        }
      }
    }

    /**
     * Send a message to a gate's WebSocket.
     */
    send(gateId, data) {
      const ws = this.connections.get(gateId)
      if (ws && ws.readyState === WebSocket.OPEN) {
        const payload = typeof data === 'string' ? data : JSON.stringify(data)
        ws.send(payload)
        return true
      }
      return false
    }

    /**
     * Check if a gate is connected.
     */
    isConnected(gateId) {
      const ws = this.connections.get(gateId)
      return ws ? ws.readyState === WebSocket.OPEN : false
    }

    // Internal: emit event to all listeners for a gate
    _emit(gateId, event) {
      const set = this.listeners.get(gateId)
      if (set) {
        for (const cb of set) {
          try {
            cb(event)
          } catch (err) {
            console.error('WebSocket listener error:', err)
          }
        }
      }
    }

    // Internal: schedule reconnect with exponential backoff
    _scheduleReconnect(gateId) {
      if (this.reconnectTimers.has(gateId)) return

      const currentDelay = this.reconnectDelays.get(gateId) || 1000
      const nextDelay = Math.min(currentDelay * 2, 30000) // Max 30s
      this.reconnectDelays.set(gateId, nextDelay)

      const timer = setTimeout(() => {
        this.reconnectTimers.delete(gateId)
        if (this.listeners.has(gateId) && this.listeners.get(gateId).size > 0) {
          this.connect(gateId)
        }
      }, currentDelay)

      this.reconnectTimers.set(gateId, timer)
    }
  }

  const ws = new ParkingWebSocket()

  // Clean up on app unmount (SSR safety)
  nuxtApp.hook('app:mounted', () => {
    // Client-side only
  })

  return {
    provide: {
      ws,
    },
  }
})
