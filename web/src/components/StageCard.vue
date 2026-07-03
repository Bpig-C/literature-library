<template>
  <div class="stage-card" :class="{ expanded: isExpanded, 'has-items': count > 0 }">
    <!-- 头部 -->
    <div class="stage-header" @click="toggleExpand">
      <span class="stage-icon">{{ icon }}</span>
      <div class="stage-info">
        <h2 class="stage-title">{{ title }}</h2>
        <p class="stage-desc">{{ description }}</p>
      </div>
      <div class="stage-stats">
        <span class="stat-badge" :class="{ active: count > 0 }">
          {{ statLabel }}: {{ count }}
        </span>
        <span v-if="secondaryCount > 0" class="stat-badge secondary">
          {{ secondaryLabel || '待审核' }}: {{ secondaryCount }}
        </span>
        <slot name="stats" />
      </div>
      <span class="expand-arrow" :class="{ expanded: isExpanded }">▼</span>
    </div>

    <!-- 展开内容 -->
    <Transition name="expand">
      <div v-if="isExpanded" class="stage-body">
        <!-- 筛选栏 -->
        <div v-if="$slots.filters" class="filter-bar">
          <slot name="filters" />
        </div>

        <!-- 文件列表 -->
        <div class="file-list">
          <slot />
        </div>

        <!-- 底部操作栏 -->
        <div class="stage-actions">
          <span class="selection-summary">
            已选: <b>{{ selectedCount }}</b> / {{ count }}
          </span>
          <div class="action-buttons">
            <button
              class="btn-primary"
              :disabled="selectedCount === 0 || loading || actionDisabled"
              :title="actionDisabled ? '当前为审核模式，请切换到「待抽取」标签后操作' : ''"
              @click="$emit('execute')"
            >
              <span v-if="loading" class="loading-spinner"></span>
              {{ actionLabel }} ({{ selectedCount }})
            </button>
            <router-link
              v-if="reviewRoute"
              :to="reviewRoute"
              class="btn-link"
            >
              去审核 →
            </router-link>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  icon: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  count: { type: Number, default: 0 },
  statLabel: { type: String, default: '待处理' },
  secondaryCount: { type: Number, default: 0 },
  secondaryLabel: { type: String, default: '' },
  actionLabel: { type: String, default: '执行' },
  reviewRoute: { type: String, default: '' },
  selectedCount: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  defaultExpanded: { type: Boolean, default: false },
  /** 外部强制禁用执行按钮（如审核模式下不应再触发抽取） */
  actionDisabled: { type: Boolean, default: false },
})

defineEmits(['execute'])

const isExpanded = ref(props.defaultExpanded)

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}
</script>

<style scoped>
.stage-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all var(--transition-fast);
}

.stage-card:hover {
  border-color: var(--accent-mute);
}

.stage-card.has-items {
  border-left: 3px solid var(--accent);
}

.stage-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  cursor: pointer;
  user-select: none;
  transition: background var(--transition-fast);
}

.stage-header:hover {
  background: var(--bg-muted);
}

.stage-icon {
  font-size: 28px;
  flex-shrink: 0;
}

.stage-info {
  flex: 1;
  min-width: 0;
}

.stage-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-1);
}

.stage-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 0;
}

.stage-stats {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.stat-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: 999px;
  background: var(--bg-muted);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.stat-badge.active {
  background: var(--accent-subtle);
  color: var(--accent);
  font-weight: 500;
}

.stat-badge.secondary {
  background: var(--warn-bg);
  color: var(--warn-fg);
  font-weight: 500;
}

.expand-arrow {
  font-size: 12px;
  color: var(--text-tertiary);
  transition: transform var(--transition-normal);
  flex-shrink: 0;
}

.expand-arrow.expanded {
  transform: rotate(180deg);
}

/* 展开内容 */
.stage-body {
  border-top: 1px solid var(--border);
  padding: var(--space-4) var(--space-5);
}

.filter-bar {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
}

.file-list {
  min-height: 60px;
  max-height: 400px;
  overflow-y: auto;
}

.stage-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
}

.selection-summary {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.selection-summary b {
  color: var(--accent);
  font-weight: 600;
}

.action-buttons {
  display: flex;
  gap: var(--space-2);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-link {
  display: inline-flex;
  align-items: center;
  padding: var(--space-2) var(--space-4);
  background: var(--bg-surface);
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  text-decoration: none;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.btn-link:hover {
  background: var(--accent-subtle);
  text-decoration: none;
}

.loading-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all var(--transition-normal);
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: var(--stage-expand-max, 800px);
}

@media (max-width: 640px) {
  .stage-header {
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .stage-stats {
    width: 100%;
    order: 3;
  }

  .stage-actions {
    flex-direction: column;
    gap: var(--space-3);
  }

  .action-buttons {
    width: 100%;
    flex-direction: column;
  }

  .btn-primary,
  .btn-link {
    width: 100%;
    justify-content: center;
  }
}
</style>
