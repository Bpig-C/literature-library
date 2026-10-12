<template>
  <div class="app-shell" :class="{'sidebar-collapsed':sidebarCollapsed}">
    <button class="mobile-menu" type="button" aria-label="打开导航" @click="sidebarOpen = true">
      <AppIcon name="menu" />
    </button>

    <div v-if="sidebarOpen" class="sidebar-scrim" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <router-link to="/" class="brand" @click="closeSidebar">
        <span class="brand-mark"><AppIcon name="spark" /></span>
        <span class="brand-copy">
          <strong>Scholar OS</strong>
        </span>
      </router-link>

      <button class="desktop-sidebar-toggle" type="button" :aria-label="sidebarCollapsed ? '展开主导航' : '收起主导航'" :title="sidebarCollapsed ? '展开主导航' : '收起主导航'" @click="toggleSidebar">{{ sidebarCollapsed ? '›' : '‹' }}</button>

      <nav class="navigation" aria-label="主导航">
        <div v-for="group in navigation" :key="group.label" class="nav-section">
          <div class="nav-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item) }"
            @click="closeSidebar"
          >
            <AppIcon :name="item.icon" />
            <span>{{ item.label }}</span>
            <span v-if="item.ai" class="ai-dot" title="智能探索"></span>
          </router-link>
        </div>
        <button
          class="nav-item auxiliary-toggle"
          type="button"
          :aria-expanded="auxiliaryOpen"
          @click="toggleAuxiliary"
        >
          <AppIcon name="review" />
          <span>维护与旧流程</span>
          <i>{{ auxiliaryOpen ? '−' : '+' }}</i>
        </button>
        <div v-if="auxiliaryOpen" class="nav-section auxiliary-section">
          <div class="nav-label">兼容入口</div>
          <router-link
            v-for="item in auxiliaryNavigation"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item) }"
            @click="closeSidebar"
          >
            <AppIcon :name="item.icon" />
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar-footer">
        <p>整理原文证据、解释与分类，为研究综述做准备</p>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ currentGroup }}</p>
          <h1>{{ currentTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <router-link to="/research" class="explore-button">
            <AppIcon name="spark" />
            <span>研究整理</span>
          </router-link>
          <span class="system-status"><i></i> 本地知识库</span>
        </div>
      </header>

      <main class="content">
        <div v-if="readOnly" class="readonly-banner" role="status">
          只读模式：当前为远程只读部署，上传 / 重新解析 / 隔离 / 删除 / 提交等写操作已被服务端禁用（403）。读取、检索与导出不受影响；正式写入须先完成权威交接。
        </div>
        <slot />
      </main>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { useRuntimeMode } from '../composables/useRuntimeMode'

const { readOnly } = useRuntimeMode()
const route = useRoute()
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(window.localStorage.getItem('scholar-sidebar-collapsed') === '1')
const auxiliaryOpen = ref(window.localStorage.getItem('scholar-auxiliary-open') === '1')

const navigation = [
  { label: '工作台', items: [
    { to: '/', label: '研究总览', icon: 'home', exact: true },
    { to: '/works', label: '文献库', icon: 'library', prefix: '/works' },
    { to: '/research', label: '研究视图', icon: 'research', prefix: '/research', exclude: ['/research/ontology'] },
    { to: '/research/ontology', label: '风险分类体系', icon: 'topics' },
  ]},
  { label: '文献准备', items: [
    { to: '/ingest', label: '文献入库', icon: 'ingest', aliases: ['/inbox'] },
    { to: '/pipeline', label: '处理流程', icon: 'pipeline' },
    { to: '/metadata-workspace', label: '元数据工作台', icon: 'metadata' },
  ]},
  { label: '库务', items: [
    { to: '/duplicates', label: '重复项', icon: 'duplicates' },
    { to: '/relations', label: '文献关系', icon: 'relations' },
  ]},
]

const auxiliaryNavigation = [
  { to: '/discovery', label: '辅助检索（旧）', icon: 'discovery' },
  { to: '/topics', label: '主题闸门（旧）', icon: 'topics' },
  { to: '/intake', label: '候选入库复核', icon: 'review' },
  { to: '/metadata', label: '书目候选复核', icon: 'metadata' },
  { to: '/classification', label: '历史分类（只读）', icon: 'classify' },
  { to: '/templates', label: '旧抽取模板', icon: 'templates' },
]

const currentTitle = computed(() => route.meta?.title || '研究总览')
const currentGroup = computed(() => route.meta?.group || '学术工作台')

function isActive(item) {
  if (item.exact) return route.path === item.to
  if (item.prefix && route.path.startsWith(item.prefix) && !item.exclude?.some(path => route.path.startsWith(path))) return true
  return route.path === item.to || item.aliases?.includes(route.path)
}

function closeSidebar() {
  sidebarOpen.value = false
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  window.localStorage.setItem('scholar-sidebar-collapsed', sidebarCollapsed.value ? '1' : '0')
}

function toggleAuxiliary() {
  auxiliaryOpen.value = !auxiliaryOpen.value
  window.localStorage.setItem('scholar-auxiliary-open', auxiliaryOpen.value ? '1' : '0')
}
</script>

<style>
:root {
  color-scheme: light;
  --accent: #0d9373;
  --accent-hover: #087e63;
  --accent-subtle: #e9f7f2;
  --accent-mute: #9dd8c7;
  --accent-ink: #075e4b;
  --text-primary: #20201f;
  --text-secondary: #696965;
  --text-tertiary: #999993;
  --border: #e7e7e3;
  --border-strong: #d7d7d1;
  --bg-page: #f7f7f4;
  --bg-surface: #ffffff;
  --bg-muted: #f0f0ec;
  --sidebar-bg: #171817;
  --sidebar-surface: #222321;
  --ok: #16865e;
  --ok-bg: #e4f5ed;
  --ok-fg: #11704f;
  --ok-border: #9fd3bc;
  --warn: #b66a18;
  --warn-bg: #fff3df;
  --warn-fg: #8d5011;
  --warn-border: #e6c189;
  --bad: #c4473a;
  --bad-bg: #fcebe8;
  --bad-fg: #a4382e;
  --bad-border: #e7aaa2;
  --info: #3478b9;
  --info-bg: #eaf3fb;
  --info-fg: #276398;
  --info-border: #a8cae8;
  --neutral: #777772;
  --neutral-bg: #f0f0ec;
  --neutral-fg: #555551;
  --neutral-border: #cdcdc7;
  --selected-bg: #e9f7f2;
  --selected-border: #0d9373;
  --fix: #b66a18;
  --fix-bg: #fff3df;
  --fix-fg: #8d5011;
  --radius-sm: 7px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 18px;
  --shadow-sm: 0 1px 2px rgba(24, 24, 22, .04), 0 3px 10px rgba(24, 24, 22, .03);
  --shadow-md: 0 10px 30px rgba(24, 24, 22, .07);
  --shadow-lg: 0 24px 70px rgba(24, 24, 22, .15);
  --shadow-focus: 0 0 0 3px rgba(13, 147, 115, .11);
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --font-sans: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --font-mono: "SFMono-Regular", "Cascadia Code", Consolas, monospace;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 26px;
  --line-height-tight: 1.3;
  --line-height-normal: 1.55;
  --line-height-relaxed: 1.7;
  --transition-fast: .14s ease;
  --transition-normal: .22s ease;
  --transition-slow: .32s ease;
  --sidebar-width: 238px;
  --topbar-height: 76px;
  --pdf-drawer-width-desktop: 420px;
  --pdf-drawer-width-tablet: 340px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { background: var(--sidebar-bg); }
body {
  min-width: 320px;
  background: var(--bg-page);
  color: var(--text-primary);
  font: var(--text-md)/var(--line-height-normal) var(--font-sans);
  -webkit-font-smoothing: antialiased;
}
button, input, select, textarea { font: inherit; }
a { color: var(--accent-ink); text-decoration: none; }
a:hover { text-decoration: none; }
::selection { background: rgba(13, 147, 115, .18); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.app-shell { min-height: 100vh; background: var(--bg-page); }
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 200;
  display: flex;
  width: var(--sidebar-width);
  flex-direction: column;
  overflow-y: auto;
  color: #ecece8;
  background: var(--sidebar-bg);
  border-right: 1px solid rgba(255,255,255,.055);
}
.desktop-sidebar-toggle { position: absolute; top: 22px; right: 8px; z-index: 2; width: 27px; height: 31px; padding: 0; color: #ddd; border: 1px solid rgba(255,255,255,.13); border-radius: 7px; background: rgba(255,255,255,.05); cursor: pointer; font-size: 20px; line-height: 1; }
.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: var(--topbar-height);
  padding: 15px 17px;
  color: #fff;
}
.brand-mark {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border-radius: 11px;
  color: #062d24;
  background: linear-gradient(145deg, #8ce6cd, #25b994);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.45), 0 6px 20px rgba(21,169,133,.18);
}
.brand-mark .app-icon { width: 20px; height: 20px; stroke-width: 1.8; }
.brand-copy { display: flex; min-width: 0; flex-direction: column; line-height: 1.2; }
.brand-copy strong { font-size: 14px; font-weight: 620; letter-spacing: -.01em; }
.brand-copy small { margin-top: 4px; color: #898b87; font-size: 10px; letter-spacing: .03em; }
.navigation { flex: 1; padding: 8px 10px 18px; }
.nav-section + .nav-section { margin-top: 18px; }
.nav-label { padding: 0 10px 7px; color: #6f716d; font-size: 10px; font-weight: 620; letter-spacing: .08em; }
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  height: 39px;
  padding: 0 11px;
  color: #aaaCA8;
  border-radius: 9px;
  font-size: 13px;
  transition: color var(--transition-fast), background var(--transition-fast), transform var(--transition-fast);
}
.nav-item + .nav-item { margin-top: 2px; }
.nav-item .app-icon { width: 17px; height: 17px; flex: 0 0 17px; }
.nav-item:hover { color: #f5f5f2; background: rgba(255,255,255,.055); }
.nav-item.active { color: #fff; background: var(--sidebar-surface); box-shadow: inset 0 0 0 1px rgba(255,255,255,.035); }
.nav-item.active::before { content: ''; position: absolute; left: -10px; width: 3px; height: 18px; border-radius: 0 3px 3px 0; background: #35bd99; }
.auxiliary-toggle { width: 100%; margin-top: 18px; border: 0; background: transparent; text-align: left; cursor: pointer; }
.auxiliary-toggle i { margin-left: auto; color: #6f716d; font-style: normal; }
.auxiliary-section { margin-top: 6px !important; padding-top: 8px; border-top: 1px solid rgba(255,255,255,.06); }
.ai-dot { width: 5px; height: 5px; margin-left: auto; border-radius: 50%; background: #4dd4ad; box-shadow: 0 0 9px #4dd4ad; }
.sidebar-footer { padding: 12px; border-top: 1px solid rgba(255,255,255,.06); }
.sidebar-footer p { margin: 9px 4px 0; color: #656863; font-size: 9px; line-height: 1.5; }
.workspace { min-height: 100vh; margin-left: var(--sidebar-width); }
.sidebar,.workspace { transition: width var(--transition-normal),margin-left var(--transition-normal); }
.app-shell.sidebar-collapsed .sidebar { width: 64px; }
.app-shell.sidebar-collapsed .workspace { margin-left: 64px; }
.app-shell.sidebar-collapsed .brand { padding-left: 14px; }
.app-shell.sidebar-collapsed .brand-copy,.app-shell.sidebar-collapsed .nav-label,.app-shell.sidebar-collapsed .nav-item span,.app-shell.sidebar-collapsed .sidebar-footer { display: none; }
.app-shell.sidebar-collapsed .navigation { padding-inline: 9px; }
.app-shell.sidebar-collapsed .nav-item { justify-content: center; padding: 0; }
.app-shell.sidebar-collapsed .desktop-sidebar-toggle { top: 66px; right: 17px; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  min-height: var(--topbar-height);
  align-items: center;
  justify-content: space-between;
  padding: 12px 32px;
  background: rgba(247,247,244,.88);
  border-bottom: 1px solid rgba(215,215,209,.72);
  backdrop-filter: blur(18px) saturate(150%);
}
.topbar .eyebrow { color: var(--text-tertiary); font-size: 10px; font-weight: 650; letter-spacing: .09em; text-transform: uppercase; }
.topbar h1 { margin-top: 2px; font-size: 18px; font-weight: 600; letter-spacing: -.025em; }
.topbar-actions { display: flex; align-items: center; gap: 14px; }
.explore-button { display: inline-flex; height: 36px; align-items: center; gap: 8px; padding: 0 13px; color: #fff; border-radius: 10px; background: #242522; font-size: 12px; font-weight: 540; transition: transform var(--transition-fast), background var(--transition-fast); }
.explore-button:hover { background: #0d9373; transform: translateY(-1px); }
.explore-button .app-icon { width: 15px; }
.system-status { display: inline-flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 11px; }
.system-status i { width: 6px; height: 6px; border-radius: 50%; background: #20a879; box-shadow: 0 0 0 3px rgba(32,168,121,.12); }
.content { min-width: 0; padding: 30px 34px 48px; }

.readonly-banner {
  margin: 0 0 14px 0;
  padding: 8px 12px;
  border: 1px solid #e8c88a;
  border-left: 4px solid #b66a18;
  border-radius: 8px;
  background: #fdf6e9;
  color: #7a4b0e;
  font-size: 13px;
  line-height: 1.6;
}
.mobile-menu, .sidebar-scrim { display: none; }

@media (max-width: 900px) {
  .workspace { margin-left: 0; }
  .sidebar { transform: translateX(-100%); transition: transform var(--transition-normal); box-shadow: var(--shadow-lg); }
  .sidebar.open { transform: translateX(0); }
  .sidebar-scrim { position: fixed; inset: 0; z-index: 190; display: block; background: rgba(0,0,0,.38); backdrop-filter: blur(2px); }
  .mobile-menu { position: fixed; top: 20px; left: 16px; z-index: 120; display: grid; width: 36px; height: 36px; place-items: center; color: var(--text-primary); border: 1px solid var(--border); border-radius: 10px; background: rgba(255,255,255,.82); }
  .desktop-sidebar-toggle { display: none; }
  .app-shell.sidebar-collapsed .sidebar { width: var(--sidebar-width); }
  .app-shell.sidebar-collapsed .workspace { margin-left: 0; }
  .app-shell.sidebar-collapsed .brand { padding-left: 17px; }
  .app-shell.sidebar-collapsed .brand-copy,.app-shell.sidebar-collapsed .nav-label,.app-shell.sidebar-collapsed .nav-item span,.app-shell.sidebar-collapsed .sidebar-footer { display: initial; }
  .app-shell.sidebar-collapsed .navigation { padding: 8px 10px 18px; }
  .app-shell.sidebar-collapsed .nav-item { justify-content: flex-start; padding: 0 11px; }
  .topbar { padding-left: 64px; }
}

@media (max-width: 620px) {
  .topbar { min-height: 68px; padding-right: 16px; }
  .topbar-actions .system-status { display: none; }
  .explore-button span { display: none; }
  .explore-button { width: 36px; padding: 0; justify-content: center; }
  .content { padding: 22px 16px 36px; }
}
</style>
