<template>
  <div class="review-bar" role="toolbar" aria-label="审核操作">
    <div class="review-note" v-if="showNote">
      <input
        v-model="note"
        :placeholder="notePlaceholder"
        class="note-input"
        @keydown.enter="onApprove"
      />
    </div>
    <div class="review-actions">
      <slot name="extra" />
      <button
        v-if="showQuarantine"
        class="btn-quarantine"
        :disabled="disabled"
        @click="$emit('quarantine')"
      >
        隔离
      </button>
      <button
        v-if="showSkip"
        class="btn-skip"
        :disabled="disabled"
        @click="$emit('skip')"
      >
        跳过
      </button>
      <button
        v-if="showReject"
        class="btn-reject"
        :disabled="disabled"
        @click="onReject"
      >
        {{ rejectText }}
      </button>
      <button
        v-if="showApprove"
        class="btn-approve"
        :disabled="disabled"
        @click="onApprove"
      >
        {{ approveText }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  /** 是否显示备注输入 */
  showNote: {
    type: Boolean,
    default: true,
  },
  /** 备注占位文字 */
  notePlaceholder: {
    type: String,
    default: '审核备注（可选）...',
  },
  /** 是否显示批准按钮 */
  showApprove: {
    type: Boolean,
    default: true,
  },
  /** 是否显示拒绝按钮 */
  showReject: {
    type: Boolean,
    default: true,
  },
  /** 是否显示跳过按钮 */
  showSkip: {
    type: Boolean,
    default: false,
  },
  /** 是否显示隔离按钮 */
  showQuarantine: {
    type: Boolean,
    default: false,
  },
  /** 批准按钮文字 */
  approveText: {
    type: String,
    default: '批准',
  },
  /** 拒绝按钮文字 */
  rejectText: {
    type: String,
    default: '拒绝',
  },
  /** 是否禁用 */
  disabled: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['approve', 'reject', 'skip', 'quarantine'])

const note = ref('')

function onApprove() {
  emit('approve', note.value)
}

function onReject() {
  emit('reject', note.value)
}

function clearNote() {
  note.value = ''
}

defineExpose({ clearNote })
</script>

<style scoped>
.review-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3, 8px);
  padding: var(--space-3, 8px) var(--space-4, 12px);
  background: var(--bg-surface, #fff);
  border-top: 1px solid var(--border, #d9dee7);
}

.review-note {
  flex: 1;
}

.note-input {
  width: 100%;
  padding: var(--space-2, 6px) var(--space-3, 8px);
  border: 1px solid var(--border, #d9dee7);
  border-radius: var(--radius-sm, 4px);
  font-size: var(--text-sm, 12px);
  background: var(--bg-page, #f7f8fa);
  color: var(--text-primary, #20242c);
  outline: none;
  transition: border-color var(--transition-fast, 0.1s ease);
}

.note-input:focus {
  border-color: var(--accent, #1f6feb);
}

.note-input::placeholder {
  color: var(--text-secondary, #667085);
}

.review-actions {
  display: flex;
  gap: var(--space-2, 6px);
  flex-shrink: 0;
}

.btn-approve,
.btn-reject,
.btn-skip,
.btn-quarantine {
  padding: var(--space-2, 6px) var(--space-4, 12px);
  border: 1px solid;
  border-radius: var(--radius-sm, 4px);
  font-size: var(--text-sm, 12px);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast, 0.1s ease);
  white-space: nowrap;
}

.btn-approve {
  background: var(--ok, #16833a);
  color: #fff;
  border-color: var(--ok, #16833a);
}

.btn-approve:hover {
  opacity: 0.9;
}

.btn-reject {
  background: var(--bad, #c32f27);
  color: #fff;
  border-color: var(--bad, #c32f27);
}

.btn-reject:hover {
  opacity: 0.9;
}

.btn-skip {
  background: var(--bg-surface, #fff);
  color: var(--text-primary, #20242c);
  border-color: var(--border, #d9dee7);
}

.btn-skip:hover {
  background: var(--bg-page, #f7f8fa);
}

.btn-quarantine {
  background: var(--bg-surface, #fff);
  color: var(--text-secondary, #667085);
  border-color: var(--border, #d9dee7);
}

.btn-quarantine:hover {
  background: var(--bg-page, #f7f8fa);
  color: var(--bad, #c32f27);
  border-color: var(--bad, #c32f27);
}

.btn-approve:disabled,
.btn-reject:disabled,
.btn-skip:disabled,
.btn-quarantine:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
