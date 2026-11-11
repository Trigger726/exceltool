<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

import AppSidebar from '@/components/AppSidebar.vue'
import ToastHost from '@/components/ToastHost.vue'
import { dispatchDrop } from '@/composables/useDropTarget'
import { useProgress } from '@/composables/useProgress'
import { bridgeReady } from '@/services/bridge'

const { update } = useProgress()

// Without this the browser opens the dropped file instead of handing it to the app.
const swallowDrag = (event: Event) => event.preventDefault()

onMounted(async () => {
  window.addEventListener('dragover', swallowDrag)
  window.addEventListener('drop', swallowDrag)
  await bridgeReady
  // The shell pushes native drop paths here because only it can resolve a
  // dropped item to a real file on disk.
  window.sheetkitDrop = (paths) => dispatchDrop(paths)
  window.sheetkitProgress = ({ stage, ratio }) => update(stage, ratio)
})

onBeforeUnmount(() => {
  window.removeEventListener('dragover', swallowDrag)
  window.removeEventListener('drop', swallowDrag)
})
</script>

<template>
  <div class="flex h-full w-full overflow-hidden bg-canvas">
    <AppSidebar />
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <RouterView v-slot="{ Component }">
        <component :is="Component" />
      </RouterView>
    </main>
    <ToastHost />
  </div>
</template>
