/** Typed access to the Python bridge that the desktop shell exposes.
 *
 * Every call returns the same envelope, so the UI only has to handle one
 * failure shape: { ok: false, error: { code, message } }. */

export interface BridgeError {
  code: string
  message: string
  detail?: string
  context?: Record<string, unknown>
}

export class SheetKitError extends Error {
  readonly code: string
  readonly detail?: string
  readonly context?: Record<string, unknown>

  constructor(error: BridgeError) {
    super(error.message)
    this.name = 'SheetKitError'
    this.code = error.code
    this.detail = error.detail
    this.context = error.context
  }
}

interface PywebviewApi {
  [method: string]: (payload: unknown) => Promise<unknown>
}

interface PywebviewWindow extends Window {
  pywebview?: { api?: PywebviewApi }
}

declare global {
  interface Window {
    sheetkitProgress?: (payload: { stage: string; ratio: number }) => void
    sheetkitDrop?: (paths: string[]) => void
  }
}

function bridge(): PywebviewApi | null {
  return (window as PywebviewWindow).pywebview?.api ?? null
}

/** Resolves once the shell has published the Python API to the page. */
export const bridgeReady = new Promise<void>((resolve) => {
  if (bridge()) {
    resolve()
    return
  }
  const done = () => resolve()
  window.addEventListener('pywebviewready', done, { once: true })
  // The event may already have fired before this module was evaluated.
  const timer = window.setInterval(() => {
    if (bridge()) {
      window.clearInterval(timer)
      resolve()
    }
  }, 120)
  window.setTimeout(() => {
    window.clearInterval(timer)
    resolve()
  }, 8000)
})

async function call<T>(method: string, payload: unknown = {}): Promise<T> {
  await bridgeReady
  const api = bridge()
  if (!api) {
    throw new SheetKitError({ code: 'E_NO_BRIDGE', message: '桌面桥接尚未就绪，请稍候重试' })
  }
  const response = (await api[method](payload)) as
    | { ok: true }
    | { ok: false; error: BridgeError }
  if (!response || typeof response !== 'object') {
    throw new SheetKitError({ code: 'E_INTERNAL', message: '桌面桥接返回了无法识别的结果' })
  }
  if (!response.ok) {
    throw new SheetKitError(response.error)
  }
  return response as T
}

export interface FileProfile {
  path: string
  name: string
  kind: string
  sheets: { name: string; max_row: number | null; max_column: number | null }[]
  has_macros: boolean
  maybe_open_elsewhere: boolean
  encoding: string | null
  delimiter: string | null
  warnings: string[]
}

export interface TablePage {
  columns: string[]
  rows: string[][]
  offset: number
  limit: number
  total: number
  unfiltered_total?: number
  filter?: string
  row_numbers: number[]
  sheet: string | null
  header_row: number
  blank_rows: number
  warnings: string[]
  truncated: boolean
  name: string
}

/** A job id the page picks itself, so a running job can still be cancelled. */
export function newJobId(): string {
  return `job-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export interface MergeSourcePayload {
  path: string
  sheet?: string | null
  header_row?: number
  mapping?: Record<string, string>
  enabled?: boolean
}

export interface MergePlan {
  sources: {
    path: string
    name: string
    sheet: string
    header_row: number
    columns: string[]
    mapped_columns: string[]
    rows: number
    skipped: boolean
    warnings: string[]
  }[]
  body_columns: string[]
  source_columns: string[]
  target_columns: string[]
  partial_columns: string[]
  warnings: string[]
}

export interface AnalyzeResponse {
  result_id: string
  kind: 'compare' | 'merge' | 'clean'
  summary: Record<string, any>
  warnings: string[]
  tables: Record<string, { columns: string[]; total: number }>
  preview: Record<string, TablePage>
}

export const api = {
  chooseFiles: (kind: 'open' | 'multi' | 'folder' | 'save', extra: Record<string, unknown> = {}) =>
    call<{ paths: string[] }>('choose_files', { kind, ...extra }),
  listFolder: (path: string) => call<{ paths: string[] }>('list_folder', { path }),
  describe: (path: string) => call<{ file: FileProfile }>('describe', { path }),
  preview: (payload: Record<string, unknown>) => call<{ table: TablePage }>('preview', payload),
  plan: (sources: MergeSourcePayload[]) => call<{ plan: MergePlan }>('plan', { sources }),
  analyze: (payload: Record<string, unknown>) => call<AnalyzeResponse>('analyze', payload),
  page: (payload: Record<string, unknown>) => call<{ table: TablePage }>('page', payload),
  cancel: (jobId: string) => call<{ cancelled: boolean }>('cancel', { job_id: jobId }),
  impact: (payload: Record<string, unknown>) =>
    call<{ impact: Record<string, any> }>('impact', payload),
  export: (payload: Record<string, unknown>) => call<{ path: string }>('export', payload),
  release: (resultId: string) => call<Record<string, never>>('release', { result_id: resultId }),
}
