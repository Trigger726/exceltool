<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, Play, Search, X } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import FilePicker from '@/components/FilePicker.vue'
import NoticeList from '@/components/NoticeList.vue'
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
  type TablePage,
} from '@/services/bridge'

const toast = useToast()
const progress = useProgress()

const oldFile = useFileSlot()
const newFile = useFileSlot()

const previewSide = ref<'old' | 'new'>('old')
const keys = ref<string[]>([])
const ignoreWhitespace = ref(true)
const ignoreCase = ref(false)
const numericColumns = ref<string[]>([])
const numericTolerance = ref('0')
const compareColumns = ref<string[]>([])

const result = ref<AnalyzeResponse | null>(null)
const activeTab = ref<'added' | 'deleted' | 'changed' | 'anomaly'>('added')
const resultTables = ref<Record<string, TablePage>>({})
const resultBusy = ref(false)
const exporting = ref(false)
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
  () => Boolean(oldFile.path.value && newFile.path.value && keys.value.length > 0),
)

watch(sharedColumns, (columns) => {
  keys.value = keys.value.filter((key) => columns.includes(key))
  numericColumns.value = numericColumns.value.filter((column) => columns.includes(column))
  compareColumns.value = compareColumns.value.filter((column) => columns.includes(column))
})

function toggle(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

async function pickOld() {
  try {
    const response = await api.chooseFiles('open')
    if (response.paths[0]) await oldFile.setPath(response.paths[0])
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function pickNew() {
  try {
    const response = await api.chooseFiles('open')
    if (response.paths[0]) await newFile.setPath(response.paths[0])
  } catch (error) {
    toast.error(messageOf(error))
  }
}

async function reload(slot: 'old' | 'new') {
  const target = slot === 'old' ? oldFile : newFile
  try {
    await target.refresh()
  } catch (error) {
    toast.error(messageOf(error))
  }
}

function onDropped(side: 'old' | 'new', paths: string[]) {
  const target = side === 'old' ? oldFile : newFile
  const file = paths[0]
  if (!file) return
  target.setPath(file).catch((error) => toast.error(messageOf(error)))
}

function messageOf(error: unknown) {
  if (error instanceof SheetKitError) return error.message
  return '操作失败，请重试'
}

async function run() {
  if (!canRun.value || !oldFile.path.value || !newFile.path.value) return
  resultBusy.value = true
  progress.begin('准备对比')
  const jobId = newJobId()
  currentJob.value = jobId
  try {
    if (result.value) await api.release(result.value.result_id).catch(() => undefined)
    const response = await api.analyze({
      action: 'compare',
      job_id: jobId,
      old_path: oldFile.path.value,
      new_path: newFile.path.value,
      old_sheet: oldFile.sheet.value,
      new_sheet: newFile.sheet.value,
      header_row: oldFile.headerRow.value,
      keys: keys.value,
      options: {
        ignore_whitespace: ignoreWhitespace.value,
        ignore_case: ignoreCase.value,
        numeric_columns: numericColumns.value,
        numeric_tolerance: numericTolerance.value,
        compare_columns: compareColumns.value,
      },
    })
    result.value = response
    resultTables.value = response.preview
    activeTab.value = 'added'
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
  if (!result.value) return
  exporting.value = true
  const jobId = newJobId()
  currentJob.value = jobId
  try {
    const picked = await api.chooseFiles('save', { save_name: '差异对比报告.xlsx' })
    const destination = picked.paths[0]
    if (!destination) return
    const written = await api.export({
      kind: 'compare',
      job_id: jobId,
      result_id: result.value.result_id,
      destination,
    })
    toast.success(`已导出到 ${written.path}`)
  } catch (error) {
    if (error instanceof SheetKitError && error.code === 'E_CANCELLED') {
      toast.info('已取消导出。')
    } else {
      toast.error(messageOf(error))
    }
  } finally {
    currentJob.value = ''
    exporting.value = false
  }
}

async function loadResultPage(offset: number) {
  if (!result.value) return
  resultBusy.value = true
  try {
    const response = await api.page({
      result_id: result.value.result_id,
      table: activeTab.value,
      offset,
      limit: 50,
      filter: filterText.value,
    })
    resultTables.value = { ...resultTables.value, [activeTab.value]: response.table }
  } catch (error) {
    toast.error(messageOf(error))
  } finally {
    resultBusy.value = false
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
] as const

onBeforeUnmount(() => {
  if (result.value) api.release(result.value.result_id).catch(() => undefined)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <PageHeader
      title="表格对比"
      caption="按业务唯一键比对两个版本，找出新增、删除与修改内容。"
    >
      <template #actions>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!resultBusy"
          @click="cancelRun"
        >
          <X :size="14" />
          取消
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!canRun || resultBusy"
          @click="run"
        >
          <Play :size="14" />
          开始对比
        </button>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!result || exporting"
          @click="exportResult"
        >
          <Download :size="14" />
          导出报告
        </button>
      </template>
    </PageHeader>

    <div class="flex-1 space-y-4 overflow-auto px-7 py-5">
      <!-- 1. 文件选择 -->
      <section class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">1 · 选择要对比的两个文件</h2>
        <div class="grid grid-cols-2 gap-3">
          <FilePicker
            id="compare-old"
            title="旧版文件"
            :path="oldFile.path.value"
            :file-name="oldFile.name.value"
            :busy="oldFile.loading.value"
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
            :busy="newFile.loading.value"
            placeholder="拖放新版 Excel 到这里"
            @browse="pickNew"
            @clear="newFile.clear"
            @dropped="(paths) => onDropped('new', paths)"
          />
        </div>

        <div v-if="oldFile.path.value || newFile.path.value" class="mt-3 grid grid-cols-2 gap-3">
          <div v-if="oldFile.path.value" class="rounded-control bg-line-soft/60 px-3 py-2.5">
            <div class="mb-1.5 text-xs font-medium text-ink-muted">旧版设置</div>
            <div class="flex items-center gap-2">
              <select v-model="oldFile.sheet.value" class="field flex-1" @change="reload('old')">
                <option v-for="item in oldFile.profile.value?.sheets ?? []" :key="item.name" :value="item.name">
                  {{ item.name }}
                </option>
              </select>
              <label class="flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-muted">
                表头行
                <input
                  v-model.number="oldFile.headerRow.value"
                  type="number"
                  min="1"
                  class="field !w-16 text-center"
                  @change="reload('old')"
                />
              </label>
            </div>
          </div>
          <div v-if="newFile.path.value" class="rounded-control bg-line-soft/60 px-3 py-2.5">
            <div class="mb-1.5 text-xs font-medium text-ink-muted">新版设置</div>
            <div class="flex items-center gap-2">
              <select v-model="newFile.sheet.value" class="field flex-1" @change="reload('new')">
                <option v-for="item in newFile.profile.value?.sheets ?? []" :key="item.name" :value="item.name">
                  {{ item.name }}
                </option>
              </select>
              <label class="flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-muted">
                表头行
                <input
                  v-model.number="newFile.headerRow.value"
                  type="number"
                  min="1"
                  class="field !w-16 text-center"
                  @change="reload('new')"
                />
              </label>
            </div>
          </div>
        </div>
      </section>

      <!-- 2. 参数配置 -->
      <section class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">2 · 匹配字段与比较选项</h2>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="field-label">
              唯一匹配字段<span class="ml-1 font-normal text-ink-faint">可多选，组合成唯一键</span>
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
              选择两个文件后，这里会列出它们共有的字段。
            </p>
          </div>

          <div class="space-y-3">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="ignoreWhitespace" type="checkbox" class="accent-primary" />
              忽略文本首尾空格
            </label>
            <label class="flex items-center gap-2 text-sm">
              <input v-model="ignoreCase" type="checkbox" class="accent-primary" />
              忽略大小写
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
        </div>
      </section>

      <!-- 3. 数据预览 -->
      <section v-if="oldFile.path.value || newFile.path.value" class="card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">3 · 数据预览</h2>
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
          :table="oldFile.table.value"
          :busy="oldFile.loading.value"
          row-number-header="行号"
          empty-text="选择文件后在此预览前 50 行"
          @page="oldFile.page"
        />
        <DataTable
          v-else
          :table="newFile.table.value"
          :busy="newFile.loading.value"
          row-number-header="行号"
          empty-text="选择文件后在此预览前 50 行"
          @page="newFile.page"
        />
      </section>

      <ProgressBar :busy="progress.state.busy" :stage="progress.state.stage" :ratio="progress.state.ratio" />

      <!-- 4. 处理结果 -->
      <section v-if="result" class="card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">4 · 对比结果</h2>
          <span class="text-2xs text-ink-faint">耗时 {{ result.summary.timings?.total ?? 0 }} 秒</span>
        </div>

        <div class="grid grid-cols-5 gap-3">
          <StatTile label="旧版记录数" :value="result.summary.old_rows" />
          <StatTile label="新版记录数" :value="result.summary.new_rows" />
          <StatTile label="新增" :value="result.summary.added" tone="success" />
          <StatTile label="删除" :value="result.summary.deleted" tone="danger" />
          <StatTile
            label="修改"
            :value="`${result.summary.modified_rows} / ${result.summary.modified_fields}`"
            tone="warning"
          />
        </div>

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

        <div class="mt-4 flex gap-1 border-b border-line">
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

        <div class="mt-3 flex items-center gap-2">
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

        <div class="mt-3 flex h-[300px] flex-col">
          <DataTable
            :table="resultTables[activeTab] ?? null"
            :busy="resultBusy"
            row-number-header="行号"
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
