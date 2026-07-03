<template>
  <div class="selectable-list">
    <!-- 工具栏（仅在可选模式下显示） -->
    <div v-if="selectable" class="list-toolbar">
      <label class="select-all">
        <input
          type="checkbox"
          :checked="isAllSelected"
          :indeterminate="isPartial"
          @change="toggleAll"
        />
        <span>全选本页</span>
      </label>
      <button class="toolbar-btn" @click="invertSelection">反选</button>
      <button
        v-if="selectedIds.size > 0"
        class="toolbar-btn"
        @click="clearSelection"
      >
        取消全选
      </button>
    </div>

    <!-- 列表 -->
    <div class="list-body">
      <div
        v-for="item in pagedItems"
        :key="item.id"
        class="list-item"
        :class="{ selected: selectable && selectedIds.has(item.id) }"
        @click="selectable && toggleItem(item.id)"
      >
        <input
          v-if="selectable"
          type="checkbox"
          :checked="selectedIds.has(item.id)"
          @click.stop
          @change="toggleItem(item.id)"
          class="item-checkbox"
        />
        <slot name="item" :item="item">
          <span class="item-title">{{ item.title || item.id }}</span>
        </slot>
      </div>

      <EmptyState
        v-if="!pagedItems.length && !loading"
        icon="search"
        title="没有匹配的记录"
      />

      <div v-if="loading" class="loading-state">
        <span class="loading-spinner"></span>
        加载中...
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="totalPages > 1" class="pagination">
      <button
        :disabled="page <= 1"
        @click="$emit('update:page', page - 1)"
        class="page-btn"
      >
        ‹
      </button>
      <span class="page-info">{{ page }} / {{ totalPages }}</span>
      <button
        :disabled="page >= totalPages"
        @click="$emit('update:page', page + 1)"
        class="page-btn"
      >
        ›
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'

const props = defineProps({
  items: { type: Array, required: true },
  selectedIds: { type: Object, required: true }, // Set
  loading: { type: Boolean, default: false },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  /** 是否显示复选框和选择工具栏（审核模式下设为 false，纯展示列表） */
  selectable: { type: Boolean, default: true },
})

const emit = defineEmits(['update:selected', 'update:page'])

const totalPages = computed(() => Math.ceil(props.items.length / props.pageSize))

const pagedItems = computed(() => {
  const start = (props.page - 1) * props.pageSize
  return props.items.slice(start, start + props.pageSize)
})

const isAllSelected = computed(() => {
  if (pagedItems.value.length === 0) return false
  return pagedItems.value.every(item => props.selectedIds.has(item.id))
})

const isPartial = computed(() => {
  if (pagedItems.value.length === 0) return false
  const selectedInPage = pagedItems.value.filter(item => props.selectedIds.has(item.id)).length
  return selectedInPage > 0 && selectedInPage < pagedItems.value.length
})

function toggleItem(id) {
  const newSet = new Set(props.selectedIds)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  emit('update:selected', newSet)
}

function toggleAll() {
  const newSet = new Set(props.selectedIds)
  if (isAllSelected.value) {
    // 取消本页所有
    pagedItems.value.forEach(item => newSet.delete(item.id))
  } else {
    // 选中本页所有
    pagedItems.value.forEach(item => newSet.add(item.id))
  }
  emit('update:selected', newSet)
}

function invertSelection() {
  const newSet = new Set(props.selectedIds)
  pagedItems.value.forEach(item => {
    if (newSet.has(item.id)) {
      newSet.delete(item.id)
    } else {
      newSet.add(item.id)
    }
  })
  emit('update:selected', newSet)
}

function clearSelection() {
  emit('update:selected', new Set())
}
</script>

<style scoped>
.selectable-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.select-all {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
}

.select-all input[type="checkbox"] {
  cursor: pointer;
}

.toolbar-btn {
  padding: var(--space-1) var(--space-2);
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.toolbar-btn:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

.list-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.list-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.list-item[style*="cursor: default"] {
  cursor: default;
}

.list-item:hover {
  background: var(--bg-muted);
}

.list-item.selected {
  background: var(--accent-subtle);
}

.item-checkbox {
  flex-shrink: 0;
  cursor: pointer;
}

.item-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.page-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-muted);
  color: var(--text-primary);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.loading-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
