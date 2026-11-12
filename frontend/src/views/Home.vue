<script setup lang="ts">
import { Brush, ChevronRight, LaptopMinimal, Layers, Scale, Table2 } from 'lucide-vue-next'

const features = [
  {
    to: '/compare',
    icon: Scale,
    title: '表格对比',
    description: '查找两个版本之间新增、删除和修改的内容。',
  },
  {
    to: '/merge',
    icon: Layers,
    title: '批量合并',
    description: '将多个表格纵向汇总为一个文件。',
  },
  {
    to: '/clean',
    icon: Brush,
    title: '数据清洗',
    description: '处理重复、空值与格式问题。',
  },
]
</script>

<template>
  <div class="home-view">
    <div class="home-content">
      <header class="home-intro">
        <h1 class="home-title font-display">
          <Table2 class="home-mark text-brand" :stroke-width="1.6" aria-hidden="true" />
          <span>想怎么处理表格？</span>
        </h1>
        <p>选择一项工具，开始处理 Excel 或 CSV 文件。</p>
      </header>

      <nav class="home-tools" aria-label="表格工具">
        <RouterLink
          v-for="feature in features"
          :key="feature.to"
          :to="feature.to"
          class="home-tool"
        >
          <span class="home-tool-icon" aria-hidden="true">
            <component :is="feature.icon" :stroke-width="1.6" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="home-tool-title font-display">{{ feature.title }}</span>
            <span class="home-tool-description">{{ feature.description }}</span>
          </span>
          <ChevronRight :size="18" :stroke-width="1.6" class="shrink-0 text-ink-muted" aria-hidden="true" />
        </RouterLink>
      </nav>

      <p class="home-note">
        <LaptopMinimal :size="17" :stroke-width="1.6" aria-hidden="true" />
        文件在本机处理。
      </p>
    </div>
  </div>
</template>
