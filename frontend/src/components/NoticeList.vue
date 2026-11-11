<script setup lang="ts">
import { AlertTriangle, Info } from 'lucide-vue-next'

defineProps<{
  messages: string[]
  tone?: 'warning' | 'info'
}>()
</script>

<template>
  <ul
    v-if="messages.length"
    class="space-y-1.5 rounded-control border px-3 py-2.5 text-xs"
    :class="
      tone === 'info'
        ? 'border-line bg-line-soft/60 text-ink-muted'
        : 'border-warning/30 bg-warning-soft text-warning'
    "
  >
    <li v-for="(message, index) in messages" :key="index" class="flex gap-1.5">
      <Info v-if="tone === 'info'" :size="13" class="mt-[2px] shrink-0" />
      <AlertTriangle v-else :size="13" class="mt-[2px] shrink-0" />
      <span class="selectable leading-relaxed">{{ message }}</span>
    </li>
  </ul>
</template>
