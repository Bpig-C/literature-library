<template>
  <div class="layout">
    <nav class="sidebar">
      <div class="sidebar-brand">文献库</div>
      <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }">
        <span class="nav-icon">📊</span>总览
      </router-link>
      <router-link to="/works" class="nav-item" :class="{ active: $route.path.startsWith('/works') }">
        <span class="nav-icon">📚</span>文献
      </router-link>
      <router-link to="/duplicates" class="nav-item" :class="{ active: $route.path === '/duplicates' }">
        <span class="nav-icon">🔍</span>去重
      </router-link>
      <router-link to="/relations" class="nav-item" :class="{ active: $route.path === '/relations' }">
        <span class="nav-icon">🔗</span>关系
      </router-link>
    </nav>
    <main class="content">
      <slot />
    </main>
  </div>
</template>

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
}
.sidebar {
  background: var(--panel);
  border-right: 1px solid var(--line);
  padding: 16px 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}
.sidebar-brand {
  padding: 0 16px 16px;
  font-size: 18px;
  font-weight: 650;
  border-bottom: 1px solid var(--line);
  margin-bottom: 8px;
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
.nav-icon { font-size: 16px; }
.content {
  padding: 20px 24px;
  min-width: 0;
}
@media (max-width: 768px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
}
</style>
