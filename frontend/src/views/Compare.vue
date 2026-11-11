<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Download, Play, Search, X } from 'lucide-vue-next'
import ExportFeedback from '@/components/ExportFeedback.vue'
import DataTable from '@/components/DataTable.vue'
import FileSettings from '@/components/FileSettings.vue'
import FilePicker from '@/components/FilePicker.vue'
import NoticeList from '@/components/NoticeList.vue'
import WorkflowSteps from '@/components/WorkflowSteps.vue'
import PageHeader from '@/components/PageHeader.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import StatTile from '@/components/StatTile.vue'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import { useFileSlot } from '@/composables/useFileSlot'
import {
  api,
  newJobId,
  SheetKitError,
  type AnalyzeResponse,
  type MatchSuggestion,
  type TablePage,
} from '@/services/bridge'

const toast = useToast()
const progress = useProgress()

const oldFile = useFileSlot()
const newFile = useFileSlot()

const previewSide = ref<'old' | 'new'>('old')
const keys = ref<string[]>([])
const suggestion = ref<MatchSuggestion | null>(null)
const suggesting = ref(false)
const ignoreWhitespace = ref(true)
const ignoreCase = ref(false)
const includeUnchanged = ref(false)
const numericColumns = ref<string[]>([])
const numericTolerance = ref('0')
const compareColumns = ref<string[]>([])

const result = ref<AnalyzeResponse | null>(null)
const resultsPanel = ref<HTMLElement | null>(null)
const completedConfig = ref('')
const configuration = computed(() => JSON.stringify([oldFile.source(), newFile.source(),
  keys.value, ignoreWhitespace.value, ignoreCase.value, numericColumns.value,
  numericTolerance.value, compareColumns.value, includeUnchanged.value]))
const settingsChanged = computed(() => !!result.value && completedConfig.value !== configuration.value)
let disposed = false
const activeTab = ref<'added' | 'deleted' | 'changed' | 'anomaly' | 'minor' | 'unchanged'>('added')
const resultTables = ref<Record<string, TablePage>>({})
const resultBusy = ref(false)
const exporting = ref(false)
const exportedPath = ref('')
const filterText = ref('')
const currentJob = ref('')

let filterTimer: number | undefined

watch(filterText, () => {
  window.clearTimeout(filterTimer)
  filterTimer = window.setTimeout(() => {
    loadResultPage(0)
  }, 300)
})

watch(activeTab, () => {
  loadResultPage(0)
})

const sharedColumns = computed(() =>
  oldFile.columns.value.filter((column) => newFile.columns.value.includes(column)),
)

const canRun = computed(
  () => Boolean(oldFile.table.value && newFile.table.value && keys.value.length > 0 && !oldFile.loading.value && !newFile.loading.value),
)

watch(sharedColumns, (columns) => {
  keys.value = keys.value.filter((key) => columns.includes(key))
  numericColumns.value = numericColumns.value.filter((column) => columns.includes(column))
  compareColumns.value = compareColumns.value.filter((column) => columns.includes(column))
})

watch([sharedColumns, ignoreWhitespace, ignoreCase], async (_next, _previous, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  suggestion.value = null
  suggesting.value = false
  if (!oldFile.table.value || !newFile.table.value || !sharedColumns.value.length) return
  suggesting.value = true
  try {
    const response = await api.recommendMatch({
      old: oldFile.source(), new: newFile.source(),
      ignore_whitespace: ignoreWhitespace.value, ignore_case: ignoreCase.value,
    })
    if (!stale) suggestion.value = response
  } catch (error) {
    if (!stale) toast.error(messageOf(error))
  } finally {
    if (!stale) suggesting.value = false
  }
})

