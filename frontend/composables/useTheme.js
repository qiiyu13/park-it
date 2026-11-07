const STORAGE_KEY = 'eparking-theme'

/**
 * Light/dark theme, stored per browser (a booth PC keeps its own choice).
 * ponytail: applied after mount to avoid a hydration mismatch, so a dark
 * screen flashes light on hard reload. Move to an inline head script if the
 * flash bothers night shifts.
 */
export function useTheme() {
  const theme = useState('theme', () => 'light')

  function setTheme(value) {
    theme.value = value
    document.documentElement.classList.toggle('dark', value === 'dark')
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // Storage blocked: the theme still applies for this session.
    }
  }

  function loadTheme() {
    let saved = null
    try {
      saved = localStorage.getItem(STORAGE_KEY)
    } catch {
      // Storage blocked: stay on the default.
    }
    if (saved === 'dark' || saved === 'light') setTheme(saved)
  }

  function toggleTheme() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, loadTheme, toggleTheme }
}
