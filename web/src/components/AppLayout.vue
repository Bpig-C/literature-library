<template>
  <div class="layout" :class="{ collapsed: collapsed }">
    <nav class="sidebar">
      <div class="sidebar-brand">
        <span v-if="collapsed">文</span>
        <span v-else>文献库</span>
        <button class="collapse-btn" @click="collapsed = !collapsed" :title="collapsed ? '展开侧栏' : '收起侧栏'">
          {{ collapsed ? '»' : '«' }}
        </button>
      </div>
      <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }">
        <span class="nav-icon">📊</span><span class="nav-text">总览</span>
      </router-link>
      <router-link to="/works" class="nav-item" :class="{ active: $route.path.startsWith('/works') }">
        <span class="nav-icon">📚</span><span class="nav-text">文献</span>
      </router-link>
      <router-link to="/duplicates" class="nav-item" :class="{ active: $route.path === '/duplicates' }">
        <span class="nav-icon">🔍</span><span class="nav-text">去重</span>
      </router-link>
      <router-link to="/relations" class="nav-item" :class="{ active: $route.path === '/relations' }">
        <span class="nav-icon">🔗</span><span class="nav-text">关系</span>
      </router-link>
      <router-link to="/metadata" class="nav-item" :class="{ active: $route.path === '/metadata' }">
        <span class="nav-icon">🏷️</span><span class="nav-text">元数据</span>
      </router-link>
      <router-link to="/classification" class="nav-item" :class="{ active: $route.path === '/classification' }">
        <span class="nav-icon">📋</span><span class="nav-text">分类审核</span>
      </router-link>
      <router-link to="/intake" class="nav-item" :class="{ active: $route.path === '/intake' }">
        <span class="nav-icon">📥</span><span class="nav-text">采集审核</span>
      </router-link>
      <router-link to="/topics" class="nav-item" :class="{ active: $route.path === '/topics' }">
        <span class="nav-icon">🗂️</span><span class="nav-text">主题闸门</span>
      </router-link>
    </nav>
    <main class="content">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const collapsed = ref(false)
</script>

<style>
:root {
  color-scheme: light;
  --bg: #f7f8fa;
  --panel: #ffffff;
  --line: #d9dee7;
  --text: #20242c;
  --muted: #667085;
  --accent: #1f6feb;
  --ok: #16833a;
  --warn: #9a6700;
  --bad: #c32f27;
  --chip: #eef2f7;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
</style>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  min-height: 100vh;
  transition: grid-template-columns .2s;
}
.layout.collapsed {
  grid-template-columns: 60px 1fr;
}
.sidebar {
  background: var(--panel);
  border-right: 1px solid var(--line);
  padding: 16px 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 16px;
  font-size: 18px;
  font-weight: 650;
  border-bottom: 1px solid var(--line);
  margin-bottom: 8px;
  white-space: nowrap;
}
.collapsed .sidebar-brand {
  justify-content: center;
  padding: 0 0 16px;
  font-size: 20px;
}
.collapse-btn {
  background: none;
  border: 1px solid var(--line);
  border-radius: 4px;
  width: 24px;
  height: 24px;
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background .15s;
}
.collapse-btn:hover {
  background: var(--bg);
  color: var(--text);
}
.collapsed .collapse-btn {
  display: none;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  color: var(--text);
  text-decoration: none;
  font-size: 14px;
  transition: background .1s;
  white-space: nowrap;
}
.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
}
.nav-item:hover {
  background: var(--bg);
  text-decoration: none;
}
.nav-item.active {
  background: #eef5ff;
  color: var(--accent);
  font-weight: 600;
  border-right: 3px solid var(--accent);
}
.collapsed .nav-item.active {
  border-right: none;
}
.nav-icon { font-size: 16px; flex-shrink: 0; }
.collapsed .nav-text { display: none; }
.content {
  padding: 20px 24px;
  min-width: 0;
}
@media (max-width: 768px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
}
</style>
