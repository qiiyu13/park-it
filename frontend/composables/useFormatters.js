/**
 * useFormatters — shared formatting utilities.
 * Eliminates duplicate formatCurrency/duration across components.
 */

export function useFormatters() {
  function formatCurrency(amount) {
    if (amount == null || isNaN(amount)) return 'Rp 0'
    return `Rp ${new Intl.NumberFormat('id-ID').format(amount)}`
  }

  // Date-only API values ('2027-10-03'). Anchored to local midnight so the day never shifts.
  function formatDate(value) {
    if (!value) return '-'
    return new Date(`${value}T00:00:00`).toLocaleDateString('id-ID', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  }

  function formatDuration(totalSeconds) {
    if (!totalSeconds || totalSeconds < 0) return '0m'
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    if (hours > 0) return `${hours}j ${minutes}m`
    return `${minutes}m`
  }

  function formatTime(dateStr) {
    if (!dateStr) return '--:--'
    return new Date(dateStr).toLocaleTimeString('id-ID', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function formatDateTime(dateStr) {
    if (!dateStr) return '--'
    return new Date(dateStr).toLocaleString('id-ID', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function maskCardNumber(cardNumber) {
    if (!cardNumber || cardNumber.length < 8) return '****'
    return `**** **** **** ${cardNumber.slice(-4)}`
  }

  function detectCardType(cardNumber) {
    if (!cardNumber) return 'Unknown'
    if (cardNumber.startsWith('00') || cardNumber.startsWith('01')) return 'Mandiri eMoney'
    if (cardNumber.startsWith('02')) return 'BRI Brizzi'
    if (cardNumber.startsWith('03')) return 'BNI TapCash'
    if (cardNumber.startsWith('04')) return 'BCA Flazz'
    return 'E-Money'
  }

  return {
    formatCurrency,
    formatDate,
    formatDuration,
    formatTime,
    formatDateTime,
    maskCardNumber,
    detectCardType,
  }
}
