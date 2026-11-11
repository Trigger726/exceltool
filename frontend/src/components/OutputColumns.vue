<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, ArrowUp } from 'lucide-vue-next'
import TemplateControls from './TemplateControls.vue'
import { useToast } from '@/composables/useToast'
import type { TemplateRule } from '@/services/bridge'

const props = defineProps<{ columns: string[] }>()
const selection = defineModel<string[] | null>({ required: true })
const toast = useToast()
const chosen = computed(() => selection.value ?? props.columns)
const available = computed(() => props.columns.filter((column) => !chosen.value.includes(column)))

function move(index: number, by: number) {
  const next = [...chosen.value]
  const [column] = next.splice(index, 1)
  next.splice(index + by, 0, column)
  selection.value = next
}

function add(event: Event) {
  const select = event.target as HTMLSelectElement
  if (select.value) selection.value = [...chosen.value, select.value]
  select.value = ''
}

function apply(rule: TemplateRule) {
  if (!Array.isArray(rule)) return
  const missing = rule.filter((column) => !props.columns.includes(column))
  if (missing.length) {
    toast.error(`模板需要以下列，请先检查表头或更换模板：${missing.join('、')}`)
    return
  }
  selection.value = [...rule]
}
</script>

<template>
  <details class="advanced mt-3">
    <summary>设置导出列（已选 {{ chosen.length }} / {{ columns.length }}）</summary>
    <div class="mt-2 space-y-2">
      <p class="text-xs text-ink-muted">按下列顺序导出业务列，异常标记和原始行号随报告保留。</p>
      <ol class="max-h-44 divide-y divide-line overflow-auto rounded-control border border-line">
        <li v-for="(column, index) in chosen" :key="column" class="flex items-center gap-1 px-2 py-1">
          <span class="min-w-0 flex-1 truncate text-sm" :title="column">{{ column }}</span>
          <button type="button" class="btn btn-ghost" :disabled="index === 0" :aria-label="`上移 ${column}`"
            @click="move(index, -1)"><ArrowUp :size="14" /></button>
          <button type="button" class="btn btn-ghost" :disabled="index + 1 === chosen.length" :aria-label="`下移 ${column}`"
            @click="move(index, 1)"><ArrowDown :size="14" /></button>
          <button type="button" class="btn btn-ghost" @click="selection = chosen.filter((name) => name !== column)">移除</button>
        </li>
      </ol>
      <div class="flex flex-wrap items-center gap-2">
        <select v-if="available.length" class="field !w-auto max-w-full" aria-label="添加输出列" @change="add">
          <option value="">添加输出列</option>
          <option v-for="column in available" :key="column" :value="column">{{ column }}</option>
        </select>
        <button v-if="selection" type="button" class="btn btn-ghost" @click="selection = null">恢复所有列</button>
      </div>
      <TemplateControls kind="clean" :rule="chosen.length ? chosen : null" @apply="apply" />
    </div>
  </details>
</template>
