<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { FileSpreadsheet, FolderOpen, Trash2, Upload } from 'lucide-vue-next'

import { registerDropTarget, setActiveDropTarget } from '@/composables/useDropTarget'

const props = defineProps<{
  id: string
  title: string
  path?: string | null
  fileName?: string | null
  placeholder?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  browse: []
  clear: []
  dropped: [paths: string[]]
}>()

const hovering = ref(false)

let unregister: (() => void) | null = null

onMounted(() => {
  unregister = registerDropTarget(props.id, (paths) => emit('dropped', paths))
})

onBeforeUnmount(() => {
  unregister?.()
})

const fileLabel = computed(() => props.fileName || props.path || '')
</script>

<template>
  <div
    class="card p-3 transition-colors"
    :class="hovering ? 'border-primary bg-primary-soft/40' : ''"
    @mouseenter="setActiveDropTarget(id)"
    @mouseleave="setActiveDropTarget(null)"
    @dragenter.prevent="hovering = true"
    @dragover.prevent="hovering = true"
    @dragleave.prevent="hovering = false"
    @drop.prevent="hovering = false"
  >
    <div class="mb-2 flex items-center justify-between">
      <span class="text-xs font-semibold uppercase tracking-wide text-ink-muted">
        {{ title }}
      </span>
      <button
        v-if="path"
        type="button"
        class="rounded p-1 text-ink-faint transition-colors hover:bg-danger-soft hover:text-danger"
        title="清除"
        @click="emit('clear')"
      >
        <Trash2 :size="14" />
      </button>
    </div>

    <div
      v-if="!path"
      class="flex flex-col items-center justify-center gap-2 rounded-control border border-dashed border-line px-4 py-6 text-center"
    >
      <Upload :size="18" class="text-ink-faint" />
      <div class="text-sm text-ink-muted">{{ placeholder || '拖放文件到这里' }}</div>
      <button type="button" class="btn btn-default" :disabled="busy" @click="emit('browse')">
        <FolderOpen :size="14" />
        选择文件
      </button>
    </div>

    <div v-else class="flex items-center gap-2.5 rounded-control border border-line bg-line-soft/60 px-3 py-2">
      <FileSpreadsheet :size="16" class="shrink-0 text-primary" />
      <div class="min-w-0 flex-1">
        <div class="truncate text-sm font-medium" :title="path">{{ fileLabel }}</div>
        <div v-if="path !== fileLabel" class="truncate text-2xs text-ink-faint" :title="path">
          {{ path }}
        </div>
      </div>
      <button type="button" class="btn btn-ghost !px-2 !py-1" @click="emit('browse')">更换</button>
    </div>
  </div>
</template>
