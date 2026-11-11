<script setup lang="ts">
defineProps<{
  title: string
  caption?: string
}>()
</script>

<template>
  <header class="shrink-0 border-b border-line bg-surface px-7 pb-4 pt-6">
    <div class="flex items-start justify-between gap-6">
      <div class="min-w-0">
        <h1 class="text-lg font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="caption" class="mt-0.5 text-sm text-ink-muted">{{ caption }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
