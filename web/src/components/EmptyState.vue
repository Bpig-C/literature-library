<template>
  <div class="empty-state" role="status">
    <div class="empty-icon">
      <slot name="icon">
        <span class="icon-placeholder">{{ iconMap[icon] || '📭' }}</span>
      </slot>
    </div>
    <h3 class="empty-title">{{ title }}</h3>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <button
      v-if="actionText"
      class="empty-action"
      @click="$emit('action')"
    >
      {{ actionText }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  /** 图标类型: inbox | search | data | error | success */
  icon: {
    type: String,
    default: 'inbox',
  },
  /** 标题 */
  title: {
    type: String,
    default: '暂无数据',
  },
  /** 描述文字 */
  description: {
    type: String,
    default: '',
  },
  /** 操作按钮文字 */
  actionText: {
    type: String,
    default: '',
  },
})

defineEmits(['action'])

const iconMap = {
  inbox: '📭',
  search: '🔍',
  data: '📊',
  error: '❌',
  success: '✅',
  empty: '📄',
  file: '📁',
}
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8, 32px) var(--space-5, 16px);
  text-align: center;
  min-height: 200px;
}

.empty-icon {
  margin-bottom: var(--space-4, 12px);
}

.icon-placeholder {
  font-size: 48px;
  line-height: 1;
  opacity: 0.5;
}

.empty-title {
  font-size: var(--text-lg, 16px);
  font-weight: 600;
  color: var(--text-primary, #20242c);
  margin: 0 0 var(--space-2, 6px);
}

.empty-desc {
  font-size: var(--text-sm, 12px);
  color: var(--text-secondary, #667085);
  margin: 0 0 var(--space-5, 16px);
  max-width: 300px;
}

.empty-action {
  padding: var(--space-2, 6px) var(--space-5, 16px);
  background: var(--accent, #1f6feb);
  color: #fff;
  border: none;
  border-radius: var(--radius-md, 6px);
  font-size: var(--text-sm, 12px);
  cursor: pointer;
  transition: opacity var(--transition-fast, 0.1s ease);
}

.empty-action:hover {
  opacity: 0.9;
}

.empty-action:focus-visible {
  outline: 2px solid var(--accent, #1f6feb);
  outline-offset: 2px;
}
</style>
