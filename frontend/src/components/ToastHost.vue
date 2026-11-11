<script setup lang="ts">
import { CheckCircle2, Info, X, XCircle } from 'lucide-vue-next'

import { useToast } from '@/composables/useToast'

const { items, dismiss } = useToast()

const toneClass = {
  info: 'border-line bg-surface text-ink',
  success: 'border-success/40 bg-surface text-ink',
  error: 'border-danger/40 bg-surface text-ink',
}

const iconClass = {
  info: 'text-primary',
  success: 'text-success',
  error: 'text-danger',
}
</script>

<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[360px] flex-col gap-2">
    <TransitionGroup name="fade">
      <div
        v-for="item in items"
        :key="item.id"
        class="pointer-events-auto flex items-start gap-2 rounded-card border px-3 py-2.5 shadow-pop"
        :class="toneClass[item.kind]"
      >
        <Info v-if="item.kind === 'info'" :size="15" class="mt-[2px] shrink-0" :class="iconClass.info" />
        <CheckCircle2
          v-else-if="item.kind === 'success'"
          :size="15"
          class="mt-[2px] shrink-0"
          :class="iconClass.success"
        />
        <XCircle v-else :size="15" class="mt-[2px] shrink-0" :class="iconClass.error" />
        <p class="selectable flex-1 text-xs leading-relaxed">{{ item.text }}</p>
        <button
          type="button"
          class="shrink-0 rounded p-0.5 text-ink-faint transition-colors hover:text-ink"
          @click="dismiss(item.id)"
        >
          <X :size="13" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>
