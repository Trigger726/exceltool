<script setup lang="ts">
defineProps<{
  title: string
  caption?: string
}>()
</script>

<template>
  <header class="workflow-header shrink-0 border-b border-line bg-surface">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h1 class="text-lg font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="caption" class="mt-0.5 text-sm text-ink-muted">{{ caption }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </header>
</template>
