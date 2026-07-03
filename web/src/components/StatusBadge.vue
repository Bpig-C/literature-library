<template>
  <span
    class="status-badge"
    :class="[`size-${size}`, `variant-${variant}`, statusClass]"
    :style="statusStyle"
  >
    <span v-if="showDot && variant === 'dot'" class="status-dot"></span>
    <span class="status-label">{{ label || status }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { STATUS_COLOR_MAP } from '../constants/options'

const props = defineProps({
  /** 状态类型 */
  status: {
    type: String,
    required: true,
  },
  /** 尺寸: small | medium | large */
  size: {
    type: String,
    default: 'medium',
    validator: (v) => ['small', 'medium', 'large'].includes(v),
  },
  /** 变体: filled | dot | outlined */
  variant: {
    type: String,
    default: 'filled',
    validator: (v) => ['filled', 'dot', 'outlined'].includes(v),
  },
  /** 是否显示圆点（仅 dot 变体有效） */
  showDot: {
    type: Boolean,
    default: true,
  },
  /** 自定义标签文字 */
  label: {
    type: String,
    default: '',
  },
})

const statusClass = computed(() => `status-${props.status}`)

const statusStyle = computed(() => {
  const colors = STATUS_COLOR_MAP[props.status]
  if (!colors) return {}

  if (props.variant === 'filled') {
    return {
      backgroundColor: colors.bg,
      color: colors.fg,
      borderColor: colors.border,
    }
  }
  if (props.variant === 'outlined') {
    return {
      backgroundColor: 'transparent',
      color: colors.fg,
      borderColor: colors.border,
    }
  }
  return {}
})
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid;
  border-radius: 999px;
  font-weight: 500;
  white-space: nowrap;
}

.size-small {
  padding: 1px 6px;
  font-size: var(--text-xs, 11px);
}

.size-medium {
  padding: 2px 8px;
  font-size: var(--text-sm, 12px);
}

.size-large {
  padding: 4px 12px;
  font-size: var(--text-base, 13px);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.variant-dot .status-label {
  font-weight: 400;
}
</style>
