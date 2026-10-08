<template>
  <div
    class="resize-handle"
    :class="{ active: dragging }"
    @mousedown.prevent="startDrag"
  >
    <div class="resize-grip"></div>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'

const emit = defineEmits(['resize'])
const props = defineProps({
  target: { type: String, default: 'previous' },
})

const dragging = ref(false)
let startX = 0
let startWidth = 0

function startDrag(e) {
  dragging.value = true
  startX = e.clientX
  const handle = e.currentTarget
  const target = props.target === 'next' ? handle.nextElementSibling : handle.previousElementSibling
  startWidth = target ? target.offsetWidth : 0
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
  document.addEventListener('mouseleave', stopDrag)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onDrag(e) {
  if (!dragging.value) return
  const delta = e.clientX - startX
  emit('resize', startWidth + delta)
}

function stopDrag() {
  dragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
  document.removeEventListener('mouseleave', stopDrag)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
  document.removeEventListener('mouseleave', stopDrag)
})
</script>

<style scoped>
.resize-handle {
  width: 6px;
  cursor: col-resize;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}
.resize-handle:hover,
.resize-handle.active {
  background: rgba(0, 0, 0, 0.08);
}
.resize-grip {
  width: 2px;
  height: 24px;
  border-radius: 1px;
  background: #d1d5db;
}
.resize-handle:hover .resize-grip,
.resize-handle.active .resize-grip {
  background: var(--accent, #3b82f6);
}
</style>
