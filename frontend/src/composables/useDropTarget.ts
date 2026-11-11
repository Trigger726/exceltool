import { ref } from 'vue'

/** Routing for files dropped onto the window.
 *
 * The shell owns the native drop event because only it can turn a browser
 * drop into a real filesystem path. The page then decides which picker the
 * files belong to: the one the pointer is over, or the only one on screen. */

export type DropHandler = (paths: string[]) => void

const handlers = new Map<string, DropHandler>()
export const activeDropTarget = ref<string | null>(null)

export function registerDropTarget(id: string, handler: DropHandler) {
  handlers.set(id, handler)
  return () => {
    handlers.delete(id)
    if (activeDropTarget.value === id) activeDropTarget.value = null
  }
}

export function setActiveDropTarget(id: string | null) {
  activeDropTarget.value = id
}

export function dispatchDrop(paths: string[]) {
  if (!paths.length) return
  const preferred = activeDropTarget.value ? handlers.get(activeDropTarget.value) : undefined
  const fallback = handlers.values().next().value as DropHandler | undefined
  ;(preferred ?? fallback)?.(paths)
}
