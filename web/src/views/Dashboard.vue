<template>
  <div class="dashboard">
    <h1 class="page-title">总览</h1>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-number">{{ stats.total }}</div>
        <div class="stat-label">文献总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ stats.unread }}</div>
        <div class="stat-label">未读</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ stats.quarantined }}</div>
        <div class="stat-label">已隔离</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ stats.relations }}</div>
        <div class="stat-label">关系</div>
      </div>
    </div>

    <!-- 待办队列 -->
    <div class="section">
      <h2 class="section-title">待办队列</h2>
      <div class="queue-grid">
        <router-link to="/inbox" class="queue-card">
          <div class="queue-icon">📥</div>
          <div class="queue-info">
            <div class="queue-count">{{ queue.ingest }}</div>
            <div class="queue-label">待摄入</div>
          </div>
        </router-link>

        <router-link to="/pipeline" class="queue-card">
          <div class="queue-icon">📄</div>
          <div class="queue-info">
            <div class="queue-count">{{ queue.parse }}</div>
            <div class="queue-label">待解析</div>
          </div>
        </router-link>

        <router-link to="/metadata" class="queue-card">
          <div class="queue-icon">🏷️</div>
          <div class="queue-info">
            <div class="queue-count">{{ queue.metadata }}</div>
            <div class="queue-label">元数据待审</div>
          </div>
        </router-link>

        <router-link to="/classification" class="queue-card">
          <div class="queue-icon">📋</div>
          <div class="queue-info">
            <div class="queue-count">{{ queue.classify }}</div>
            <div class="queue-label">分类待审</div>
          </div>
        </router-link>

        <router-link to="/duplicates" class="queue-card">
          <div class="queue-icon">🔍</div>
          <div class="queue-info">
            <div class="queue-count">{{ queue.duplicates }}</div>
            <div class="queue-label">待去重</div>
          </div>
        </router-link>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="section">
      <h2 class="section-title">快捷入口</h2>
      <div class="links-grid">
        <router-link to="/works" class="link-card">
          <div class="link-icon">📚</div>
          <div class="link-title">文献库</div>
          <div class="link-desc">搜索、筛选、编辑元数据</div>
        </router-link>
        <router-link to="/pipeline" class="link-card">
          <div class="link-icon">⚡</div>
          <div class="link-title">流程管理</div>
          <div class="link-desc">批量触发解析和抽取</div>
        </router-link>
        <router-link to="/topics" class="link-card">
          <div class="link-icon">🗂️</div>
          <div class="link-title">主题闸门</div>
          <div class="link-desc">管理研究主题和成熟度</div>
        </router-link>
        <router-link to="/discovery" class="link-card">
          <div class="link-icon">🔎</div>
          <div class="link-title">发现检索</div>
          <div class="link-desc">AI 辅助文献发现</div>
        </router-link>
      </div>
    </div>

    <!-- 类型分布 -->
    <div class="section" v-if="stats.docTypes">
      <h2 class="section-title">类型分布</h2>
      <div class="chips">
        <span class="chip" v-for="(count, type) in stats.docTypes" :key="type">
          {{ label(DOC_TYPE_LABELS, type) }}: {{ count }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getWorks, getMetadataExtractions, getClassificationExtractions, getIngestPlan, parseStatus, getDuplicates } from '../api'
import { DOC_TYPE_LABELS, label } from '../labels'

const stats = ref({
  total: 0,
  unread: 0,
  quarantined: 0,
  relations: 0,
  docTypes: {},
})

const queue = ref({
  ingest: 0,
  parse: 0,
  metadata: 0,
  classify: 0,
  duplicates: 0,
})

async function loadStats() {
  try {
    const worksRes = await getWorks({ per_page: 1 })
    const summary = worksRes.summary || {}
    stats.value.total = summary.total || 0
    stats.value.unread = summary.statuses?.unread || 0
    stats.value.quarantined = summary.statuses?.quarantined || 0
    stats.value.relations = summary.relations || 0
    stats.value.docTypes = summary.doc_types || {}
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

async function loadQueue() {
  try {
    const [ingestRes, parseRes, metaRes, classRes, dupRes] = await Promise.allSettled([
      getIngestPlan(),
      parseStatus(),
      getMetadataExtractions({ status: 'pending', per_page: 1 }),
      getClassificationExtractions({ status: 'pending', per_page: 1 }),
      getDuplicates({ per_page: 1 }),
    ])

    if (ingestRes.status === 'fulfilled') {
      queue.value.ingest = ingestRes.value.summary?.ingests || 0
    }
    if (parseRes.status === 'fulfilled') {
      queue.value.parse = parseRes.value.pending || 0
    }
    if (metaRes.status === 'fulfilled') {
      queue.value.metadata = metaRes.value.total || 0
    }
    if (classRes.status === 'fulfilled') {
      queue.value.classify = classRes.value.total || 0
    }
    if (dupRes.status === 'fulfilled') {
      queue.value.duplicates = dupRes.value.total || 0
    }
  } catch (e) {
    console.error('Failed to load queue:', e)
  }
}

onMounted(() => {
  loadStats()
  loadQueue()
})
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
}

.page-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-6);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-8);
}

.stat-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
}

.stat-number {
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  margin-bottom: var(--space-1);
}

.stat-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.section {
  margin-bottom: var(--space-8);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}

.queue-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-4);
}

.queue-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  color: inherit;
  transition: all var(--transition-fast);
}

.queue-card:hover {
  border-color: var(--accent);
  box-shadow: var(--shadow-sm);
}

.queue-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.queue-count {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.queue-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: var(--space-1);
}

.links-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}

.link-card {
  display: block;
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  color: inherit;
  transition: all var(--transition-fast);
}

.link-card:hover {
  border-color: var(--accent);
  box-shadow: var(--shadow-sm);
}

.link-icon {
  font-size: 24px;
  margin-bottom: var(--space-3);
}

.link-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-1);
}

.link-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.chip {
  padding: var(--space-1) var(--space-3);
  border-radius: 999px;
  background: var(--bg-muted);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
</style>
