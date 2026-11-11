import { computed, reactive } from 'vue'

export type ToastKind = 'info' | 'success' | 'error'

export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}

const state = reactive({ items: [] as ToastItem[] })
let counter = 0

function dismiss(id: number) {
  const index = state.items.findIndex((item) => item.id === id)
  if (index >= 0) state.items.splice(index, 1)
}

function push(kind: ToastKind, text: string, timeout = 6000) {
  counter += 1
  const id = counter
  state.items.push({ id, kind, text })
  if (state.items.length > 2) state.items.shift()
  if (timeout > 0) window.setTimeout(() => dismiss(id), timeout)
  return id
}

export function useToast() {
  return {
    items: computed(() => state.items),
    dismiss,
    info: (text: string) => push('info', text),
    success: (text: string) => push('success', text),
    error: (text: string) => push('error', text, 9000),
  }
}
