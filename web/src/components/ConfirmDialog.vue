<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="show"
        class="confirm-overlay"
        @click.self="onCancel"
        @keydown.esc="onCancel"
        tabindex="-1"
        ref="overlayRef"
      >
        <div
          class="confirm-dialog"
          :class="[`type-${type}`]"
          role="alertdialog"
          aria-modal="true"
        >
          <div class="confirm-header">
            <span class="confirm-icon">{{ iconMap[type] }}</span>
            <h3 class="confirm-title">{{ title }}</h3>
          </div>
          <div class="confirm-body">
            <p class="confirm-message">{{ message }}</p>
            <slot />
          </div>
          <div class="confirm-footer">
            <button
              class="btn-cancel"
              @click="onCancel"
              ref="cancelBtn"
            >
              {{ cancelText }}
            </button>
            <button
              class="btn-confirm"
              :class="[`btn-${type}`]"
              :disabled="loading"
              @click="onConfirm"
              ref="confirmBtn"
            >
              <span v-if="loading" class="loading-spinner"></span>
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  /** 是否显示 */
  show: {
    type: Boolean,
    default: false,
  },
  /** 标题 */
  title: {
    type: String,
    default: '确认操作',
  },
  /** 消息内容 */
  message: {
    type: String,
    default: '',
  },
  /** 确认按钮文字 */
  confirmText: {
    type: String,
    default: '确认',
  },
  /** 取消按钮文字 */
  cancelText: {
    type: String,
    default: '取消',
  },
  /** 类型: warn | danger | info */
  type: {
    type: String,
    default: 'warn',
    validator: (v) => ['warn', 'danger', 'info'].includes(v),
  },
  /** 是否加载中 */
  loading: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['confirm', 'cancel', 'update:show'])

const overlayRef = ref(null)
const cancelBtn = ref(null)
const confirmBtn = ref(null)

const iconMap = {
  warn: '⚠️',
  danger: '🗑️',
  info: 'ℹ️',
}

function onConfirm() {
  emit('confirm')
}

function onCancel() {
  emit('cancel')
  emit('update:show', false)
}

watch(() => props.show, (val) => {
  if (val) {
    nextTick(() => {
      overlayRef.value?.focus()
    })
  }
})
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-5, 16px);
}

.confirm-dialog {
  background: var(--bg-surface, #fff);
  border-radius: var(--radius-lg, 8px);
  box-shadow: var(--shadow-lg, 0 8px 32px rgba(0,0,0,0.18));
  width: 100%;
  max-width: 420px;
  overflow: hidden;
}

.confirm-header {
  display: flex;
  align-items: center;
  gap: var(--space-3, 8px);
  padding: var(--space-5, 16px) var(--space-5, 16px) var(--space-3, 8px);
}

.confirm-icon {
  font-size: 24px;
  line-height: 1;
}

.confirm-title {
  font-size: var(--text-lg, 16px);
  font-weight: 600;
  color: var(--text-primary, #20242c);
  margin: 0;
}

.confirm-body {
  padding: 0 var(--space-5, 16px) var(--space-5, 16px);
}

.confirm-message {
  font-size: var(--text-sm, 12px);
  color: var(--text-secondary, #667085);
  margin: 0;
  line-height: var(--line-height-relaxed, 1.6);
}

.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3, 8px);
  padding: var(--space-4, 12px) var(--space-5, 16px);
  background: var(--bg-page, #f7f8fa);
  border-top: 1px solid var(--border, #d9dee7);
}

.btn-cancel,
.btn-confirm {
  padding: var(--space-2, 6px) var(--space-4, 12px);
  border: 1px solid var(--border, #d9dee7);
  border-radius: var(--radius-md, 6px);
  font-size: var(--text-sm, 12px);
  cursor: pointer;
  transition: all var(--transition-fast, 0.1s ease);
}

.btn-cancel {
  background: var(--bg-surface, #fff);
  color: var(--text-primary, #20242c);
}

.btn-cancel:hover {
  background: var(--bg-page, #f7f8fa);
}

.btn-confirm {
  background: var(--accent, #1f6feb);
  color: #fff;
  border-color: var(--accent, #1f6feb);
}

.btn-confirm:hover {
  opacity: 0.9;
}

.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-danger {
  background: var(--bad, #c32f27);
  border-color: var(--bad, #c32f27);
}

.btn-warn {
  background: var(--warn, #9a6700);
  border-color: var(--warn, #9a6700);
}

.loading-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 4px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition-normal, 0.15s ease);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
