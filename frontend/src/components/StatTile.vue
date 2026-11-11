<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  tone?: 'neutral' | 'primary' | 'success' | 'danger' | 'warning'
}>()
</script>

<template>
  <div class="card px-3.5 py-3">
    <div class="text-xs text-ink-muted">{{ label }}</div>
    <div
      class="mt-1 text-xl font-semibold tabular-nums tracking-tight"
      :class="{
        'text-ink': !tone || tone === 'neutral',
        'text-primary': tone === 'primary',
        'text-success': tone === 'success',
        'text-danger': tone === 'danger',
        'text-warning': tone === 'warning',
      }"
    >
      {{ value }}
    </div>
  </div>
</template>
