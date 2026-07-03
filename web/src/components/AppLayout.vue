<template>
  <div class="layout" :class="{ 'sidebar-expanded': isExpanded }">
    <!-- 顶部栏 -->
    <header class="topbar">
      <div class="topbar-left">
        <span class="logo">📚 文献库</span>
        <span class="breadcrumb">{{ currentTitle }}</span>
      </div>
    </header>

    <!-- 侧边栏 -->
    <nav
      class="sidebar"
      @mouseenter="isExpanded = true"
      @mouseleave="isExpanded = false"
    >
      <div class="sidebar-brand">
        <span class="brand-icon">文</span>
        <span class="brand-text">文献库</span>
      </div>

      <!-- 顶层 -->
      <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }" title="总览">
        <span class="nav-icon">📊</span><span class="nav-text">总览</span>
      </router-link>
      <router-link to="/works" class="nav-item" :class="{ active: $route.path.startsWith('/works') }" title="文献">
        <span class="nav-icon">📚</span><span class="nav-text">文献</span>
      </router-link>

      <!-- 流程 -->
      <div class="nav-group">流程</div>
      <router-link to="/pipeline" class="nav-item" :class="{ active: $route.path === '/pipeline' }" title="流程管理">
        <span class="nav-icon">⚡</span><span class="nav-text">流程管理</span>
      </router-link>
      <router-link to="/topics" class="nav-item" :class="{ active: $route.path === '/topics' }" title="主题闸门">
        <span class="nav-icon">🗂️</span><span class="nav-text">主题闸门</span>
      </router-link>
      <router-link to="/discovery" class="nav-item" :class="{ active: $route.path === '/discovery' }" title="发现检索">
        <span class="nav-icon">🔎</span><span class="nav-text">发现检索</span>
      </router-link>
      <router-link to="/ingest" class="nav-item" :class="{ active: $route.path === '/ingest' || $route.path === '/inbox' }" title="文献入库">
        <span class="nav-icon">📥</span><span class="nav-text">文献入库</span>
      </router-link>
      <router-link to="/intake" class="nav-item" :class="{ active: $route.path === '/intake' }" title="采集审核">
        <span class="nav-icon">✅</span><span class="nav-text">采集审核</span>
      </router-link>
      <router-link to="/metadata" class="nav-item" :class="{ active: $route.path === '/metadata' }" title="元数据审核">
        <span class="nav-icon">🏷️</span><span class="nav-text">元数据审核</span>
      </router-link>
      <router-link to="/classification" class="nav-item" :class="{ active: $route.path === '/classification' }" title="分类审核">
        <span class="nav-icon">📋</span><span class="nav-text">分类审核</span>
      </router-link>

      <!-- 库内 -->
      <div class="nav-group">库内</div>
      <router-link to="/duplicates" class="nav-item" :class="{ active: $route.path === '/duplicates' }" title="去重">
        <span class="nav-icon">🔍</span><span class="nav-text">去重</span>
      </router-link>
      <router-link to="/relations" class="nav-item" :class="{ active: $route.path === '/relations' }" title="关系图">
        <span class="nav-icon">🔗</span><span class="nav-text">关系图</span>
      </router-link>

      <!-- 系统 -->
      <div class="nav-group">系统</div>
      <router-link to="/templates" class="nav-item" :class="{ active: $route.path === '/templates' }" title="模板管理">
        <span class="nav-icon">📑</span><span class="nav-text">模板管理</span>
      </router-link>
    </nav>

    <!-- 内容区 -->
    <main class="content">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isExpanded = ref(false)

const currentTitle = computed(() => route.meta?.title || '总览')
</script>

