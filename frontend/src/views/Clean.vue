<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Download, Play, Search, TriangleAlert, X } from 'lucide-vue-next'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ExportFeedback from '@/components/ExportFeedback.vue'
import DataTable from '@/components/DataTable.vue'
import FileSettings from '@/components/FileSettings.vue'
import FilePicker from '@/components/FilePicker.vue'
import OutputColumns from '@/components/OutputColumns.vue'
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
  type CleanSuggestion,
  type TablePage,
} from '@/services/bridge'

const toast = useToast()
const progress = useProgress()
const file = useFileSlot()
const suggestion = ref<CleanSuggestion | null>(null)
const suggestionText = computed(() => {
  const s = suggestion.value
  if (!s) return ''
  return [
    [s.strip_columns, '清理空格'], [s.duplicate_key_columns, '检查重复'],
    [s.date_columns, '检查日期'], [s.number_columns, '检查数字'],
  ].filter(([columns]) => columns.length).map(([columns, label]) =>
    `${label}（${(columns as string[]).join('、')}）`).join('，')
})

watch(file.columns, async (columns, _previous, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  suggestion.value = null
  for (const list of [stripColumns, duplicateKeyColumns, requiredColumns, dateColumns, numberColumns]) {
    list.value = list.value.filter((column) => columns.includes(column))
  }
  if (!columns.length) return
  try {
    const response = await api.recommendClean(file.source())
    if (!stale) suggestion.value = response
  } catch (error) {
    if (!stale) toast.error(messageOf(error))
  }
})

function resetRules() {
  removeBlankRows.value = true
  duplicateAction.value = 'mark'
  for (const list of [stripColumns, duplicateKeyColumns, requiredColumns, dateColumns, numberColumns]) list.value = []
}

function applySuggestion() {
  if (!suggestion.value) return
  stripColumns.value = [...suggestion.value.strip_columns]
  duplicateKeyColumns.value = [...suggestion.value.duplicate_key_columns]
  dateColumns.value = [...suggestion.value.date_columns]
  numberColumns.value = [...suggestion.value.number_columns]
  duplicateAction.value = 'mark'
}

const removeBlankRows = ref(true)
const stripColumns = ref<string[]>([])
const duplicateAction = ref<'none' | 'mark' | 'keep_first' | 'remove_all'>('mark')
const duplicateKeyColumns = ref<string[]>([])
const requiredColumns = ref<string[]>([])
const dateColumns = ref<string[]>([])
const numberColumns = ref<string[]>([])

const result = ref<AnalyzeResponse | null>(null)
const resultsPanel = ref<HTMLElement | null>(null)
const completedConfig = ref('')
const configuration = computed(() => JSON.stringify([file.source(), buildOptions()]))
const settingsChanged = computed(() => !!result.value && completedConfig.value !== configuration.value)
let disposed = false
const resultTables = ref<Record<string, TablePage>>({})
const activeTab = ref<'cleaned' | 'duplicates' | 'anomalies'>('cleaned')
const busy = ref(false)
const exporting = ref(false)
const exportedPath = ref('')
const outputColumns = ref<string[] | null>(null)
const impact = ref<Record<string, any> | null>(null)
const confirmOpen = ref(false)
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

const isDestructive = computed(
  () => duplicateAction.value === 'keep_first' || duplicateAction.value === 'remove_all',
)

const canRun = computed(() => Boolean(file.table.value && !file.loading.value))

