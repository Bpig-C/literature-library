<template>
  <div>
    <h1>去重确认</h1>
    <div class="toolbar">
      <select v-model="typeFilter">
        <option value="all">类型：全部</option>
        <option value="exact_sha256">SHA256 完全相同</option>
        <option value="title_candidate">标题相似</option>
      </select>
      <select v-model="statusFilter">
        <option value="needsreview">需审查</option>
        <option value="all">状态：全部</option>
        <option value="pending">未决策</option>
        <option value="confirmed">已自动确认</option>
      </select>
      <input v-model="search" placeholder="搜索标题、ID..." />
    </div>

    <div class="stats-bar">
      <div class="stat-card"><b>{{ filtered.length }}</b><span>重复组</span></div>
      <div class="stat-card"><b>{{ filteredAutoCount }}</b><span>已自动确认</span></div>
      <div class="stat-card"><b>{{ filtered.length - filteredAutoCount }}</b><span>需审查</span></div>
    </div>

    <details class="decision-help">
      <summary>📋 各决策按钮的含义与后果（点击展开/收起）</summary>
      <table class="help-table">
        <thead>
          <tr><th>决策</th><th>含义</th><th>数据库动作</th><th>物理动作</th><th>性质</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>同一作品 <code>same_work</code></td>
            <td>同一篇文献的不同来源副本</td>
            <td>写 same_work 关系；<b>标题相似组</b>触发合并：按 arXiv/DOI/文件大小/标签数评分，选最优作主文献</td>
            <td>副本文献源文件归档到 <code>_archive/dedup/</code>，副本文献设为 quarantined</td>
            <td class="cell-bad">有损·合并</td>
          </tr>
          <tr>
            <td>版本关系 <code>version_of</code></td>
            <td>同一系列的不同版本（如 2025 / 2026、v1 / v2）</td>
            <td>写 version_of 关系</td>
            <td>无</td>
            <td class="cell-ok">无损</td>
          </tr>
          <tr>
            <td>翻译关系 <code>translation_of</code></td>
            <td>互为不同语言译本</td>
            <td>写 translation_of 关系</td>
            <td>无</td>
            <td class="cell-ok">无损</td>
          </tr>
          <tr>
            <td>取代关系 <code>supersedes</code></td>
            <td>后作取代前作（<b>有方向</b>：组内前者 → 后者）</td>
            <td>写 supersedes 关系</td>
            <td>无</td>
            <td class="cell-ok">无损</td>
          </tr>
          <tr>
            <td>部分关系 <code>part_of</code></td>
            <td>一篇是另一篇的一部分（<b>有方向</b>）</td>
            <td>写 part_of 关系</td>
            <td>无</td>
            <td class="cell-ok">无损</td>
          </tr>
          <tr>
            <td>非重复 <code>not_duplicate</code></td>
            <td>标题像但其实是不同文献</td>
            <td>写 not_duplicate 关系</td>
            <td>无</td>
            <td class="cell-ok">无损·不再提示</td>
          </tr>
          <tr>
            <td>隔离 <code>quarantine</code></td>
            <td>文献无价值或坏源</td>
            <td>read_status=quarantined + bad_source（作用于组内<b>所有</b>文献）</td>
            <td>源文件移入 <code>_quarantine/{work_id}/</code></td>
            <td class="cell-bad">有损·退出主库</td>
          </tr>
        </tbody>
      </table>
      <p class="help-note">
        所有决策都会把本组标记为"已决策"并移出待审队列。只有 <b>同一作品（标题相似组）</b> 与 <b>隔离</b> 会移动/归档文件，其余仅建立关系、完全可逆。<b>拿不准时优先选关系型（版本/翻译/取代/部分/非重复）</b>。
      </p>
      <div class="rule-box">
        <div class="rule-title">🔍 判定规则速查</div>
        <div class="rule-row"><b>同一作品 vs 版本关系</b> —— 关键问题：<i>合并会不会丢失独立的文献内容？</i></div>
        <ul class="rule-list">
          <li><b>同一作品 same_work</b>：是<b>同一篇</b>的不同来源副本。SHA256 相同，或标题+作者+年份+DOI/arXiv 全一致，内容完全相同。合并不丢信息。</li>
          <li><b>版本关系 version_of</b>：同系列/同工作的<b>不同版本</b>（年份 2025/2026、v1/v2、preprint/published、GPT-5/5.5）。内容确实不同。<b>合并会丢内容 → 选 version_of，两篇都保留</b>。</li>
          <li><b>守则：拿不准一律选 version_of（无损可逆）</b>；只有"真是同一份、合并不丢东西"才 same_work。</li>
        </ul>
        <div class="rule-row"><b>假阳性识别（标题相似但非重复）</b></div>
        <ul class="rule-list">
          <li>标题共享骨架词（如 NIST / RMF / Crosswalk / ISO）被凑对，但<b>标准号/版本号不同、实际是不同文献</b> → 选 <b>非重复 not_duplicate</b>。</li>
          <li>看到相似度 100% 但标题明显不同，多半是归一化把区分号剥光导致的假阳性 —— 以<b>实际内容/PDF</b>为准。</li>
        </ul>
      </div>
    </details>

    <div v-for="g in filtered" :key="g.id" class="group-card">
      <div class="group-header">
        <div>
          <span class="group-id">{{ g.id }}</span>
          <span class="chip">{{ g.duplicate_type === 'exact_sha256' ? 'SHA256 相同' : '标题相似' }}</span>
          <span class="muted tiny">{{ g.candidates.length }} 个来源 · {{ g.work_ids.length }} 个作品</span>
        </div>
        <span :class="'badge ' + badgeClass(g)">{{ badgeText(g) }}</span>
      </div>

        <div class="cand-grid">
        <div v-for="c in g.candidates" :key="c.id" class="cand-card">
          <div class="cand-title">{{ c.work_title || c.work_id }}</div>
          <div class="cand-meta">
            <div>ID: {{ c.work_id }}</div>
            <div v-if="c.work_year">年份: {{ c.work_year }}</div>
            <div v-if="c.work_doc_type">类型: {{ c.work_doc_type }}</div>
            <div v-if="c.work_language">语言: {{ c.work_language }}</div>
            <div v-if="c.work_arxiv_id">arXiv: <a :href="'https://arxiv.org/abs/' + c.work_arxiv_id" target="_blank">{{ c.work_arxiv_id }}</a></div>
            <div v-if="c.work_doi">DOI: <a :href="'https://doi.org/' + c.work_doi" target="_blank">{{ c.work_doi }}</a></div>
          </div>
          <div class="cand-signals">
            <span v-if="c.source_file_size" class="signal" title="文件大小">📄 {{ formatSize(c.source_file_size) }}</span>
            <span class="signal" title="已审核通过的标签数">🏷️ {{ c.tag_count }}</span>
            <span v-if="c.score" class="signal" title="标题相似度">📊 {{ (c.score * 100).toFixed(0) }}%</span>
            <span v-if="c.content_sha256" class="signal sha"
                  :class="{ 'sha-match': shaMatchesAnother(g, c) }"
                  :title="'SHA256: ' + c.content_sha256 + (shaMatchesAnother(g, c) ? '\n⚠ 与组内其他候选字节相同' : '\n组内唯一')">
              #{{ c.content_sha256.slice(0, 10) }}{{ shaMatchesAnother(g, c) ? ' · 字节相同' : '' }}
            </span>
          </div>
          <div class="cand-source">{{ c.source_original_name || '' }}</div>
          <div class="cand-actions">
            <button class="link-btn" @click="openPdf(c.work_id)" title="在新标签打开 PDF 原文">📑 预览 PDF</button>
          </div>
        </div>
      </div>

      <div v-if="g.auto_confirmed" class="auto-msg">
        ✓ 已自动确认：SHA256 完全相同，属于同一作品的不同来源文件
      </div>
      <div v-else-if="g.candidates.some(c => c.reviewed)" class="auto-msg">
        ✓ 已决策
      </div>
      <div v-else class="decision-section">
        <div class="decision-btns">
          <button
            v-for="dt in DECISION_TYPES" :key="dt[0]"
            :class="[dt[0], { selected: processing[g.id] === dt[0] }]"
            :disabled="!!processing[g.id]"
            @click="onDecision(g, dt[0])"
          >{{ processing[g.id] === dt[0] ? '处理中...' : dt[1] }}</button>
        </div>
      </div>

      <!-- Same-work confirmation modal: human picks primary, machine recommends -->
      <n-modal v-model:show="confirmMerge.show" preset="card" title="确认合并 · 选择主文献" style="width: 580px">
        <p class="modal-desc">机器已按 arXiv/DOI/文件大小/标签数评分，推荐主文献标 <b>⭐</b>。你可改选——<b>未被选中的副本文献将被隔离、源文件归档、标签并入主文献</b>。</p>
        <div v-if="confirmMerge.loadingPreview" class="muted" style="padding:12px">加载评分中…</div>
        <div v-else class="merge-preview">
          <label v-for="c in confirmMerge.candidates" :key="c.work_id"
                 class="merge-item"
                 :class="{ recommended: c.work_id === confirmMerge.recommended, chosen: c.work_id === confirmMerge.chosenPrimary }">
            <input type="radio" name="mergePrimary" :value="c.work_id" v-model="confirmMerge.chosenPrimary" />
            <span class="merge-title">{{ c.title || c.work_id }}</span>
            <span class="muted tiny">{{ c.work_id }}</span>
            <span class="score" title="机器评分：arXiv/DOI 各 +100，文件大小 log2，已审标签数 ×2">得分 {{ c.score }}</span>
            <span v-if="c.work_id === confirmMerge.recommended" class="rec-badge">⭐ 机器推荐</span>
          </label>
        </div>
        <p class="modal-warn">⚠ 合并不可撤销：副本文献设为 quarantined，源文件移入 _archive，标签合并到主文献。</p>
        <template #action>
          <n-button @click="confirmMerge.show = false">取消</n-button>
          <n-button type="error" :disabled="!confirmMerge.chosenPrimary" :loading="confirmMerge.submitting" @click="executeMerge">确认合并</n-button>
        </template>
      </n-modal>
    </div>

    <div class="empty" v-if="!filtered.length">没有匹配的重复组</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { getDuplicates, getMergePreview, reviewDuplicate, pdfUrl } from '../api'

