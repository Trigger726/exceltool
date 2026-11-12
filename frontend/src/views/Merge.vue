<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Download, FolderPlus, Play, Plus, Search, Trash2, X } from 'lucide-vue-next'

import ExportFeedback from '@/components/ExportFeedback.vue'
import DataTable from '@/components/DataTable.vue'
import NoticeList from '@/components/NoticeList.vue'
import WorkflowSteps from '@/components/WorkflowSteps.vue'
import PageHeader from '@/components/PageHeader.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import TemplateControls from '@/components/TemplateControls.vue'
import StatTile from '@/components/StatTile.vue'
import { registerDropTarget } from '@/composables/useDropTarget'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import {
  api,
  newJobId,
  SheetKitError,
  type AnalyzeResponse,
  type MergePlan,
  type HeaderSuggestion,
  type TablePage,
  type TemplateRule,
} from '@/services/bridge'

interface SourceItem {
  path: string
  name: string
  sheet: string | null
  headerRow: number
  headerHint: HeaderSuggestion | null
  enabled: boolean
  mapping: Record<string, string>
  columns: string[]
  sheets: string[]
}

const toast = useToast()
const progress = useProgress()

const sources = ref<SourceItem[]>([])
const plan = ref<MergePlan | null>(null)
const activeIndex = ref(0)
const result = ref<AnalyzeResponse | null>(null)
const resultsPanel = ref<HTMLElement | null>(null)
const completedConfig = ref('')
const configuration = computed(() => JSON.stringify(sources.value.map(payloadOf)))
const settingsChanged = computed(() => !!result.value && completedConfig.value !== configuration.value)
let disposed = false
const resultTable = ref<TablePage | null>(null)
const busy = ref(false)
const exporting = ref(false)
const exportedPath = ref('')
const mappingDraft = ref<Record<string, string>>({})
const filterText = ref('')
const currentJob = ref('')
const loading = ref(false)
const canRun = computed(() => !!plan.value?.sources.some((source) => !source.skipped) && !loading.value)
const inputWarnings = ref<string[]>([])
const templateRule = computed(() => {
  const merged = new Map<string, string>()
  for (const source of sources.value.filter((item) => item.enabled)) {
    for (const column of source.columns) {
      const target = Object.prototype.hasOwnProperty.call(source.mapping, column) ? source.mapping[column] : column
      if (merged.has(column) && merged.get(column) !== target) return null
      merged.set(column, target)
    }
  }
  const rules = [...merged].filter(([column, target]) => column !== target)
  return rules.length && plan.value && !loading.value ? Object.fromEntries(rules) : null
})
let unregisterDrop: (() => void) | undefined
onMounted(() => {
  unregisterDrop = registerDropTarget('merge', (paths) => {
    void addPaths(paths).catch((error) => toast.error(messageOf(error)))
  })
})

let filterTimer: number | undefined

watch(filterText, () => {
  window.clearTimeout(filterTimer)
  filterTimer = window.setTimeout(() => {
    loadResultPage(0)
  }, 300)
})

function messageOf(error: unknown) {
  if (error instanceof SheetKitError) return error.message
  return '操作失败，请重试'
}

function payloadOf(item: SourceItem) {
  return {
    path: item.path,
    sheet: item.sheet,
    header_row: item.headerRow,
    mapping: item.mapping,
    enabled: item.enabled,
  }
}

async function addPaths(paths: string[]) {
  if (loading.value || currentJob.value) return
  loading.value = true
  const known = new Set(sources.value.map((item) => item.path.toLowerCase()))
  inputWarnings.value = []
  try {
    for (const path of paths) {
      if (known.has(path.toLowerCase())) continue
      try {
        const { file } = await api.describe(path)
        const sheet = file.sheets[0]?.name ?? null
        const hint = await api.recommendHeader({ path, sheet })
        sources.value.push({
          path, name: file.name, sheet, headerRow: hint.row ?? 1, headerHint: hint,
          enabled: true, mapping: {}, columns: [], sheets: file.sheets.map((entry) => entry.name),
        })
        known.add(path.toLowerCase())
      } catch (error) {
        inputWarnings.value.push(`${path.split(/[\\/]/).pop()} 未加入。 ${messageOf(error)}`)
      }
    }
  } finally {
    loading.value = false
  }
  await refreshPlan()
}