function toggle(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

function messageOf(error: unknown) {
  if (error instanceof SheetKitError) return error.message
  return '操作失败，请重试'
}

function buildOptions(confirmed = false) {
  return {
    remove_blank_rows: removeBlankRows.value,
    strip_columns: stripColumns.value,
    duplicate_action: duplicateAction.value,
    duplicate_key_columns: duplicateKeyColumns.value,
    required_columns: requiredColumns.value,
    date_columns: dateColumns.value,
    number_columns: numberColumns.value,
    confirmed,
  }
}

async function pickFile() {
  try {
    const response = await api.chooseFiles('open')
    if (response.paths[0]) await file.setPath(response.paths[0])
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function reload(detect: boolean) {
  try {
    await file.refresh(detect)
  } catch (error) {
    toast.error(messageOf(error))
  }
}

function onDropped(paths: string[]) {
  if (currentJob.value) return
  const target = paths[0]
  if (!target) return
  file.setPath(target).catch((error) => toast.error(messageOf(error)))
}

async function refreshImpact() {
  const request = ++impactRequest
  impact.value = null
  if (!file.path.value || !isDestructive.value) {
    impact.value = null
    return
  }
  try {
    const response = await api.impact({
      path: file.path.value,
      sheet: file.sheet.value,
      header_row: file.headerRow.value,
      options: buildOptions(),
    })
    if (request === impactRequest) impact.value = response.impact
  } catch (error) {
    if (request !== impactRequest) return
    impact.value = null
    toast.error(messageOf(error))
  }
}

let impactRequest = 0
watch([duplicateAction, duplicateKeyColumns, stripColumns, removeBlankRows, file.columns], () => {
  refreshImpact()
}, { deep: true })

async function run(confirmed = false) {
  if (!canRun.value || currentJob.value || !file.path.value) return
  busy.value = true
  progress.begin('准备清洗')
  const jobId = newJobId()
  currentJob.value = jobId
  const configurationAtStart = configuration.value
  try {
    const response = await api.analyze({
      action: 'clean',
      job_id: jobId,
      path: file.path.value,
      sheet: file.sheet.value,
      header_row: file.headerRow.value,
      options: buildOptions(confirmed),
    })
    if (disposed) {
      await api.release(response.result_id)
      return
    }
    if (result.value) void api.release(result.value.result_id).catch(() => undefined)
    exportedPath.value = ''
    const columns: string[] = response.summary.body_columns
    if (outputColumns.value?.some((name) => !columns.includes(name))) {
      toast.info('新结果缺少上次所选的列，已恢复为导出所有列。')
      outputColumns.value = null
    }
    completedConfig.value = configurationAtStart
    result.value = response
    void nextTick(() => resultsPanel.value?.scrollIntoView({ block: 'start' }))
    resultTables.value = response.preview
    activeTab.value = 'cleaned'
    confirmOpen.value = false
    filterText.value = ''
    toast.success('清洗完成。')
  } catch (error) {
    if (error instanceof SheetKitError && error.code === 'E_CONFIRMATION_REQUIRED') {
      impactRequest++
      impact.value = (error.context?.impact as Record<string, any>) ?? null
      confirmOpen.value = true
    } else if (error instanceof SheetKitError && error.code === 'E_CANCELLED') {
      toast.info('已取消本次清洗。')
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
    const picked = await api.chooseFiles('save', { save_name: '数据清洗结果.xlsx' })
    const destination = picked.paths[0]
    if (!destination || disposed) return
    const jobId = newJobId()
    currentJob.value = jobId
    progress.begin('正在导出 Excel')
    const written = await api.export({
      kind: 'clean',
      job_id: jobId,
      result_id: result.value.result_id,
      destination,
      output_columns: outputColumns.value,
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
  const tab = activeTab.value
  busy.value = true
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
    if (request === pageRequest && !currentJob.value) busy.value = false
  }
}

function pageResult(offset: number) {
  return loadResultPage(offset)
}

const tabs = [
  { key: 'cleaned', label: '清洗结果' },
  { key: 'duplicates', label: '重复数据' },
  { key: 'anomalies', label: '异常数据' },
] as const

const impactDetails = computed(() => {
  if (!impact.value) return []
  const removes =
    duplicateAction.value === 'keep_first'
      ? impact.value.keep_first_removes
      : impact.value.remove_all_removes
  return [
    { label: '重复组数', value: impact.value.groups },
    { label: '涉及重复的记录数', value: impact.value.rows_in_groups },
    { label: '将被删除的行数', value: removes },
    { label: '处理后剩余行数', value: impact.value.result_rows?.[duplicateAction.value] },
  ]
})

onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(filterTimer)
  if (currentJob.value) void cancelRun()
  if (result.value) api.release(result.value.result_id).catch(() => undefined)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <PageHeader title="数据清洗" caption="检测并处理重复、空值与格式问题。">
      <template #actions>
        <button type="button" class="btn btn-default" :disabled="!currentJob" @click="cancelRun">
          <X :size="14" />
          取消
        </button>
        <button type="button" class="btn btn-primary" :disabled="!canRun || !!currentJob || exporting" @click="run(false)">
          <Play :size="14" />
          开始清洗
        </button>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!result || settingsChanged || !!currentJob || exporting || outputColumns?.length === 0"
          @click="exportResult"
        >
          <Download :size="14" />
          导出文件
        </button>
      </template>
      <WorkflowSteps :stage="result && !settingsChanged ? 3 : file.table.value ? 2 : 1" />
      <ProgressBar class="my-2" :busy="progress.state.busy" :stage="progress.state.stage" :ratio="progress.state.ratio" />
    </PageHeader>

    <div class="workspace flex-1 space-y-4 overflow-auto">
      <!-- 1. 文件选择 -->
      <section class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">1 · 选择要清洗的文件</h2>
        <div class="workflow-grid grid items-start gap-3">
          <FilePicker
            id="clean-file"
            title="待清洗文件"
            :path="file.path.value"
            :file-name="file.name.value"
            :busy="file.loading.value || !!currentJob"
            placeholder="拖放 Excel 到这里"
            @browse="pickFile"
            @clear="file.clear"
            @dropped="onDropped"
          />
          <FileSettings v-if="file.path.value" :file="file" :disabled="!!currentJob" @reload="reload" />
        </div>
      </section>

      <!-- 2. 清洗规则 -->
      <section v-if="file.path.value" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">2 · 清洗规则</h2>
        <div v-if="suggestion" class="recommendation mb-3">
          <p>{{ suggestionText || '抽查前 500 条记录后，暂无额外规则建议。' }}</p>
          <button v-if="suggestionText" type="button" class="btn btn-default" @click="applySuggestion">应用推荐</button>
          <button type="button" class="btn btn-ghost" @click="resetRules">恢复默认</button>
        </div>

        <label class="flex items-center gap-2 text-sm">
          <input v-model="removeBlankRows" type="checkbox" class="accent-primary" />
          删除完全空白行
        </label>

        <details class="advanced mt-3">
          <summary>调整清洗规则</summary>
        <div class="workflow-grid mt-4 grid gap-4">
          <div>
            <div class="field-label">清理首尾空格的字段</div>
            <div class="max-h-40 overflow-auto rounded-control border border-line px-2.5 py-2">
              <label
                v-for="column in file.columns.value"
                :key="column"
                class="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  :checked="stripColumns.includes(column)"
                  class="accent-primary"
                  @change="toggle(stripColumns, column)"
                />
                <span class="selectable truncate">{{ column }}</span>
              </label>
              <p v-if="!file.columns.value.length" class="text-xs text-ink-faint">选择文件后在此选择字段</p>
            </div>
          </div>

          <div class="space-y-3">
            <div>
              <div class="field-label">重复数据处理方式</div>
              <div class="space-y-1.5 rounded-control border border-line px-2.5 py-2">
                <label class="flex items-center gap-2 text-sm">
                  <input v-model="duplicateAction" type="radio" value="none" class="accent-primary" />
                  不检查重复
                </label>
                <label class="flex items-center gap-2 text-sm">
                  <input v-model="duplicateAction" type="radio" value="mark" class="accent-primary" />
                  仅标记重复数据
                </label>
                <label class="flex items-center gap-2 text-sm">
                  <input v-model="duplicateAction" type="radio" value="keep_first" class="accent-primary" />
                  删除重复项（保留首次出现）
                </label>
                <label class="flex items-center gap-2 text-sm">
                  <input v-model="duplicateAction" type="radio" value="remove_all" class="accent-primary" />
                  删除整组重复数据
                </label>
              </div>
            </div>

            <div v-if="duplicateAction !== 'none'">
              <div class="field-label">
                重复判断字段
                <span class="ml-1 font-normal text-ink-faint">不选则判断完全相同的整行</span>
              </div>
              <div class="max-h-32 overflow-auto rounded-control border border-line px-2.5 py-2">
                <label
                  v-for="column in file.columns.value"
                  :key="column"
                  class="flex cursor-pointer items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="duplicateKeyColumns.includes(column)"
                    class="accent-primary"
                    @change="toggle(duplicateKeyColumns, column)"
                  />
                  <span class="selectable truncate">{{ column }}</span>
                </label>
                <p v-if="!file.columns.value.length" class="text-xs text-ink-faint">选择文件后在此选择字段</p>
              </div>
            </div>
          </div>
        </div>

        <div class="workflow-grid mt-4 grid gap-4">
          <div>
            <div class="field-label">必填字段<span class="ml-1 font-normal text-ink-faint">缺失时标记</span></div>
            <div class="max-h-32 overflow-auto rounded-control border border-line px-2.5 py-2">
              <label
                v-for="column in file.columns.value"
                :key="column"
                class="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  :checked="requiredColumns.includes(column)"
                  class="accent-primary"
                  @change="toggle(requiredColumns, column)"
                />
                <span class="selectable truncate">{{ column }}</span>
              </label>
            </div>
          </div>
          <div>
            <div class="field-label">日期检查字段</div>
            <div class="max-h-32 overflow-auto rounded-control border border-line px-2.5 py-2">
              <label
                v-for="column in file.columns.value"
                :key="column"
                class="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  :checked="dateColumns.includes(column)"
                  class="accent-primary"
                  @change="toggle(dateColumns, column)"
                />
                <span class="selectable truncate">{{ column }}</span>
              </label>
            </div>
          </div>
          <div>
            <div class="field-label">数字检查字段</div>
            <div class="max-h-32 overflow-auto rounded-control border border-line px-2.5 py-2">
              <label
                v-for="column in file.columns.value"
                :key="column"
                class="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  :checked="numberColumns.includes(column)"
                  class="accent-primary"
                  @change="toggle(numberColumns, column)"
                />
                <span class="selectable truncate">{{ column }}</span>
              </label>
            </div>
          </div>
        </div>

        </details>
        <div
          v-if="isDestructive && impact"
          class="mt-4 rounded-control border border-warning/40 bg-warning-soft px-3 py-2.5"
        >
          <div class="flex items-center gap-1.5 text-xs font-medium text-warning">
            <TriangleAlert :size="13" />
            删除重复数据的影响预览
          </div>
          <dl class="mt-1.5 grid grid-cols-4 gap-2 text-xs text-warning">
            <div v-for="item in impactDetails" :key="item.label">
              <dt class="opacity-80">{{ item.label }}</dt>
              <dd class="font-semibold tabular-nums">{{ item.value }}</dd>
            </div>
          </dl>
          <p class="mt-1.5 text-2xs text-warning/90">
            删除前仍会再次确认，原始文件不会被修改。
          </p>
        </div>
      </section>

      <!-- 3. 数据预览 -->
      <section v-if="file.path.value" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">数据预览</h2>
        <DataTable
          class="max-h-[300px]"
          :table="file.table.value"
          :busy="file.loading.value"
          row-number-header="行号"
          empty-text="选择文件后在此预览前 50 行"
          @page="(offset) => file.page(offset).catch((error) => toast.error(messageOf(error)))"
        />
      </section>

      <ExportFeedback v-if="exportedPath && !settingsChanged" :path="exportedPath" />

      <!-- 结果 -->
      <section v-if="result" ref="resultsPanel" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">3 · 清洗结果</h2>
        <NoticeList v-if="settingsChanged" class="mb-3" :messages="['下方显示上一次的结果。文件或配置已更改，请重新运行后再导出。']" />
        <div class="stat-grid grid gap-3">
          <StatTile label="原始记录数" :value="result.summary.original_rows" />
          <StatTile label="处理后记录数" :value="result.summary.result_rows" tone="primary" />
          <StatTile label="空白行" :value="result.summary.blank_rows" />
          <StatTile label="重复记录" :value="result.summary.duplicate_rows" tone="warning" />
          <StatTile label="必填缺失" :value="result.summary.missing_required_rows" tone="danger" />
          <StatTile label="格式异常" :value="result.summary.format_anomaly_rows" tone="danger" />
        </div>

        <NoticeList class="mt-3" :messages="result.warnings" />
        <OutputColumns v-model="outputColumns" :columns="result.summary.body_columns" />
        <p class="mt-3 text-xs text-ink-muted">浅黄表示重复，浅红表示必填缺失或格式异常。详情见表格标记列。</p>

        <div class="mt-4 flex flex-wrap gap-1 border-b border-line">
          <button
            v-for="tab in tabs"
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
            :busy="busy"
            empty-text="没有此类数据"
            @page="pageResult"
          />
        </div>
      </section>
    </div>

    <ConfirmDialog
      :open="confirmOpen"
      title="确认删除重复数据？"
      :message="`该操作会从结果中删除 ${impactDetails.find((item) => item.label === '将被删除的行数')?.value ?? 0} 行数据。此操作不可撤销，但不会修改你的原始文件。`"
      :details="impactDetails"
      confirm-text="确认删除"
      :busy="busy"
      @cancel="confirmOpen = false"
      @confirm="run(true)"
    />
  </div>
</template>