const message = useMessage()
const dialog = useDialog()

const DECISION_TYPES = [
  ['same_work', '同一作品'],
  ['not_duplicate', '非重复'],
  ['version_of', '版本关系'],
  ['translation_of', '翻译关系'],
  ['supersedes', '取代关系'],
  ['part_of', '部分关系'],
  ['quarantine', '隔离'],
]

const allGroups = ref([])
const typeFilter = ref('all')
const statusFilter = ref('needsreview')
const search = ref('')
const processing = ref({})
const confirmMerge = ref({
  show: false, group: null, decision: null,
  candidates: [], recommended: null, chosenPrimary: null,
  loadingPreview: false, submitting: false,
})

const filtered = computed(() => {
  return allGroups.value.filter(g => {
    if (typeFilter.value !== 'all' && g.duplicate_type !== typeFilter.value) return false
    if (statusFilter.value === 'needsreview') {
      if (g.auto_confirmed) return false
      const hasUnreviewed = g.candidates.some(c => !c.reviewed)
      if (!hasUnreviewed) return false
    }
    if (statusFilter.value === 'confirmed' && !g.auto_confirmed) return false
    if (search.value) {
      const q = search.value.toLowerCase()
      const haystack = g.candidates.map(c =>
        [c.work_id, c.work_title, c.source_original_name, g.id].join(' ')
      ).join(' ').toLowerCase()
      if (!haystack.includes(q)) return false
    }
    return true
  })
})

