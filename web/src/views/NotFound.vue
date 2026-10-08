<template>
  <div class="not-found">
    <div class="not-found-content">
      <div class="not-found-icon">404</div>
      <h1 class="not-found-title">页面未找到</h1>
      <p class="not-found-desc">您访问的页面不存在或已被移除</p>
      <button class="not-found-btn" @click="goHome">返回首页</button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push({ name: 'dashboard' })
}
</script>

<style scoped>
.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 32px;
}

.not-found-content {
  text-align: center;
}

.not-found-icon {
  font-size: 96px;
  font-weight: 700;
  color: var(--accent, #1f6feb);
  opacity: 0.3;
  line-height: 1;
  margin-bottom: 16px;
}

.not-found-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--text, #20242c);
  margin: 0 0 8px;
}

.not-found-desc {
  font-size: 14px;
  color: var(--muted, #667085);
  margin: 0 0 24px;
}

.not-found-btn {
  display: inline-block;
  padding: 10px 24px;
  background: var(--accent, #1f6feb);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.not-found-btn:hover {
  opacity: 0.9;
}

.not-found-btn:focus-visible {
  outline: 2px solid var(--accent, #1f6feb);
  outline-offset: 2px;
}
</style>
