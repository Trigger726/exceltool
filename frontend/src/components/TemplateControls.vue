<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type TemplateRule } from '@/services/bridge'
import { useToast } from '@/composables/useToast'

const props = defineProps<{ kind: 'merge' | 'clean'; rule: TemplateRule | null }>()
const emit = defineEmits<{ apply: [rule: TemplateRule] }>()
const toast = useToast()
const items = ref<Record<string, TemplateRule>>({})
const selected = ref('')
const name = ref('')
const busy = ref(false)

function errorMessage(error: unknown) {
  toast.error(error instanceof Error ? error.message : '无法读取或保存模板')
}

onMounted(async () => {
  try {
    const response = await api.templates(props.kind)
    items.value = response.templates
  } catch (error) {
    errorMessage(error)
  }
})

async function save() {
  if (!props.rule || !name.value.trim()) return
  busy.value = true
  try {
    const response = await api.templates(props.kind, { name: name.value, rule: props.rule })
    items.value = response.templates
    selected.value = name.value.trim()
    toast.success('已保存模板')
    name.value = ''
  } catch (error) {
    errorMessage(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex flex-wrap gap-2">
    <div v-if="Object.keys(items).length" class="flex min-w-0 items-center gap-2">
      <select v-model="selected" class="field min-w-0" aria-label="选择已保存的模板">
        <option value="">选择模板</option>
        <option v-for="(_rule, label) in items" :key="label" :value="label">{{ label }}</option>
      </select>
      <button type="button" class="btn btn-default" :disabled="!selected || busy"
        @click="emit('apply', items[selected])">应用模板</button>
    </div>
    <form class="flex min-w-0 items-center gap-2" @submit.prevent="save">
      <input v-model="name" class="field min-w-0" placeholder="模板名称" aria-label="模板名称" maxlength="60" />
      <button type="submit" class="btn btn-default" :disabled="!name.trim() || !rule || busy">
        {{ Object.prototype.hasOwnProperty.call(items, name.trim()) ? '更新模板' : '保存模板' }}
      </button>
    </form>
  </div>
</template>
