<script setup lang="ts">
import {
  Brush,
  House,
  Layers,
  Moon,
  Scale,
  Sun,
  Table2,
} from 'lucide-vue-next'

import { useTheme } from '@/composables/useTheme'

const { theme, toggle } = useTheme()

const items = [
  { to: '/', label: '首页', icon: House },
  { to: '/compare', label: '表格对比', icon: Scale },
  { to: '/merge', label: '批量合并', icon: Layers },
  { to: '/clean', label: '数据清洗', icon: Brush },
]
</script>

<template>
  <aside class="app-sidebar">
    <div class="sidebar-brand font-display" aria-label="SheetKit">
      <Table2 class="shrink-0 text-brand" :size="27" :stroke-width="1.7" aria-hidden="true" />
      <span class="sidebar-label">SheetKit</span>
    </div>

    <nav class="sidebar-nav" aria-label="主导航">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        :title="item.label"
        :aria-label="item.label"
        class="sidebar-item"
      >
        <component :is="item.icon" :size="18" :stroke-width="1.65" aria-hidden="true" />
        <span class="sidebar-label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar-footer">
      <button
        type="button"
        class="sidebar-item w-full"
        :title="theme === 'dark' ? '浅色主题' : '深色主题'"
        :aria-label="theme === 'dark' ? '浅色主题' : '深色主题'"
        @click="toggle"
      >
        <Sun v-if="theme === 'dark'" :size="18" :stroke-width="1.65" aria-hidden="true" />
        <Moon v-else :size="18" :stroke-width="1.65" aria-hidden="true" />
        <span class="sidebar-label">{{ theme === 'dark' ? '浅色主题' : '深色主题' }}</span>
      </button>
    </div>
  </aside>
</template>
