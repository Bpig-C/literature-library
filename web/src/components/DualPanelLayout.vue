<template>
  <div class="dual-panel" :class="{ collapsed: listCollapsed }">
    <!-- 左侧列表区 -->
    <div
      class="panel-list"
      :style="{ width: listCollapsed ? '0' : listWidth + 'px' }"
    >
      <div class="panel-list-content">
        <slot name="list" />
      </div>
      <ResizeHandle
        v-if="!listCollapsed"
        direction="horizontal"
        @resize="onResize"
      />
    </div>

    <!-- 右侧详情区 -->
    <div class="panel-detail">
      <slot name="detail" />
    </div>

    <!-- 可选: PDF 侧栏 -->
    <Transition name="slide-right">
      <div
        v-if="showPdf && pdfWorkId"
        class="panel-pdf"
        :style="{ width: pdfWidth + 'px' }"
      >
        <slot name="pdf" />
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { toRef } from 'vue'
import { useDualPanel } from '../composables/useDualPanel'
import ResizeHandle from './ResizeHandle.vue'

const props = defineProps({
  /** 默认列表宽度 */
  defaultListWidth: {
    type: Number,
    default: 480,
  },
  /** 最小列表宽度 */
  minListWidth: {
    type: Number,
    default: 280,
  },
  /** 最大列表宽度 */
  maxListWidth: {
    type: Number,
    default: 600,
  },
  /** 是否显示 PDF 侧栏 */
  showPdf: {
    type: Boolean,
    default: false,
  },
  /** PDF 工作 ID */
  pdfWorkId: {
    type: String,
    default: null,
  },
  /** PDF 侧栏宽度 */
  pdfWidth: {
    type: Number,
    default: 420,
  },
})

const emit = defineEmits(['toggle-list', 'resize'])

const {
  listWidth,
  listCollapsed,
  toggleList,
  onResize: handleResize,
} = useDualPanel({
  defaultListWidth: props.defaultListWidth,
  minListWidth: props.minListWidth,
  maxListWidth: props.maxListWidth,
})

function onResize(delta) {
  handleResize(delta)
  emit('resize', delta)
}

function toggle() {
  toggleList()
  emit('toggle-list', listCollapsed.value)
}

defineExpose({
  listWidth,
  listCollapsed,
  toggleList: toggle,
})
</script>

<style scoped>
.dual-panel {
  display: grid;
  grid-template-columns: auto 1fr;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.dual-panel.has-pdf {
  grid-template-columns: auto 1fr auto;
}

.panel-list {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border, #d9dee7);
  background: var(--bg-surface, #fff);
  overflow: hidden;
  transition: width var(--transition-normal, 0.15s ease);
  position: relative;
  min-width: 0;
}

.panel-list-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.panel-detail {
  min-width: 0;
  overflow-y: auto;
  background: var(--bg-surface, #fff);
}

.panel-pdf {
  border-left: 1px solid var(--border, #d9dee7);
  background: var(--bg-surface, #fff);
  overflow: hidden;
}

.collapsed .panel-list {
  width: 0 !important;
  border-right: none;
}

/* PDF 侧栏动画 */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: all var(--transition-normal, 0.15s ease);
}

.slide-right-enter-from,
.slide-right-leave-to {
  width: 0 !important;
  opacity: 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .dual-panel {
    grid-template-columns: 1fr;
  }

  .panel-list {
    border-right: none;
    border-bottom: 1px solid var(--border, #d9dee7);
  }
}
</style>
