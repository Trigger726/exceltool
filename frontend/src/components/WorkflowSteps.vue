<script setup lang="ts">
defineProps<{ stage: 1 | 2 | 3 }>()
const labels = ['选择文件', '确认配置', '查看结果并导出']
</script>

<template>
  <ol class="workflow-steps" aria-label="操作进度">
    <li v-for="(label, index) in labels" :key="label" :aria-current="index + 1 === stage ? 'step' : undefined"
      :class="{ completed: index + 1 < stage }">
      <span aria-hidden="true">{{ index + 1 < stage ? '✓' : index + 1 }}</span>{{ label }}
    </li>
  </ol>
</template>