function toggle(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

async function pickOld() {
  try {
    const response = await api.chooseFiles('open')
    if (response.paths[0]) {
      await oldFile.setPath(response.paths[0])
      previewSide.value = 'old'
    }
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function pickNew() {
  try {
    const response = await api.chooseFiles('open')
    if (response.paths[0]) {
      await newFile.setPath(response.paths[0])
      previewSide.value = 'new'
    }
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function reload(slot: 'old' | 'new', detect: boolean) {
  const target = slot === 'old' ? oldFile : newFile
  try {
    await target.refresh(detect)
  } catch (error) {
    toast.error(messageOf(error))
  }
}

function onDropped(side: 'old' | 'new', paths: string[]) {
  if (currentJob.value) return
  const target = side === 'old' ? oldFile : newFile
  const file = paths[0]
  if (!file) return
  previewSide.value = side
  target.setPath(file).catch((error) => toast.error(messageOf(error)))
}

function messageOf(error: unknown) {
  if (error instanceof SheetKitError) return error.message
  return '操作失败，请重试'
}

async function run() {
  if (currentJob.value || !canRun.value || !oldFile.path.value || !newFile.path.value) return
  resultBusy.value = true
  progress.begin('准备对比')
  const jobId = newJobId()
  currentJob.value = jobId
  const configurationAtStart = configuration.value
  try {
    const response = await api.analyze({
      action: 'compare',
      job_id: jobId,
      old_path: oldFile.path.value,
      new_path: newFile.path.value,
      old_sheet: oldFile.sheet.value,
      new_sheet: newFile.sheet.value,
      old_header_row: oldFile.headerRow.value,
      new_header_row: newFile.headerRow.value,
      keys: keys.value,
      options: {
        ignore_whitespace: ignoreWhitespace.value,
        ignore_case: ignoreCase.value,
        include_unchanged: includeUnchanged.value,
        numeric_columns: numericColumns.value,
        numeric_tolerance: numericTolerance.value,
        compare_columns: compareColumns.value,
      },
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
    resultTables.value = response.preview
    activeTab.value = response.summary.modified_fields ? 'changed' : response.summary.added ? 'added' : response.summary.deleted ? 'deleted' : response.summary.minor_fields ? 'minor' : 'anomaly'
    filterText.value = ''
    if (response.summary.anomalies || response.summary.unmatched) {
      toast.info('有部分记录因匹配字段为空或重复未参与比对，请查看“异常记录”。')
    } else {
      toast.success('对比完成。')
    }
  } catch (error) {
    if (error instanceof SheetKitError && error.code === 'E_CANCELLED') {
      toast.info('已取消本次对比。')
    } else {
      toast.error(messageOf(error))
    }
  } finally {
    currentJob.value = ''
    resultBusy.value = false
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
    const picked = await api.chooseFiles('save', { save_name: '差异对比报告.xlsx' })
    const destination = picked.paths[0]
    if (!destination || disposed) return
    const jobId = newJobId()
    currentJob.value = jobId
    progress.begin('正在导出 Excel')
    const written = await api.export({
      kind: 'compare',
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
    resultBusy.value = false
    progress.end()
  }
}

let pageRequest = 0
async function loadResultPage(offset: number) {
  if (!result.value || currentJob.value) return
  const request = ++pageRequest
  const resultId = result.value.result_id
  const tab = activeTab.value
  resultBusy.value = true
  try {
    const response = await api.page({
      result_id: resultId,
      table: tab,
      offset,
      limit: 50,
      filter: filterText.value,
    })
    if (request !== pageRequest || resultId !== result.value?.result_id) return
    resultTables.value = { ...resultTables.value, [tab]: response.table }
  } catch (error) {
    if (request === pageRequest) toast.error(messageOf(error))
  } finally {
    if (request === pageRequest && !currentJob.value) resultBusy.value = false
  }
}

function pageResult(offset: number) {
  return loadResultPage(offset)
}

const tabs = [
  { key: 'added', label: '新增记录' },
  { key: 'deleted', label: '删除记录' },
  { key: 'changed', label: '修改明细' },
  { key: 'anomaly', label: '异常记录' },
  { key: 'minor', label: '细微差异' },
  { key: 'unchanged', label: '按规则未变化' },
] as const

onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(filterTimer)
  if (currentJob.value) void cancelRun()
  if (result.value) api.release(result.value.result_id).catch(() => undefined)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <PageHeader
      title="表格对比"
      caption="找出两张表中新增、删除和修改的记录。"
    >
      <template #actions>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!currentJob"
          @click="cancelRun"
        >
          <X :size="14" />
          取消
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!canRun || !!currentJob || exporting"
          @click="run"
        >
          <Play :size="14" />
          开始对比
        </button>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!result || settingsChanged || !!currentJob || exporting"
          @click="exportResult"
        >
          <Download :size="14" />
          导出报告
        </button>
      </template>
      <WorkflowSteps :stage="result && !settingsChanged ? 3 : oldFile.table.value && newFile.table.value ? 2 : 1" />
      <ProgressBar class="my-2" :busy="progress.state.busy" :stage="progress.state.stage" :ratio="progress.state.ratio" />
    </PageHeader>

    <div class="workspace flex-1 space-y-4 overflow-auto">
      <!-- 1. 文件选择 -->
      <section class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">1 · 选择要对比的两个文件</h2>
        <div class="workflow-grid grid gap-3">
          <FilePicker
            id="compare-old"
            title="旧版文件"
            :path="oldFile.path.value"
            :file-name="oldFile.name.value"
            :busy="oldFile.loading.value || !!currentJob"
            placeholder="拖放旧版 Excel 到这里"
            @browse="pickOld"
            @clear="oldFile.clear"
            @dropped="(paths) => onDropped('old', paths)"
          />
          <FilePicker
            id="compare-new"
            title="新版文件"
            :path="newFile.path.value"
            :file-name="newFile.name.value"
            :busy="newFile.loading.value || !!currentJob"
            placeholder="拖放新版 Excel 到这里"
            @browse="pickNew"
            @clear="newFile.clear"
            @dropped="(paths) => onDropped('new', paths)"
          />
        </div>

        <div class="workflow-grid mt-3 grid gap-3">
          <FileSettings v-if="oldFile.path.value" :file="oldFile" :disabled="!!currentJob"
            @reload="(detect) => reload('old', detect)" />
          <FileSettings v-if="newFile.path.value" :file="newFile" :disabled="!!currentJob"
            @reload="(detect) => reload('new', detect)" />
        </div>
      </section>

      <!-- 2. 参数配置 -->
      <section v-if="oldFile.path.value && newFile.path.value" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">2 · 匹配字段与比较选项</h2>

        <div class="space-y-4">
          <div>
            <div class="field-label">
              用于匹配记录的字段<span class="ml-1 font-normal text-ink-faint">可选多列组合匹配</span>
            </div>
            <div v-if="suggesting || suggestion" class="recommendation mb-2">
              <p>{{ suggesting ? '正在检查匹配字段…' : suggestion?.reason }}</p>
              <button v-if="suggestion?.keys.length" type="button" class="btn btn-default"
                @click="keys = [...suggestion.keys]">使用 {{ suggestion.keys.join(' + ') }}</button>
            </div>
            <div
              v-if="sharedColumns.length"
              class="max-h-36 space-y-1 overflow-auto rounded-control border border-line px-2.5 py-2"
            >
              <label
                v-for="column in sharedColumns"
                :key="column"
                class="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  :checked="keys.includes(column)"
                  class="accent-primary"
                  @change="toggle(keys, column)"
                />
                <span class="selectable truncate">{{ column }}</span>
              </label>
            </div>
            <p v-else class="rounded-control bg-line-soft/60 px-3 py-2 text-xs text-ink-muted">
              没有同名字段。请检查工作表和表头，或先在 Excel 中统一列名。
            </p>
          </div>

          <details class="advanced">
            <summary>高级比较选项</summary>
            <div class="mt-3 space-y-3">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="ignoreWhitespace" type="checkbox" class="accent-primary" />
              忽略文本首尾空格
            </label>
            <label class="flex items-center gap-2 text-sm">
              <input v-model="ignoreCase" type="checkbox" class="accent-primary" />
              忽略大小写
            </label>

            <label class="flex items-center gap-2 text-sm">
              <input v-model="includeUnchanged" type="checkbox" class="accent-primary" />
              在结果和报告中保留按规则未变化的记录
            </label>
            <div>
              <div class="field-label">按数值比较的字段</div>
              <div class="max-h-24 overflow-auto rounded-control border border-line px-2.5 py-2">
                <label
                  v-for="column in sharedColumns"
                  :key="column"
                  class="flex cursor-pointer items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="numericColumns.includes(column)"
                    class="accent-primary"
                    @change="toggle(numericColumns, column)"
                  />
                  <span class="selectable truncate">{{ column }}</span>
                </label>
                <p v-if="!sharedColumns.length" class="text-xs text-ink-faint">暂无共有字段</p>
              </div>
              <div v-if="numericColumns.length" class="mt-2 flex items-center gap-2">
                <span class="text-xs text-ink-muted">允许误差</span>
                <input v-model="numericTolerance" type="text" class="field !w-28" />
                <span class="text-xs text-ink-faint">例如 0 表示必须完全相等</span>
              </div>
            </div>

            <div>
              <div class="field-label">
                参与比较的字段<span class="ml-1 font-normal text-ink-faint">不选则比较其余全部共有字段</span>
              </div>
              <div class="max-h-24 overflow-auto rounded-control border border-line px-2.5 py-2">
                <label
                  v-for="column in sharedColumns"
                  :key="column"
                  class="flex cursor-pointer items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="compareColumns.includes(column)"
                    class="accent-primary"
                    @change="toggle(compareColumns, column)"
                  />
                  <span class="selectable truncate">{{ column }}</span>
                </label>
                <p v-if="!sharedColumns.length" class="text-xs text-ink-faint">暂无共有字段</p>
              </div>
            </div>
            </div>
          </details>
        </div>
      </section>

      <!-- 3. 数据预览 -->
      <section v-if="oldFile.path.value || newFile.path.value" class="card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">数据预览</h2>
          <div class="flex gap-1 rounded-control bg-line-soft p-0.5">
            <button
              type="button"
              class="rounded-[5px] px-2.5 py-1 text-xs font-medium transition-colors"
              :class="previewSide === 'old' ? 'bg-surface text-ink shadow-card' : 'text-ink-muted'"
              :disabled="!oldFile.path.value"
              @click="previewSide = 'old'"
            >
              旧版
            </button>
            <button
              type="button"
              class="rounded-[5px] px-2.5 py-1 text-xs font-medium transition-colors"
              :class="previewSide === 'new' ? 'bg-surface text-ink shadow-card' : 'text-ink-muted'"
              :disabled="!newFile.path.value"
              @click="previewSide = 'new'"
            >
              新版
            </button>
          </div>
        </div>
        <DataTable
          v-if="previewSide === 'old'"
          class="max-h-[300px]"
          :table="oldFile.table.value"
          :busy="oldFile.loading.value"
          row-number-header="行号"
          empty-text="选择文件后在此预览前 50 行"
          @page="(offset) => oldFile.page(offset).catch((error) => toast.error(messageOf(error)))"
        />
        <DataTable
          v-else
          class="max-h-[300px]"
          :table="newFile.table.value"
          :busy="newFile.loading.value"
          row-number-header="行号"
          empty-text="选择文件后在此预览前 50 行"
          @page="(offset) => newFile.page(offset).catch((error) => toast.error(messageOf(error)))"
        />
      </section>

      <ExportFeedback v-if="exportedPath && !settingsChanged" :path="exportedPath" />

      <!-- 结果 -->
      <section v-if="result" ref="resultsPanel" data-result class="card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">3 · 对比结果</h2>
          <span class="text-2xs text-ink-faint">耗时 {{ result.summary.timings?.total ?? 0 }} 秒</span>
        </div>

        <NoticeList v-if="settingsChanged" class="mb-3" :messages="['下方显示上一次的结果。文件或配置已更改，请重新运行后再导出。']" />
        <div class="stat-grid grid gap-3">
          <StatTile label="新增记录" :value="result.summary.added" tone="success" />
          <StatTile label="删除记录" :value="result.summary.deleted" tone="danger" />
          <StatTile label="实际修改" :value="result.summary.modified_rows" tone="warning" />
          <StatTile label="按规则未变化" :value="result.summary.unchanged" />
          <StatTile label="异常及无法判定" :value="result.summary.anomalies + result.summary.unmatched" tone="danger" />
        </div>
        <p v-if="result.summary.minor_fields" class="mt-2 text-xs text-ink-muted">
          {{ result.summary.minor_rows }} 条记录含细微差异。按严格比较，{{ result.summary.strict_modified_rows }} 条已匹配记录有变化。
        </p>

        <NoticeList
          class="mt-3"
          :messages="[
            ...result.warnings,
            ...(result.summary.only_in_old_columns?.length
              ? [`仅旧版存在：${result.summary.only_in_old_columns.join('、')}`]
              : []),
            ...(result.summary.only_in_new_columns?.length
              ? [`仅新版存在：${result.summary.only_in_new_columns.join('、')}`]
              : []),
          ]"
        />

        <div class="mt-4 flex flex-wrap gap-1 border-b border-line">
          <button
            v-for="tab in tabs.filter((item) => result?.tables[item.key])"
            :key="tab.key"
            type="button"
            class="relative px-3 py-2 text-sm font-medium transition-colors"
            :class="activeTab === tab.key ? 'text-ink' : 'text-ink-muted hover:text-ink'"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
            <span class="ml-1 text-xs tabular-nums text-ink-faint">
              {{ result.tables[tab.key]?.total ?? 0 }}
            </span>
            <span
              v-if="activeTab === tab.key"
              class="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
            />
          </button>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <div class="relative flex-1">
            <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input
              v-model="filterText"
              type="search"
              class="field !pl-7"
              placeholder="在结果中筛选（匹配任意一列即可）"
            />
          </div>
          <span class="shrink-0 text-xs tabular-nums text-ink-faint">
            筛选后 {{ resultTables[activeTab]?.total ?? 0 }} / {{ result.tables[activeTab]?.total ?? 0 }} 行
          </span>
        </div>

        <div class="mt-3 flex max-h-[300px] flex-col">
          <DataTable
            :table="resultTables[activeTab] ?? null"
            :busy="resultBusy"
            :empty-text="
              activeTab === 'anomaly' ? '没有异常记录' : '没有此类差异'
            "
            @page="pageResult"
          />
        </div>
      </section>

      <p v-else class="flex items-center gap-1.5 text-xs text-ink-faint">
        <Search :size="13" />
        选择两个文件并指定匹配字段后，点击右上角“开始对比”。
      </p>
    </div>
  </div>
</template>