async function addFiles() {
  try {
    const response = await api.chooseFiles('multi')
    if (response.paths.length) await addPaths(response.paths)
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function addFolder() {
  try {
    const picked = await api.chooseFiles('folder')
    const folder = picked.paths[0]
    if (!folder) return
    const listed = await api.listFolder(folder)
    if (!listed.paths.length) {
      toast.info('该文件夹里没有可合并的 Excel 或 CSV 文件。')
      return
    }
    await addPaths(listed.paths)
  } catch (error) {
    toast.error(messageOf(error))
  }
}

function removeSource(index: number) {
  sources.value.splice(index, 1)
  if (activeIndex.value >= sources.value.length) {
    activeIndex.value = Math.max(0, sources.value.length - 1)
  }
  refreshPlan()
}

async function refreshPlan() {
  plan.value = null
  if (!sources.value.some((item) => item.enabled)) {
    plan.value = null
    return
  }
  loading.value = true
  try {
    const response = await api.plan(sources.value.map(payloadOf))
    plan.value = response.plan
    response.plan.sources.forEach((entry, index) => {
      const item = sources.value[index]
      if (item) item.columns = entry.columns
    })
    syncMappingDraft()
    return true
  } catch (error) {
    toast.error(messageOf(error))
    return false
  } finally {
    loading.value = false
  }
}

async function changeSheet(item: SourceItem) {
  loading.value = true
  try {
    item.headerHint = await api.recommendHeader({ path: item.path, sheet: item.sheet })
    item.headerRow = item.headerHint.row ?? 1
  } catch (error) {
    toast.error(messageOf(error))
  } finally {
    loading.value = false
  }
  await refreshPlan()
}

function syncMappingDraft() {
  const item = sources.value[activeIndex.value]
  mappingDraft.value = Object.fromEntries((item?.columns ?? []).map((column) =>
    [column, Object.prototype.hasOwnProperty.call(item?.mapping, column) ? item!.mapping[column] : column]))
}

function commitMapping() {
  const item = sources.value[activeIndex.value]
  if (!item) return
  item.mapping = Object.fromEntries(Object.entries(mappingDraft.value)
    .map(([column, target]) => [column, target.trim()])
    .filter(([column, target]) => target && target !== column))
  void refreshPlan()
}

async function applyMappings(next: Record<string, string>[]) {
  if (loading.value || currentJob.value) return
  const previous = sources.value.map((item) => item.mapping)
  sources.value.forEach((item, index) => { item.mapping = next[index] })
  if (!await refreshPlan()) {
    sources.value.forEach((item, index) => { item.mapping = previous[index] })
    await refreshPlan()
    return
  }
  toast.success('已应用列名对应关系')
}

function applySuggestions() {
  const next = sources.value.map((item) => ({ ...item.mapping }))
  for (const item of plan.value?.suggestions ?? []) {
    next[item.source_index] = { ...next[item.source_index], [item.column]: item.target }
  }
  void applyMappings(next)
}

function applyTemplate(rule: TemplateRule) {
  if (Array.isArray(rule)) return
  const available = new Set(sources.value.filter((item) => item.enabled).flatMap((item) => item.columns))
  const missing = Object.keys(rule).filter((column) => !available.has(column))
  if (missing.length) {
    toast.error(`模板需要以下列，请先检查表头或更换模板：${missing.join('、')}`)
    return
  }
  void applyMappings(sources.value.map((item) => item.enabled
    ? Object.fromEntries(Object.entries(rule).filter(([column]) => item.columns.includes(column)))
    : item.mapping))
}

function resetMapping() {
  const item = sources.value[activeIndex.value]
  if (!item) return
  item.mapping = {}
  syncMappingDraft()
  void refreshPlan()
}

function selectSource(index: number) {
  activeIndex.value = index
  syncMappingDraft()
}

async function run() {
  if (!canRun.value || currentJob.value) return
  busy.value = true
  progress.begin('准备合并')
  const jobId = newJobId()
  currentJob.value = jobId
  const configurationAtStart = configuration.value
  try {
    const response = await api.analyze({
      action: 'merge',
      job_id: jobId,
      sources: sources.value.map(payloadOf),
    })
    if (disposed) {
      await api.release(response.result_id)
      return
    }
    if (result.value) void api.release(result.value.result_id).catch(() => undefined)
    exportedPath.value = ''
    completedConfig.value = configurationAtStart
    result.value = response
    void nextTick(() => resultsPanel.value?.scrollIntoView({ block: 'start' }))
    resultTable.value = response.preview.merged
    filterText.value = ''
    toast.success(`合并完成，共 ${response.summary.total_rows} 行。`)
  } catch (error) {
    if (error instanceof SheetKitError && error.code === 'E_CANCELLED') {
      toast.info('已取消本次合并。')
    } else {
      toast.error(messageOf(error))
    }
  } finally {
    currentJob.value = ''
    busy.value = false
    progress.end()
  }
}

async function cancelRun() {
  if (!currentJob.value) return
  await api.cancel(currentJob.value).catch(() => undefined)
}

async function exportResult() {
  if (!result.value || settingsChanged.value) return
  if (currentJob.value || exporting.value) return
  exporting.value = true
  try {
    const picked = await api.chooseFiles('save', { save_name: '合并汇总.xlsx' })
    const destination = picked.paths[0]
    if (!destination || disposed) return
    const jobId = newJobId()
    currentJob.value = jobId
    progress.begin('正在导出 Excel')
    const written = await api.export({
      kind: 'merge',
      job_id: jobId,
      result_id: result.value.result_id,
      destination,
    })
    if (disposed) return
    exportedPath.value = written.path
    void nextTick(() => document.querySelector('[data-export-feedback]')?.scrollIntoView({ block: 'nearest' }))
    toast.success('已导出 Excel')
  } catch (error) {
    if (error instanceof SheetKitError && error.code === 'E_CANCELLED') {
      toast.info('已取消导出。')
    } else {
      toast.error(messageOf(error))
    }
  } finally {
    currentJob.value = ''
    exporting.value = false
    busy.value = false
    progress.end()
  }
}

let pageRequest = 0
async function loadResultPage(offset: number) {
  if (!result.value || currentJob.value) return
  const request = ++pageRequest
  const resultId = result.value.result_id
  busy.value = true
  try {
    const response = await api.page({
      result_id: resultId,
      table: 'merged',
      offset,
      limit: 50,
      filter: filterText.value,
    })
    if (request !== pageRequest || resultId !== result.value?.result_id) return
    resultTable.value = response.table
  } catch (error) {
    if (request === pageRequest) toast.error(messageOf(error))
  } finally {
    if (request === pageRequest && !currentJob.value) busy.value = false
  }
}

function pageResult(offset: number) {
  return loadResultPage(offset)
}

onBeforeUnmount(() => {
  disposed = true
  unregisterDrop?.()
  window.clearTimeout(filterTimer)
  if (currentJob.value) void cancelRun()
  if (result.value) api.release(result.value.result_id).catch(() => undefined)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <PageHeader title="批量合并" caption="把多个结构相同或相近的表格纵向汇总为一个文件。">
      <template #actions>
        <button type="button" class="btn btn-default" :disabled="!currentJob" @click="cancelRun">
          <X :size="14" />
          取消
        </button>
        <button type="button" class="btn btn-primary" :disabled="!canRun || !!currentJob || exporting" @click="run">
          <Play :size="14" />
          开始合并
        </button>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!result || settingsChanged || !!currentJob || exporting"
          @click="exportResult"
        >
          <Download :size="14" />
          导出文件
        </button>
      </template>
      <WorkflowSteps :stage="result && !settingsChanged ? 3 : sources.length ? 2 : 1" />
      <ProgressBar class="my-2" :busy="progress.state.busy" :stage="progress.state.stage" :ratio="progress.state.ratio" />
    </PageHeader>

    <div class="workspace flex-1 space-y-4 overflow-auto">
      <!-- 1. 文件列表 -->
      <section class="card workflow-panel">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold">1 · 待合并的文件</h2>
          <div class="flex gap-2">
            <button type="button" class="btn btn-default" :disabled="loading || !!currentJob" @click="addFiles">
              <Plus :size="14" />
              添加文件
            </button>
            <button type="button" class="btn btn-default" :disabled="loading || !!currentJob" @click="addFolder">
              <FolderPlus :size="14" />
              添加文件夹
            </button>
          </div>
        </div>

        <NoticeList class="mb-2" :messages="inputWarnings" />
        <p v-if="loading" role="status" class="mb-2 text-sm text-ink-muted">正在读取文件和列名…</p>
        <div
          v-if="!sources.length"
          class="drop-surface px-4 py-10 text-center text-sm text-ink-muted"
        >
          点击“添加文件”选择多个 Excel，或直接把文件拖进窗口。
        </div>

        <ul v-else class="space-y-1.5">
          <li
            v-for="(item, index) in sources"
            :key="item.path"
            class="flex flex-wrap items-center gap-2.5 rounded-control border px-3 py-2 transition-colors"
            :class="
              index === activeIndex ? 'border-primary bg-primary-soft/40' : 'border-line hover:bg-line-soft/60'
            "
            @click="selectSource(index)"
          >
            <input
              v-model="item.enabled"
              type="checkbox"
              class="accent-primary"
              title="是否参与合并"
              :disabled="loading || !!currentJob"
              @change="refreshPlan()"
              @click.stop
            />
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm font-medium">{{ item.name }}</div>
              <div class="truncate text-2xs text-ink-faint" :title="item.path">{{ item.path }}</div>
            </div>
            <select
              v-model="item.sheet"
              class="field !w-32 !py-1 text-xs"
              aria-label="工作表"
              :disabled="loading || !!currentJob || !item.sheets.length"
              @click.stop
              @change="changeSheet(item)"
            >
              <option v-if="!item.sheets.length" :value="null">CSV 数据</option>
              <option v-for="sheet in item.sheets" :key="sheet" :value="sheet">{{ sheet }}</option>
            </select>
            <label class="flex items-center gap-1 text-xs text-ink-muted" @click.stop>
              表头行
              <input
                v-model.number="item.headerRow"
                type="number"
                min="1"
                max="10000"
                :disabled="loading || !!currentJob"
                class="field !w-14 !py-1 text-center text-xs"
                @change="item.headerHint = null; refreshPlan()"
              />
            </label>
            <button
              type="button"
              class="rounded p-1 text-ink-faint transition-colors hover:bg-danger-soft hover:text-danger"
              :disabled="loading || !!currentJob"
              :aria-label="`移除 ${item.name}`"
              @click.stop="removeSource(index)"
            >
              <Trash2 :size="14" />
            </button>
            <p v-if="item.headerHint && (!item.headerHint.row || item.headerHint.row > 1)" class="basis-full pl-6 text-xs text-ink-muted">
              {{ item.headerHint.row ? `推荐第 ${item.headerHint.row} 行为表头。 ` : '' }}{{ item.headerHint.reason }}
            </p>
          </li>
        </ul>
      </section>

      <!-- 2. 字段映射 -->
      <section v-if="sources.length" class="card workflow-panel">
        <h2 class="mb-2 text-sm font-semibold">2 · 确认列如何对齐</h2>
        <p class="mb-3 text-xs text-ink-muted">同名列自动对齐。未对齐的列单独保留，缺失处留空。</p>
        <div v-if="plan?.suggestions.length" class="recommendation mb-3">
          <ul class="max-h-32 min-w-0 flex-1 space-y-1 overflow-auto">
            <li v-for="item in plan.suggestions" :key="`${item.source_index}-${item.column}`">
              {{ sources[item.source_index].name }}：{{ item.column }} → {{ item.target }}
            </li>
          </ul>
          <button type="button" class="btn btn-default" :disabled="loading || !!currentJob"
            @click="applySuggestions">确认使用推荐</button>
        </div>
        <details class="advanced">
          <summary>手动调整列名与模板</summary>
        <p class="my-3 text-xs text-ink-muted">将不同表格中含义相同的列填为同一个目标列名。</p>

        <div class="mb-3 flex flex-wrap gap-1.5">
          <button
            v-for="(item, index) in sources"
            :key="item.path"
            type="button"
            class="chip"
            :class="index === activeIndex ? 'chip-primary' : 'chip-neutral'"
            @click="selectSource(index)"
          >
            {{ item.name }}
          </button>
        </div>

        <div
          v-if="sources[activeIndex]?.columns.length"
          class="max-h-56 overflow-auto rounded-control border border-line"
        >
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-line-soft/95">
              <tr>
                <th class="w-1/2 border-b border-line px-3 py-1.5 text-left text-2xs font-semibold text-ink-muted">
                  源字段
                </th>
                <th class="w-1/2 border-b border-line px-3 py-1.5 text-left text-2xs font-semibold text-ink-muted">
                  目标字段名
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="column in sources[activeIndex].columns" :key="column" class="border-b border-line-soft last:border-0">
                <td class="selectable px-3 py-1.5 text-ink-muted">{{ column }}</td>
                <td class="px-3 py-1">
                  <input
                    v-model="mappingDraft[column]"
                    class="field !py-1 text-xs"
                    :disabled="loading || !!currentJob"
                    @change="commitMapping"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-xs text-ink-faint">当前文件没有可调整的列。</p>
        <button v-if="Object.keys(sources[activeIndex]?.mapping ?? {}).length" type="button"
          class="btn btn-ghost mt-2" :disabled="loading || !!currentJob" @click="resetMapping">恢复此文件原列名</button>
        <div class="mt-3 border-t border-line pt-3">
          <TemplateControls kind="merge" :rule="templateRule" @apply="applyTemplate" />
          <p class="mt-1 text-xs text-ink-muted">模板可复用各文件一致的列名对应关系。</p>
        </div>
        </details>
      </section>

      <!-- 3. 合并预览 -->
      <section v-if="plan" class="card workflow-panel">
        <h2 class="mb-3 text-sm font-semibold">合并结果字段</h2>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="column in plan.target_columns" :key="column" class="chip chip-neutral">
            {{ column }}
          </span>
        </div>
        <NoticeList class="mt-3" :messages="plan.warnings" />
      </section>

      <ExportFeedback v-if="exportedPath && !settingsChanged" :path="exportedPath" />

      <!-- 结果 -->
      <section v-if="result" ref="resultsPanel" class="card workflow-panel">
        <h2 class="mb-3 text-sm font-semibold">3 · 合并结果</h2>
        <NoticeList v-if="settingsChanged" class="mb-3" :messages="['下方显示上一次的结果。文件或配置已更改，请重新运行后再导出。']" />
        <div class="stat-grid grid gap-3">
          <StatTile label="已合并文件" :value="result.summary.merged_file_count" />
          <StatTile label="读取记录数" :value="result.summary.total_rows" />
          <StatTile label="合并后总行数" :value="result.summary.total_rows" tone="primary" />
          <StatTile label="目标字段数" :value="result.summary.total_columns" />
          <StatTile label="已跳过文件" :value="result.summary.file_count - result.summary.merged_file_count" />
        </div>

        <NoticeList class="mt-3" :messages="result.warnings" />
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <div class="relative flex-1">
            <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input
              v-model="filterText"
              type="search"
              class="field !pl-7"
              placeholder="在合并结果中筛选（匹配任意一列即可）"
            />
          </div>
          <span class="shrink-0 text-xs tabular-nums text-ink-faint">
            筛选后 {{ resultTable?.total ?? 0 }} / {{ result?.summary.total_rows ?? 0 }} 行
          </span>
        </div>

        <div class="mt-4 flex max-h-[320px] flex-col">
          <DataTable
            :table="resultTable"
            :busy="busy"
            empty-text="没有合并任何数据"
            @page="pageResult"
          />
        </div>
      </section>
    </div>
  </div>
</template>
