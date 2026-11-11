import { createRouter, createWebHashHistory } from 'vue-router'

import Home from '@/views/Home.vue'
import Compare from '@/views/Compare.vue'
import Merge from '@/views/Merge.vue'
import Clean from '@/views/Clean.vue'

export const routes = [
  {
    path: '/',
    name: 'home',
    component: Home,
    meta: { title: '首页', caption: '选择一个功能开始处理你的表格' },
  },
  {
    path: '/compare',
    name: 'compare',
    component: Compare,
    meta: { title: '表格对比', caption: '按业务唯一键比对两个版本，找出新增、删除与修改' },
  },
  {
    path: '/merge',
    name: 'merge',
    component: Merge,
    meta: { title: '批量合并', caption: '把多个结构相近的表格纵向汇总成一个文件' },
  },
  {
    path: '/clean',
    name: 'clean',
    component: Clean,
    meta: { title: '数据清洗', caption: '检测并处理重复、空值与格式问题' },
  },
]

// Hash history keeps the single inlined HTML file working without any server.
export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
