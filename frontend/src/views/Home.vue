<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Columns3, Combine, Sparkles } from 'lucide-vue-next'

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
    <header class="shrink-0 border-b border-line bg-surface px-7 pb-4 pt-6">
      <h1 class="text-lg font-semibold tracking-tight">SheetKit 表格效率助手</h1>
      <p class="mt-0.5 text-sm text-ink-muted">
        全部处理都在本机完成，文件不会上传，也不需要安装服务器。
      </p>
    </header>

    <div class="flex-1 px-7 py-6">
      <div class="grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-3">
        <button
          v-for="feature in features"
          :key="feature.to"
          type="button"
          class="card group flex flex-col items-start gap-3 p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-pop"
          @click="router.push(feature.to)"
        >
          <span
            class="grid h-10 w-10 place-items-center rounded-control"
            :class="feature.accent"
          >
            <component :is="feature.icon" :size="19" :stroke-width="1.8" />
          </span>
          <span class="text-sm font-semibold">{{ feature.title }}</span>
          <span class="text-xs leading-relaxed text-ink-muted">{{ feature.description }}</span>
          <span
            class="mt-auto pt-2 text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100"
          >
            开始处理 →
          </span>
        </button>
      </div>

      <div class="card mt-6 max-w-4xl px-5 py-4">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">
          使用须知
        </h2>
        <ul class="mt-2 space-y-1.5 text-xs leading-relaxed text-ink-muted">
          <li>· 所有文件只在本机读取，SheetKit 不会上传或保存你的表格内容。</li>
          <li>· 处理结果一律另存为新文件，原始文件不会被修改。</li>
          <li>· 支持 .xlsx / .xlsm / .csv；旧版 .xls 与 WPS 专有 .et 请先另存为 .xlsx。</li>
        </ul>
      </div>
    </div>
  </div>
</template>
