<template>
  <div class="search-header">
    <div class="search-main">
      <div class="search-input-wrapper">
        <span class="search-icon">🔍</span>
        <input
          ref="inputRef"
          :value="modelValue"
          @input="onInput"
          :placeholder="placeholder"
          class="search-input"
          @keydown.enter="$emit('search')"
          @keydown.esc="onClear"
        />
        <button
          v-if="modelValue"
          class="clear-btn"
          @click="onClear"
          title="清除"
        >
          ×
        </button>
      </div>
      <button
        class="search-btn"
        @click="$emit('search')"
        :disabled="loading"
      >
        <span v-if="loading" class="loading-spinner"></span>
        {{ loading ? '搜索中...' : '搜索' }}
      </button>
    </div>

    <div v-if="hasFilters" class="filters-section">
      <button
        class="toggle-filters-btn"
        @click="showFilters = !showFilters"
      >
        {{ showFilters ? '收起筛选' : '高级筛选' }}
        <span class="toggle-icon">{{ showFilters ? '▲' : '▼' }}</span>
      </button>

      <Transition name="slide">
        <div v-if="showFilters" class="filters-content">
          <slot name="filters" />
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useDebounce } from '../composables/useFormatUtils'

const props = defineProps({
  /** 搜索词 */
  modelValue: {
    type: String,
    default: '',
  },
  /** 占位文字 */
  placeholder: {
    type: String,
    default: '搜索...',
  },
  /** 是否加载中 */
  loading: {
    type: Boolean,
    default: false,
  },
  /** 是否有筛选器 */
  hasFilters: {
    type: Boolean,
    default: false,
  },
  /** 防抖延迟(ms) */
  debounce: {
    type: Number,
    default: 300,
  },
})

const emit = defineEmits(['update:modelValue', 'search', 'clear'])

const inputRef = ref(null)
const showFilters = ref(false)

const { execute: debouncedEmit } = useDebounce((val) => {
  emit('update:modelValue', val)
}, props.debounce)

function onInput(e) {
  debouncedEmit(e.target.value)
}

function onClear() {
  emit('update:modelValue', '')
  emit('clear')
  inputRef.value?.focus()
}

function focus() {
  inputRef.value?.focus()
}

defineExpose({ focus })
</script>

<style scoped>
.search-header {
  margin-bottom: var(--space-4, 12px);
}

.search-main {
  display: flex;
  gap: var(--space-2, 6px);
}

.search-input-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  border: 1px solid var(--border, #d9dee7);
  border-radius: var(--radius-md, 6px);
  background: var(--bg-surface, #fff);
  padding: 0 var(--space-3, 8px);
  transition: border-color var(--transition-fast, 0.1s ease);
}

.search-input-wrapper:focus-within {
  border-color: var(--accent, #1f6feb);
  box-shadow: var(--shadow-focus);
}

.search-icon {
  font-size: 14px;
  margin-right: var(--space-2, 6px);
  opacity: 0.5;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--text-sm, 12px);
  padding: var(--space-2, 6px) 0;
  color: var(--text-primary, #20242c);
}

.search-input::placeholder {
  color: var(--text-secondary, #667085);
}

.clear-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: var(--text-secondary, #667085);
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

.clear-btn:hover {
  color: var(--text-primary, #20242c);
}

.search-btn {
  padding: 0 var(--space-4, 12px);
  background: var(--accent, #1f6feb);
  color: #fff;
  border: none;
  border-radius: var(--radius-md, 6px);
  font-size: var(--text-sm, 12px);
  cursor: pointer;
  transition: opacity var(--transition-fast, 0.1s ease);
  white-space: nowrap;
}

.search-btn:hover {
  opacity: 0.9;
}

.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.filters-section {
  margin-top: var(--space-3, 8px);
}

.toggle-filters-btn {
  background: none;
  border: none;
  font-size: var(--text-xs, 11px);
  color: var(--text-secondary, #667085);
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 4px;
}

.toggle-filters-btn:hover {
  color: var(--accent, #1f6feb);
}

.toggle-icon {
  font-size: 10px;
}

.filters-content {
  margin-top: var(--space-3, 8px);
  padding: var(--space-4, 12px);
  background: var(--bg-page, #f7f8fa);
  border-radius: var(--radius-md, 6px);
  border: 1px solid var(--border, #d9dee7);
}

.slide-enter-active,
.slide-leave-active {
  transition: all var(--transition-normal, 0.15s ease);
  overflow: hidden;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.slide-enter-to,
.slide-leave-from {
  opacity: 1;
  max-height: 500px;
}
</style>
