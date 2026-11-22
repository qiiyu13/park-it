/**
 * useKeyboard — centralized keyboard shortcut management.
 * Registers/unregisters on mount/unmount.
 */

import { onMounted, onUnmounted } from 'vue'

export function useKeyboard(handlers, options = {}) {
  const { isBlocked } = options

  function onKeydown(e) {
    // Don't trigger shortcuts when typing in inputs
    const tag = e.target.tagName
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable

    // When a modal owns the screen (cash/RFID/PIN/handover), suppress every
    // shortcut except Escape. F1-F4 are otherwise whitelisted over the always
    // -focused barcode field, but they must not fire into a modal's PIN/amount
    // input where they would hijack the operator's keystrokes.
    const blocked = typeof isBlocked === 'function' && isBlocked()

    for (const handler of handlers) {
      const matches = handler.keys.every((key) => {
        if (key === 'ctrl') return e.ctrlKey || e.metaKey
        if (key === 'shift') return e.shiftKey
        if (key === 'alt') return e.altKey
        return e.key === key
      })

      if (matches) {
        const isEscape = handler.keys.length === 1 && handler.keys[0] === 'Escape'
        if (blocked && !isEscape) {
          continue
        }
        // Skip single-key shortcuts when typing in inputs
        if (isInput && handler.keys.length === 1 && !['Escape', 'F1', 'F2', 'F3', 'F4', 'F11', 'F12'].includes(handler.keys[0])) {
          continue
        }
        e.preventDefault()
        handler.action()
        return
      }
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', onKeydown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', onKeydown)
  })
}
