<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { FileSpreadsheet, FileUp, Trash2 } from 'lucide-vue-next'

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
  unregister = registerDropTarget(props.id, (paths) => { if (!props.busy) emit('dropped', paths) })
})

onBeforeUnmount(() => {
  unregister?.()
})

const fileLabel = computed(() => props.fileName || props.path || '')
</script>

<template>
  <div
    class="file-picker p-4 transition-colors"
    :class="[
      path ? 'rounded-card border border-line bg-canvas' : 'drop-surface',
      hovering && '!border-primary !bg-primary-soft',
    ]"
    @mouseenter="setActiveDropTarget(id)"
    @mouseleave="setActiveDropTarget(null)"
    @dragenter.prevent="setActiveDropTarget(id); hovering = true"
    @dragover.prevent="setActiveDropTarget(id); hovering = true"
    @dragleave.prevent="hovering = false"
    @drop.prevent="hovering = false"
  >
    <div class="mb-2 flex items-center justify-between">
      <span class="file-picker-title font-semibold text-ink">
        {{ title }}
      </span>
      <button
        v-if="path"
        type="button"
        class="rounded p-1 text-ink-faint transition-colors hover:bg-danger-soft hover:text-danger"
        title="清除文件"
        :disabled="busy"
        @click="emit('clear')"
      >
        <Trash2 :size="14" />
      </button>
    </div>

    <div
      v-if="!path"
      class="flex flex-col items-center justify-center gap-3 px-2 py-[clamp(12px,2vw,28px)] text-center"
    >
      <FileUp class="size-[clamp(30px,3.7vw,54px)] text-ink-muted" :stroke-width="1.5" aria-hidden="true" />
      <div class="file-picker-hint text-ink-muted">{{ placeholder || '拖放文件到这里' }}</div>
      <button type="button" class="btn btn-surface" :disabled="busy" @click="emit('browse')">
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
      <button type="button" class="btn btn-ghost !px-2 !py-1" :disabled="busy" @click="emit('browse')">更换</button>
    </div>
  </div>
</template>