<style>
:root {
  color-scheme: light;

  /* === 主色调 === */
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --accent-subtle: #eff6ff;
  --accent-mute: #93c5fd;

  /* === 中性色 === */
  --text-primary: #111827;
  --text-secondary: #4b5563;
  --text-tertiary: #9ca3af;
  --border: #e5e7eb;
  --border-strong: #d1d5db;
  --bg-page: #f9fafb;
  --bg-surface: #ffffff;
  --bg-muted: #f3f4f6;

  /* === 状态色（三元组 + border） === */
  --ok: #16a34a;
  --ok-bg: #dcfce7;
  --ok-fg: #15803d;
  --ok-border: #16a34a;

  --warn: #d97706;
  --warn-bg: #fef9c3;
  --warn-fg: #92400e;
  --warn-border: #d97706;

  --bad: #dc2626;
  --bad-bg: #fee2e2;
  --bad-fg: #991b1b;
  --bad-border: #dc2626;

  --info: #2563eb;
  --info-bg: #dbeafe;
  --info-fg: #0369a1;
  --info-border: #2563eb;

  --neutral: #6b7280;
  --neutral-bg: #f3f4f6;
  --neutral-fg: #374151;
  --neutral-border: #6b7280;

  --selected-bg: #eff6ff;
  --selected-border: #2563eb;

  --fix: #d97706;
  --fix-bg: #fef3c7;
  --fix-fg: #92400e;

  /* === 圆角 === */
  --radius-sm: 3px;
  --radius-md: 4px;
  --radius-lg: 6px;
  --radius-xl: 8px;

  /* === 阴影 === */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.18);
  --shadow-focus: 0 0 0 2px rgba(37,99,235,0.25);

  /* === 间距 === */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;

  /* === 字体 === */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  --font-mono: "SF Mono", "Cascadia Code", "Consolas", monospace;

  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 18px;
  --text-2xl: 20px;

  --line-height-tight: 1.3;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.6;

  /* === 过渡 === */
  --transition-fast: 0.1s ease;
  --transition-normal: 0.15s ease;
  --transition-slow: 0.2s ease;

  /* === 布局 === */
  --sidebar-collapsed-width: 56px;
  --sidebar-expanded-width: 200px;
  --sidebar-transition: width 0.2s ease;
  --topbar-height: 48px;
  --pdf-drawer-width-desktop: 420px;
  --pdf-drawer-width-tablet: 340px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg-page);
  color: var(--text-primary);
  font: var(--text-md)/var(--line-height-normal) var(--font-sans);
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>

<style scoped>
.layout {
  display: grid;
  grid-template-rows: var(--topbar-height) 1fr;
  grid-template-columns: var(--sidebar-collapsed-width) 1fr;
  min-height: 100vh;
  transition: grid-template-columns var(--transition-normal);
}

.layout.sidebar-expanded {
  grid-template-columns: var(--sidebar-expanded-width) 1fr;
}

/* 顶部栏 */
.topbar {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  height: var(--topbar-height);
  position: sticky;
  top: 0;
  z-index: 100;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.logo {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.breadcrumb {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  padding-left: var(--space-4);
  border-left: 1px solid var(--border);
}

/* 侧边栏 */
.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  padding: var(--space-3) 0;
  position: sticky;
  top: var(--topbar-height);
  height: calc(100vh - var(--topbar-height));
  overflow-y: auto;
  overflow-x: hidden;
  transition: width var(--transition-normal);
  width: var(--sidebar-collapsed-width);
}

.sidebar-expanded .sidebar {
  width: var(--sidebar-expanded-width);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-2);
  border-bottom: 1px solid var(--border);
}

.brand-icon {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--accent);
  flex-shrink: 0;
}

.brand-text {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  opacity: 0;
  width: 0;
  overflow: hidden;
  transition: opacity var(--transition-fast), width var(--transition-fast);
}

.sidebar-expanded .brand-text {
  opacity: 1;
  width: auto;
}

/* 导航项 */
.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  margin: 1px 0;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: var(--text-sm);
  transition: all var(--transition-fast);
  white-space: nowrap;
  border-left: 3px solid transparent;
}

.nav-item:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
  text-decoration: none;
}

.nav-item.active {
  background: var(--accent-subtle);
  color: var(--accent);
  font-weight: 500;
  border-left-color: var(--accent);
}

.nav-icon {
  font-size: 16px;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.nav-text {
  opacity: 0;
  width: 0;
  overflow: hidden;
  transition: opacity var(--transition-fast), width var(--transition-fast);
}

.sidebar-expanded .nav-text {
  opacity: 1;
  width: auto;
}

/* 导航分组 */
.nav-group {
  font-size: var(--text-xs);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  padding: var(--space-4) var(--space-4) var(--space-1);
  margin: 0;
  white-space: nowrap;
}

/* 内容区 */
.content {
  padding: var(--space-5) var(--space-6);
  min-width: 0;
  background: var(--bg-page);
}

/* 响应式 */
@media (max-width: 768px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    display: none;
  }

  .topbar {
    padding: 0 var(--space-4);
  }
}
</style>
