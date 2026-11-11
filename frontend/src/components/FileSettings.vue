<script setup lang="ts">
import type { useFileSlot } from '@/composables/useFileSlot'
import NoticeList from './NoticeList.vue'

const props = defineProps<{ file: ReturnType<typeof useFileSlot>; disabled?: boolean }>()
const emit = defineEmits<{ reload: [detect: boolean] }>()
const { sheet, headerRow, loading, profile, headerHint, table } = props.file
</script>

<template>
  <div class="mt-3 space-y-2">
    <div class="grid grid-cols-[minmax(0,1fr)_5rem] gap-2">
      <label class="min-w-0">
        <span class="field-label">工作表</span>
        <select v-model="sheet" class="field" :disabled="disabled || loading" @change="emit('reload', true)">
          <option v-for="item in profile?.sheets ?? []" :key="item.name" :value="item.name">{{ item.name }}</option>
          <option v-if="!profile?.sheets.length" :value="null">CSV 数据</option>
        </select>
      </label>
      <label>
        <span class="field-label">表头行</span>
        <input v-model.number="headerRow" type="number" min="1" max="10000" class="field"
          :disabled="disabled || loading" @change="emit('reload', false)" />
      </label>
    </div>
    <p v-if="headerHint" class="text-xs text-ink-muted">
      {{ headerHint.row ? `推荐第 ${headerHint.row} 行。 ` : '' }}{{ headerHint.reason }}
    </p>
    <NoticeList :messages="[...new Set([...(profile?.warnings ?? []), ...(table?.warnings ?? [])])]" />
  </div>
</template>
