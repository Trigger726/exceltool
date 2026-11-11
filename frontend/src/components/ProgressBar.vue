<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  busy: boolean
  stage?: string
  ratio?: number
}>()

const percent = computed(() => Math.round(Math.min(1, Math.max(0, props.ratio ?? 0)) * 100))
</script>

<template>
  <div
    v-if="busy"
    class="flex items-center gap-2.5 rounded-control border border-line bg-surface px-3 py-2"
  >
    <Loader2 :size="14" class="shrink-0 animate-spin text-primary" />
    <span class="shrink-0 text-xs text-ink-muted">{{ stage || '正在处理…' }}</span>
    <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-line-soft">
      <div
        class="h-full rounded-full bg-primary transition-[width] duration-200"
        :style="{ width: `${percent}%` }"
      />
    </div>
    <span class="w-9 shrink-0 text-right text-2xs tabular-nums text-ink-faint">
      {{ percent }}%
    </span>
  </div>
</template>