const filteredAutoCount = computed(() => filtered.value.filter(g => g.auto_confirmed).length)

function badgeClass(g) {
  if (g.auto_confirmed) return 'confirmed'
  if (g.candidates.some(c => c.reviewed)) return 'decided'
  return 'pending'
}

function badgeText(g) {
  if (g.auto_confirmed) return '已自动确认'
  if (g.candidates.some(c => c.reviewed)) return '已决策'
  return '待审查'
}

function pairs(g) {
  if (g.duplicate_type === 'exact_sha256') {
    return [{ key: 'group:' + g.id, label: '这组是同一文献？' }]
  }
  const wids = g.work_ids
  const result = []
  for (let i = 0; i < wids.length; i++) {
    for (let j = i + 1; j < wids.length; j++) {
      const tA = g.candidates.find(c => c.work_id === wids[i])?.work_title || wids[i]
      const tB = g.candidates.find(c => c.work_id === wids[j])?.work_title || wids[j]
      result.push({ key: 'pair:' + wids[i] + '|' + wids[j], label: tA + ' → ' + tB })
    }
  }
  return result
}

async function onDecision(group, decision) {
  // For same_work on title_candidate: open modal with machine-scored preview
  if (decision === 'same_work' && group.duplicate_type === 'title_candidate') {
    confirmMerge.value = {
      show: true, group, decision,
      candidates: [], recommended: null, chosenPrimary: null,
      loadingPreview: true, submitting: false,
    }
    try {
      const prev = await getMergePreview(group.id)
      confirmMerge.value.candidates = prev.candidates || []
      confirmMerge.value.recommended = prev.recommended_primary || null
      // Default to machine recommendation; human may override via radio
      confirmMerge.value.chosenPrimary = confirmMerge.value.recommended
    } catch (e) {
      message.error('加载评分失败: ' + (e.message || e))
      confirmMerge.value.show = false
      return
    } finally {
      confirmMerge.value.loadingPreview = false
    }
    return
  }
  // Quarantine is destructive at the file level: it moves every candidate work's
  // source files into _quarantine/. Require explicit confirmation first.
  if (decision === 'quarantine') {
    const count = (group.candidates || []).length
    dialog.warning({
      title: '确认隔离',
      content: `此操作将把该重复组内 ${count} 个候选 work 的源文件移入隔离区（_quarantine/）并标记为 quarantined。可通过各 work 的「恢复」撤销。是否继续？`,
      positiveText: '隔离',
      negativeText: '取消',
      onPositiveClick: () => executeDecision(group, decision),
    })
    return
  }
  // For exact_sha256 or other decisions: execute directly
  executeDecision(group, decision)
}

