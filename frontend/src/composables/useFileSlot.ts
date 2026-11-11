import { ref } from 'vue'

import { api, type FileProfile, type HeaderSuggestion, type TablePage } from '@/services/bridge'

export function useFileSlot() {
  const path = ref<string | null>(null)
  const name = ref<string | null>(null)
  const profile = ref<FileProfile | null>(null)
  const sheet = ref<string | null>(null)
  const headerRow = ref(1)
  const headerHint = ref<HeaderSuggestion | null>(null)
  const columns = ref<string[]>([])
  const table = ref<TablePage | null>(null)
  const loading = ref(false)

  function source() {
    return { path: path.value, sheet: sheet.value, header_row: headerRow.value }
  }

  async function load(offset: number) {
    const response = await api.preview({ ...source(), offset, limit: 50 })
    table.value = response.table
    if (!offset) columns.value = response.table.columns
  }

  async function detectHeader() {
    const suggestion = await api.recommendHeader(source())
    headerHint.value = suggestion
    headerRow.value = suggestion.row ?? 1
  }

  async function refresh(detect = false) {
    if (!path.value || loading.value) return
    loading.value = true
    table.value = null
    try {
      headerHint.value = null
      if (detect) await detectHeader()
      await load(0)
    } catch (error) {
      columns.value = []
      throw error
    } finally {
      loading.value = false
    }
  }

  async function setPath(next: string) {
    if (loading.value) return
    loading.value = true
    try {
      const response = await api.describe(next)
      path.value = next
      profile.value = response.file
      name.value = response.file.name
      sheet.value = response.file.sheets[0]?.name ?? null
      headerRow.value = 1
      table.value = null
      headerHint.value = null
      await detectHeader()
      await load(0)
    } catch (error) {
      if (!table.value) columns.value = []
      throw error
    } finally {
      loading.value = false
    }
  }

  async function page(offset: number) {
    if (!path.value || loading.value) return
    loading.value = true
    try {
      await load(offset)
    } finally {
      loading.value = false
    }
  }

  function clear() {
    if (loading.value) return
    path.value = null
    name.value = null
    profile.value = null
    sheet.value = null
    headerRow.value = 1
    headerHint.value = null
    columns.value = []
    table.value = null
  }

  return { path, name, profile, sheet, headerRow, headerHint, columns, table, loading,
    source, setPath, refresh, page, clear }
}
