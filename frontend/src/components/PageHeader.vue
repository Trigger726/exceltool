<script setup lang="ts">
defineProps<{
  title: string
  caption?: string
}>()
</script>

<template>
  <header class="workflow-header shrink-0">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="workflow-heading font-display">{{ title }}</h1>
        <p v-if="caption" class="workflow-caption mt-2 text-ink-muted">{{ caption }}</p>
      </div>
      <div class="workflow-actions flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </header>
</template>