async function executeMerge() {
  const { group, decision, chosenPrimary } = confirmMerge.value
  confirmMerge.value.submitting = true
  confirmMerge.value.show = false
  try {
    await executeDecision(group, decision, chosenPrimary)
  } finally {
    confirmMerge.value.submitting = false
  }
}

async function executeDecision(group, decision, primaryWorkId = null) {
  const groupId = group.id
  processing.value[groupId] = decision
  try {
    const res = await reviewDuplicate(groupId, decision, '', primaryWorkId)
    if (res.ok) {
      for (const c of group.candidates) {
        c.reviewed = 1
      }
      if (res.actions?.merged) {
        const m = res.actions.merged
        message.success(`已合并：保留 ${m.primary}，归档 ${m.archived_sources} 个源文件，合并 ${m.merged_tags} 个标签`)
      } else {
        message.success('决策已保存')
      }
    }
  } catch (e) {
    message.error('操作失败: ' + (e.message || e))
  } finally {
    delete processing.value[groupId]
  }
}

function shaMatchesAnother(group, cand) {
  const sha = cand.content_sha256
  if (!sha) return false
  return group.candidates.some(c => c !== cand && c.content_sha256 === sha)
}

function openPdf(workId) {
  window.open(pdfUrl(workId), '_blank')
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

onMounted(async () => {
  const res = await getDuplicates()
  allGroups.value = res.groups
})
</script>

<style scoped>
h1 { margin-bottom: 12px; font-size: 22px; }
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.toolbar select, .toolbar input {
  height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit;
}
.stats-bar { display: flex; gap: 10px; margin-bottom: 16px; }
.stat-card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 8px 14px; }
.stat-card b { display: block; font-size: 20px; }
.stat-card span { color: var(--muted); font-size: 12px; }
.group-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-bottom: 14px; }
.group-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #f1f4f8; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 6px; }
.group-id { font-weight: 650; font-size: 15px; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; margin: 0 4px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.confirmed { background: #dcfce7; color: #15803d; }
.badge.decided { background: #d1fae5; color: #065f46; }
.badge.pending { background: #fef9c3; color: #92400e; }
.cand-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; padding: 12px 14px; }
.cand-card { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: #fafbfc; }
.cand-title { font-weight: 600; margin-bottom: 4px; word-break: break-word; }
.cand-meta { font-size: 12px; color: var(--muted); }
.cand-source { font-size: 12px; color: #475467; margin-top: 4px; word-break: break-all; }
.cand-signals { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.signal { font-size: 11px; color: #374151; background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
.auto-msg { padding: 10px 14px; color: #065f46; font-size: 13px; border-top: 1px solid var(--line); }
.decision-section { padding: 12px 14px; border-top: 1px solid var(--line); }
.pair-row { margin-bottom: 10px; }
.pair-label { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
.decision-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.decision-btns button { padding: 4px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); background: #fff; cursor: pointer; transition: all .15s; }
.decision-btns button:hover { background: #f3f4f6; }
.decision-btns button.selected { color: #fff; font-weight: 600; background: var(--accent); border-color: var(--accent); }
.decision-btns button:disabled { opacity: 0.5; cursor: wait; }
.decision-btns button.same_work { color: #15803d; border-color: #15803d; }
.decision-btns button.same_work:hover { background: #dcfce7; }
.decision-btns button.quarantine { color: #991b1b; border-color: #991b1b; }
.decision-btns button.quarantine:hover { background: #fee2e2; }
.empty { padding: 28px; text-align: center; color: var(--muted); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }

.decision-help { background: var(--chip); border: 1px solid var(--line); border-radius: 8px; padding: 8px 14px; margin-bottom: 14px; }
.decision-help summary { cursor: pointer; font-weight: 600; user-select: none; }
.help-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
.help-table th, .help-table td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
.help-table th { background: var(--panel); white-space: nowrap; }
.help-table code { font-size: 12px; }
.help-table .cell-ok { color: var(--ok); font-weight: 600; white-space: nowrap; }
.help-table .cell-bad { color: var(--bad); font-weight: 600; white-space: nowrap; }
.help-note { margin: 10px 0 2px; font-size: 12px; color: var(--muted); line-height: 1.6; }
.rule-box { margin-top: 10px; padding: 8px 12px; background: var(--panel); border: 1px dashed var(--line); border-radius: 6px; }
.rule-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.rule-row { font-size: 12px; color: var(--text); margin: 6px 0 2px; }
.rule-list { margin: 2px 0 6px 18px; font-size: 12px; color: var(--muted); line-height: 1.7; }
.merge-preview { margin: 12px 0; }
.merge-item { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--line); }
.merge-title { font-weight: 600; }
.modal-warn { margin-top: 12px; font-size: 12px; color: #991b1b; background: #fee2e2; padding: 8px; border-radius: 4px; }
.cmd-bar { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin-top: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.export-btn { height: 34px; padding: 0 16px; background: var(--accent); color: #fff; border: none; border-radius: 6px; cursor: pointer; font: inherit; }

/* SHA256 signal on candidate card */
.signal.sha { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.signal.sha-match { background: #fee2e2; color: var(--bad); font-weight: 600; }

/* Per-card PDF preview button */
.cand-actions { margin-top: 6px; }
.link-btn { background: none; border: 1px solid var(--line); color: var(--accent); font-size: 12px; padding: 2px 8px; border-radius: 4px; cursor: pointer; }
.link-btn:hover { background: var(--chip); }

/* Primary-selection merge modal */
.merge-item { cursor: pointer; padding: 8px 6px; border-radius: 6px; }
.merge-item:hover { background: var(--chip); }
.merge-item.recommended { background: #fef9c3; }
.merge-item.chosen { outline: 2px solid var(--accent); }
.merge-item input[type="radio"] { margin-right: 4px; }
.merge-item .score { margin-left: auto; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.rec-badge { font-size: 11px; font-weight: 600; color: #92400e; background: #fde68a; padding: 1px 6px; border-radius: 999px; }
.modal-desc { font-size: 13px; color: var(--text); line-height: 1.6; }
</style>
