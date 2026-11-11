<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
  title: string
  message: string
  details?: { label: string; value: string | number }[]
  confirmText?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const dialog = ref<HTMLDialogElement | null>(null)
watchEffect(() => {
  if (props.open && dialog.value && !dialog.value.open) dialog.value.showModal()
  if (!props.open && dialog.value?.open) dialog.value.close()
})
const details = computed(() => props.details ?? [])
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="confirm-dialog card w-[calc(100%-2rem)] max-w-[440px] text-ink shadow-pop"
      aria-labelledby="confirmation-title" @cancel.prevent="!busy && emit('cancel')">
          <div class="flex items-start gap-3 px-5 pb-2 pt-5">
            <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-danger-soft">
              <AlertTriangle :size="16" class="text-danger" />
            </span>
            <div>
              <h2 id="confirmation-title" class="text-sm font-semibold">{{ title }}</h2>
              <p class="mt-1 text-sm leading-relaxed text-ink-muted">{{ message }}</p>
            </div>
          </div>

          <dl
            v-if="details.length"
            class="mx-5 mb-1 mt-3 space-y-1 rounded-control bg-line-soft/70 px-3 py-2.5 text-xs"
          >
            <div v-for="item in details" :key="item.label" class="flex justify-between gap-4">
              <dt class="text-ink-muted">{{ item.label }}</dt>
              <dd class="font-medium tabular-nums">{{ item.value }}</dd>
            </div>
          </dl>

          <div class="flex justify-end gap-2 px-5 pb-5 pt-4">
            <button type="button" class="btn btn-default" autofocus :disabled="busy" @click="emit('cancel')">
              取消
            </button>
            <button type="button" class="btn btn-danger" :disabled="busy" @click="emit('confirm')">
              {{ confirmText || '确认删除' }}
            </button>
          </div>
    </dialog>
  </Teleport>
</template>
