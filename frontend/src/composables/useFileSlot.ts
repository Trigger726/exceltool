import { ref } from 'vue'

import { api, type FileProfile, type TablePage } from '@/services/bridge'

/** One selected file plus its structure and preview.
 *
 * The compare view needs two of these and the clean view needs one, so the
 * loading, sheet choice and paging live here rather than in each page. */
export function useFileSlot() {
  const path = ref<string | null>(null)
  const name = ref<string | null>(null)
  const profile = ref<FileProfile | null>(null)
  const sheet = ref<string | null>(null)
  const headerRow = ref(1)
  const columns = ref<string[]>([])
  const table = ref<TablePage | null>(null)
  const loading = ref(false)

  async function refresh() {
    if (!path.value) return
    loading.value = true
    try {
      const response = await api.preview({
        path: path.value,
        sheet: sheet.value,
        header_row: headerRow.value,
        offset: 0,
        limit: 50,
      })
      table.value = response.table
      columns.value = response.table.columns
    } finally {
      loading.value = false
    }
  }

  async function setPath(next: string) {
    path.value = next
    const response = await api.describe(next)
    profile.value = response.file
    name.value = response.file.name
    sheet.value = response.file.sheets[0]?.name ?? null
    headerRow.value = 1
    await refresh()
  }

  async function page(offset: number) {
    if (!path.value) return
    loading.value = true
    try {
      const response = await api.preview({
        path: path.value,
        sheet: sheet.value,
        header_row: headerRow.value,
        offset,
        limit: 50,
      })
      table.value = response.table
    } finally {
      loading.value = false
    }
  }

  function clear() {
    path.value = null
    name.value = null
    profile.value = null
    sheet.value = null
    headerRow.value = 1
    columns.value = []
    table.value = null
  }

  return {
    path,
    name,
    profile,
    sheet,
    headerRow,
    columns,
    table,
    loading,
    setPath,
    refresh,
    page,
    clear,
  }
}
