import { reactive } from 'vue'

/** Shared progress state, fed by the Python side while a job runs. */
const state = reactive({ busy: false, stage: '', ratio: 0 })

export function useProgress() {
  return {
    state,
    begin(stage = '正在处理…') {
      state.busy = true
      state.stage = stage
      state.ratio = 0
    },
    update(stage: string, ratio: number) {
      state.busy = true
      state.stage = stage
      state.ratio = ratio
    },
    end() {
      state.busy = false
      state.stage = ''
      state.ratio = 0
    },
  }
}
