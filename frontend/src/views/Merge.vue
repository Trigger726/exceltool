<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { Download, FolderPlus, Play, Plus, Search, Trash2, X } from 'lucide-vue-next'

import DataTable from '@/components/DataTable.vue'
import NoticeList from '@/components/NoticeList.vue'
import PageHeader from '@/components/PageHeader.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import StatTile from '@/components/StatTile.vue'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import {
  api,
  newJobId,
  SheetKitError,
  type AnalyzeResponse,
  type MergePlan,
  type TablePage,
} from '@/services/bridge'

interface SourceItem {
  path: string
  name: string
  sheet: string | null
  headerRow: number
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
const resultTable = ref<TablePage | null>(null)
const busy = ref(false)
const exporting = ref(false)
const mappingDraft = ref<Record<string, string>>({})
const filterText = ref('')
const currentJob = ref('')

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
  const known = new Set(sources.value.map((item) => item.path.toLowerCase()))
  for (const path of paths) {
    if (known.has(path.toLowerCase())) continue
    const response = await api.describe(path)
    const item: SourceItem = {
      path,
      name: response.file.name,
      sheet: response.file.sheets[0]?.name ?? null,
      headerRow: 1,
      enabled: true,
      mapping: {},
      columns: [],
      sheets: response.file.sheets.map((entry) => entry.name),
    }
    sources.value.push(item)
    known.add(path.toLowerCase())
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
  if (!sources.value.length) {
    plan.value = null
    return
  }
  try {
    const response = await api.plan(sources.value.map(payloadOf))
    plan.value = response.plan
    response.plan.sources.forEach((entry, index) => {
      const item = sources.value[index]
      if (item) item.columns = entry.columns
    })
    syncMappingDraft()
  } catch (error) {
    toast.error(messageOf(error))
  }
}

function syncMappingDraft() {
  const item = sources.value[activeIndex.value]
  if (!item) {
    mappingDraft.value = {}
    return
  }
  const draft: Record<string, string> = {}
  for (const column of item.columns) {
    draft[column] = item.mapping[column] || column
  }
  mappingDraft.value = draft
}

function commitMapping() {
  const item = sources.value[activeIndex.value]
  if (!item) return
  const mapping: Record<string, string> = {}
  for (const [column, target] of Object.entries(mappingDraft.value)) {
    const trimmed = (target || '').trim()
    if (trimmed && trimmed !== column) mapping[column] = trimmed
  }
  item.mapping = mapping
  refreshPlan()
}

function selectSource(index: number) {
  activeIndex.value = index
  syncMappingDraft()
}

async function run() {
  if (!sources.value.length) return
  busy.value = true
  progress.begin('准备合并')
  const jobId = newJobId()
  currentJob.value = jobId
  try {
    if (result.value) await api.release(result.value.result_id).catch(() => undefined)
    const response = await api.analyze({
      action: 'merge',
      job_id: jobId,
      sources: sources.value.map(payloadOf),
    })
    result.value = response
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
  if (!result.value) return
  exporting.value = true
  const jobId = newJobId()
  currentJob.value = jobId
  try {
    const picked = await api.chooseFiles('save', { save_name: '合并汇总.xlsx' })
    const destination = picked.paths[0]
    if (!destination) return
    const written = await api.export({
      kind: 'merge',
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
  busy.value = true
  try {
    const response = await api.page({
      result_id: result.value.result_id,
      table: 'merged',
      offset,
      limit: 50,
      filter: filterText.value,
    })
    resultTable.value = response.table
  } catch (error) {
    toast.error(messageOf(error))
  } finally {
    busy.value = false
  }
}

function pageResult(offset: number) {
  return loadResultPage(offset)
}

onBeforeUnmount(() => {
  if (result.value) api.release(result.value.result_id).catch(() => undefined)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <PageHeader title="批量合并" caption="把多个结构相同或相近的表格纵向汇总为一个文件。">
      <template #actions>
        <button type="button" class="btn btn-default" :disabled="!busy" @click="cancelRun">
          <X :size="14" />
          取消
        </button>
        <button type="button" class="btn btn-primary" :disabled="!sources.length || busy" @click="run">
          <Play :size="14" />
          开始合并
        </button>
        <button
          type="button"
          class="btn btn-default"
          :disabled="!result || exporting"
          @click="exportResult"
        >
          <Download :size="14" />
          导出文件
        </button>
      </template>
    </PageHeader>

    <div class="flex-1 space-y-4 overflow-auto px-7 py-5">
      <!-- 1. 文件列表 -->
      <section class="card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">1 · 待合并的文件</h2>
          <div class="flex gap-2">
            <button type="button" class="btn btn-default" @click="addFiles">
              <Plus :size="14" />
              添加文件
            </button>
            <button type="button" class="btn btn-default" @click="addFolder">
              <FolderPlus :size="14" />
              添加文件夹
            </button>
          </div>
        </div>

        <div
          v-if="!sources.length"
          class="rounded-control border border-dashed border-line px-4 py-8 text-center text-sm text-ink-muted"
        >
          点击“添加文件”选择多个 Excel，或直接把文件拖进窗口。
        </div>

        <ul v-else class="space-y-1.5">
          <li
            v-for="(item, index) in sources"
            :key="item.path"
            class="flex items-center gap-2.5 rounded-control border px-3 py-2 transition-colors"
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
              @click.stop
            />
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm font-medium">{{ item.name }}</div>
              <div class="truncate text-2xs text-ink-faint" :title="item.path">{{ item.path }}</div>
            </div>
            <select
              v-model="item.sheet"
              class="field !w-32 !py-1 text-xs"
              @click.stop
              @change="refreshPlan()"
            >
              <option v-for="sheet in item.sheets" :key="sheet" :value="sheet">{{ sheet }}</option>
            </select>
            <label class="flex items-center gap-1 text-xs text-ink-muted" @click.stop>
              表头行
              <input
                v-model.number="item.headerRow"
                type="number"
                min="1"
                class="field !w-14 !py-1 text-center text-xs"
                @change="refreshPlan()"
              />
            </label>
            <button
              type="button"
              class="rounded p-1 text-ink-faint transition-colors hover:bg-danger-soft hover:text-danger"
              @click.stop="removeSource(index)"
            >
              <Trash2 :size="14" />
            </button>
          </li>
        </ul>
      </section>

      <!-- 2. 字段映射 -->
      <section v-if="sources.length" class="card p-4">
        <h2 class="mb-1 text-sm font-semibold">2 · 字段映射</h2>
        <p class="mb-3 text-xs text-ink-muted">
          字段按名称对应，不会按位置硬拼。把左侧改成目标字段名即可，例如
          <span class="font-mono">出货日期 → 发货日期</span>。
        </p>

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
                    @change="commitMapping"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-xs text-ink-faint">正在读取字段…</p>
      </section>

      <!-- 3. 合并预览 -->
      <section v-if="plan" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">3 · 合并结果字段</h2>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="column in plan.target_columns" :key="column" class="chip chip-neutral">
            {{ column }}
          </span>
        </div>
        <NoticeList class="mt-3" :messages="plan.warnings" />
      </section>

      <ProgressBar :busy="progress.state.busy" :stage="progress.state.stage" :ratio="progress.state.ratio" />

      <!-- 4. 处理结果 -->
      <section v-if="result" class="card p-4">
        <h2 class="mb-3 text-sm font-semibold">4 · 合并结果</h2>
        <div class="grid grid-cols-4 gap-3">
          <StatTile label="文件数" :value="result.summary.file_count" />
          <StatTile label="合并后总行数" :value="result.summary.total_rows" tone="primary" />
          <StatTile label="目标字段数" :value="result.summary.total_columns" />
          <StatTile label="耗时(秒)" :value="result.summary.timings?.total ?? 0" />
        </div>

        <div class="mt-3 flex items-center gap-2">
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

        <div class="mt-4 flex h-[320px] flex-col">
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
