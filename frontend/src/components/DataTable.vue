<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight, Inbox, Loader2 } from 'lucide-vue-next'

import type { TablePage } from '@/services/bridge'

const props = defineProps<{
  table: TablePage | null
  busy?: boolean
  emptyText?: string
  /** Shown in the left-most column, e.g. the source row number. */
  rowNumberHeader?: string
}>()

const emit = defineEmits<{
  page: [offset: number]
}>()

const columns = computed(() => props.table?.columns ?? [])
const rows = computed(() => props.table?.rows ?? [])
const total = computed(() => props.table?.total ?? 0)
const offset = computed(() => props.table?.offset ?? 0)
const limit = computed(() => props.table?.limit ?? 50)
const pageIndex = computed(() => (total.value ? Math.floor(offset.value / limit.value) + 1 : 0))
const pageCount = computed(() => (total.value ? Math.ceil(total.value / limit.value) : 0))
const hasPrev = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + limit.value < total.value)

const rowNumbers = computed(() => props.table?.row_numbers ?? [])

function columnClass(index: number) {
  return index === 0 ? 'text-left' : 'text-left'
}
</script>

<template>
  <div class="card flex min-h-0 flex-1 flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b border-line-soft px-3 py-2">
      <div class="text-xs font-medium text-ink-muted">
        <span v-if="busy" class="inline-flex items-center gap-1.5">
          <Loader2 :size="12" class="animate-spin" />
          正在加载…
        </span>
        <span v-else-if="total">共 {{ total.toLocaleString() }} 行</span>
        <span v-else>暂无数据</span>
      </div>
      <div v-if="total" class="flex items-center gap-1.5 text-xs text-ink-muted">
        <button
          type="button"
          class="btn btn-ghost !h-7 !w-7 !p-0"
          :disabled="!hasPrev || busy"
          title="上一页"
          @click="emit('page', Math.max(0, offset - limit))"
        >
          <ChevronLeft :size="15" />
        </button>
        <span class="tabular-nums">{{ pageIndex }} / {{ pageCount }}</span>
        <button
          type="button"
          class="btn btn-ghost !h-7 !w-7 !p-0"
          :disabled="!hasNext || busy"
          title="下一页"
          @click="emit('page', offset + limit)"
        >
          <ChevronRight :size="15" />
        </button>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-auto">
      <table v-if="rows.length" class="w-full border-collapse text-sm">
        <thead class="sticky top-0 z-10 bg-line-soft/95 backdrop-blur">
          <tr>
            <th
              v-if="rowNumberHeader"
              class="whitespace-nowrap border-b border-line px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wide text-ink-muted"
            >
              {{ rowNumberHeader }}
            </th>
            <th
              v-for="(column, index) in columns"
              :key="`${column}-${index}`"
              class="whitespace-nowrap border-b border-line px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wide text-ink-muted"
              :class="columnClass(index)"
            >
              {{ column }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, rowIndex) in rows"
            :key="rowIndex"
            class="border-b border-line-soft last:border-0 hover:bg-line-soft/50"
          >
            <td
              v-if="rowNumberHeader"
              class="whitespace-nowrap px-3 py-1.5 align-top text-2xs tabular-nums text-ink-faint"
            >
              {{ rowNumbers[rowIndex] ?? '' }}
            </td>
            <td
              v-for="(cell, cellIndex) in row"
              :key="cellIndex"
              class="selectable max-w-[320px] truncate px-3 py-1.5 align-top"
              :class="cellIndex === 0 ? 'font-medium' : 'text-ink-muted'"
              :title="cell"
            >
              {{ cell }}
            </td>
          </tr>
        </tbody>
      </table>

      <div
        v-else
        class="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 text-ink-faint"
      >
        <Loader2 v-if="busy" :size="20" class="animate-spin" />
        <Inbox v-else :size="20" />
        <span class="text-sm">{{ busy ? '正在加载…' : emptyText || '没有数据' }}</span>
      </div>
    </div>
  </div>
</template>
