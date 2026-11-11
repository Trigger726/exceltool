<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  Columns3,
  Combine,
  LayoutGrid,
  Moon,
  Sparkles,
  Sun,
} from 'lucide-vue-next'

import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const { theme, toggle } = useTheme()

const items = [
  { to: '/', label: '首页', icon: LayoutGrid },
  { to: '/compare', label: '表格对比', icon: Columns3 },
  { to: '/merge', label: '批量合并', icon: Combine },
  { to: '/clean', label: '数据清洗', icon: Sparkles },
]

const activePath = computed(() => route.path)
</script>

<template>
  <aside
    class="flex h-full app-sidebar w-[176px] shrink-0 flex-col border-r border-line bg-surface"
  >
    <div class="flex items-center gap-2.5 px-4 pb-4 pt-5">
      <div
        class="grid h-8 w-8 place-items-center rounded-control bg-primary text-sm font-bold text-white"
      >
        S
      </div>
      <div class="sidebar-label leading-tight">
        <div class="text-sm font-semibold tracking-tight">SheetKit</div>
        <div class="text-2xs text-ink-faint">表格效率助手</div>
      </div>
    </div>

    <nav class="flex flex-1 flex-col gap-0.5 px-2.5">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        :title="item.label"
        :aria-label="item.label"
        class="flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm font-medium transition-colors"
        :class="
          activePath === item.to
            ? 'bg-primary-soft text-primary'
            : 'text-ink-muted hover:bg-line-soft hover:text-ink'
        "
      >
        <component :is="item.icon" :size="16" :stroke-width="1.9" />
        <span class="sidebar-label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="border-t border-line-soft p-2.5">
      <button
        type="button"
        class="flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-sm text-ink-muted transition-colors hover:bg-line-soft hover:text-ink"
        :title="theme === 'dark' ? '浅色主题' : '深色主题'"
        :aria-label="theme === 'dark' ? '浅色主题' : '深色主题'"
        @click="toggle"
      >
        <Sun v-if="theme === 'dark'" :size="16" :stroke-width="1.9" />
        <Moon v-else :size="16" :stroke-width="1.9" />
        <span class="sidebar-label">{{ theme === 'dark' ? '浅色主题' : '深色主题' }}</span>
      </button>
    </div>
  </aside>
</template>
