import { ref, watch } from 'vue'

export type ThemeName = 'light' | 'dark'

const STORAGE_KEY = 'sheetkit-theme'

function readStored(): ThemeName {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // A page served from an opaque origin has no usable localStorage.
  }
  return 'light'
}

const theme = ref<ThemeName>(readStored())

watch(
  theme,
  (value) => {
    document.documentElement.classList.remove('light', 'dark')
    document.documentElement.classList.add(value)
    try {
      window.localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // Preference simply does not persist; the app still works.
    }
  },
  { immediate: true },
)

export function useTheme() {
  return {
    theme,
    toggle: () => {
      theme.value = theme.value === 'light' ? 'dark' : 'light'
    },
  }
}
