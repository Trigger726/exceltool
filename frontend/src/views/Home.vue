<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ChevronRight, Columns3, Combine, Sparkles } from 'lucide-vue-next'

const router = useRouter()

const features = [
  {
    to: '/compare',
    icon: Columns3,
    title: '表格对比',
    description: '对比两个版本的 Excel，自动识别新增、删除和修改内容。',
    accent: 'text-primary bg-primary-soft',
  },
  {
    to: '/merge',
    icon: Combine,
    title: '批量合并',
    description: '将多个 Excel 文件快速汇总为一个文件。',
    accent: 'text-success bg-success-soft',
  },
  {
    to: '/clean',
    icon: Sparkles,
    title: '数据清洗',
    description: '检测和处理重复、空值及格式问题。',
    accent: 'text-warning bg-warning-soft',
  },
]
</script>

<template>
  <div class="flex h-full flex-col overflow-auto">
    <div class="workspace">
      <div class="mb-7 mt-5">
        <h1 class="text-2xl font-semibold tracking-tight">SheetKit 表格效率助手</h1>
        <p class="mt-2 text-sm text-ink-muted">选择要完成的工作。支持 Excel 和 CSV，文件在本机处理。</p>
      </div>
      <div class="card max-w-3xl divide-y divide-line">
        <button
          v-for="feature in features"
          :key="feature.to"
          type="button"
          class="flex w-full items-center gap-4 px-4 py-4 text-left hover:bg-line-soft"
          @click="router.push(feature.to)"
        >
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-control" :class="feature.accent">
            <component :is="feature.icon" :size="19" :stroke-width="1.8" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block font-semibold">{{ feature.title }}</span>
            <span class="mt-1 block text-xs text-ink-muted">{{ feature.description }}</span>
          </span>
          <ChevronRight :size="17" class="shrink-0 text-ink-muted" aria-hidden="true" />
        </button>
      </div>
      <p class="mt-4 text-xs text-ink-muted">结果另存为 Excel 文件，原始文件保持原样。</p>
    </div>
  </div>
</template>
