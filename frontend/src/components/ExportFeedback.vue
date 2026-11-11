<script setup lang="ts">
import { Check, FileSpreadsheet, FolderOpen } from 'lucide-vue-next'
import { api } from '@/services/bridge'
import { useToast } from '@/composables/useToast'

const props = defineProps<{ path: string }>()
const toast = useToast()

async function open(folder: boolean) {
  try {
    await api.openExport(props.path, folder)
  } catch (error) {
    toast.error(error instanceof Error ? error.message : '无法打开导出位置')
  }
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2 rounded-control border border-success/30 bg-success-soft p-3" role="status" data-export-feedback>
    <Check :size="16" class="text-success" />
    <span class="text-sm font-medium text-success">已导出</span>
    <span class="selectable min-w-0 flex-1 break-all text-xs text-ink-muted">{{ path }}</span>
    <button type="button" class="btn btn-default" @click="open(false)"><FileSpreadsheet :size="14" />打开结果</button>
    <button type="button" class="btn btn-default" @click="open(true)"><FolderOpen :size="14" />打开所在文件夹</button>
  </div>
</template>
