<template>
  <div class="tpl-page">
    <!-- Page Header -->
    <div class="tpl-header">
      <h2>📑 模板管理</h2>
      <div class="tpl-header-meta">
        <span v-if="data" class="tpl-last-mod">
          {{ data._meta?.has_customizations ? '✏️' : '📖' }} 默认
          <template v-if="data._meta?.last_modified"> · 更新于 {{ formatTime(data._meta.last_modified) }}</template>
        </span>
        <button v-if="hasChanges" class="btn-save" :disabled="saving" @click="doSave">
          {{ saving ? '保存中...' : '💾 保存修改' }}
        </button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tpl-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tpl-tab"
        :class="{ active: activeTab === tab.key, locked: tab.locked }"
        @click="activeTab = tab.key"
        :title="tab.locked ? tab.lockHint : ''"
      >
        {{ tab.icon }} {{ tab.label }}
        <span v-if="tab.locked" class="lock-icon">🔒</span>
      </button>
    </div>

    <!-- Tab Content: Metadata Fields (editable) -->
    <div v-if="activeTab === 'metadata' && data" class="tpl-content">
      <div class="toolbar">
        <div class="toolbar-left">
          <span class="field-count">{{ data.metadata.fields.length }} 个字段</span>
          <span v-if="hasChanges" class="changes-badge">有未保存的修改</span>
        </div>
        <div class="toolbar-right">
          <button class="ctrl-sm" @click="copyJSON('metadata')">📋 复制 JSON</button>
          <button class="ctrl-sm" @click="copyPrompt()">📄 复制 LLM Prompt</button>
          <button class="ctrl-sm warn" @click="confirmReset">🔄 恢复默认</button>
          <button class="ctrl-sm" @click="showAddField = true">➕ 添加字段</button>
        </div>
      </div>

      <table class="field-table">
        <thead>
          <tr>
            <th>字段名</th>
            <th>中文标签</th>
            <th>类型</th>
            <th>验证规则</th>
            <th>说明</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(f, idx) in data.metadata.fields" :key="f.key || idx" :class="{ builtin: isBuiltin(f.key) }">
            <td class="cell-key"><code>{{ f.key }}</code><span v-if="isBuiltin(f.key)" class="builtin-tag">内置</span></td>
            <td class="cell-editable" @click="startEdit(idx, 'label', $event)">
              <template v-if="editingIdx === idx && editingField === 'label'">
                <input ref="editInput" v-model="data.metadata.fields[idx].label"
                  class="inline-input" @blur="finishEdit" @keyup.enter="finishEdit" @keyup.escape="cancelEdit" />
              </template>
              <template v-else>{{ f.label || '—' }}</template>
            </td>
            <td class="cell-editable" @click="startEdit(idx, 'type', $event)">
              <template v-if="editingIdx === idx && editingField === 'type'">
                <select v-model="data.metadata.fields[idx].type" class="inline-select" @blur="finishEdit" @change="finishEdit">
                  <option v-for="t in validTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </template>
              <template v-else><span class="type-badge">{{ f.type }}</span></template>
            </td>
            <td class="cell-rules" :title="f.rules ? '后续版本可编辑此字段' : ''">
              <span class="rules-text">{{ f.rules || '—' }}</span>
            </td>
            <td class="cell-editable cell-desc" @click="startEdit(idx, 'description', $event)">
              <template v-if="editingIdx === idx && editingField === 'description'">
                <textarea ref="editTextarea" v-model="data.metadata.fields[idx].description"
                  class="inline-textarea" rows="2" @blur="finishEdit" @keyup.escape="cancelEdit"></textarea>
              </template>
              <template v-else>{{ f.description || '—' }}</template>
            </td>
            <td class="cell-action">
              <button v-if="!isBuiltin(f.key)" class="btn-del" title="删除自定义字段" @click="confirmDelete(idx)">🗑️</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Internal fields -->
      <div class="internal-section">
        <h4>内部字段（系统自动生成，不可编辑）</h4>
        <div class="internal-tags">
          <span v-for="if_ in data.metadata.internal_fields" :key="if_.key" class="itag">
            <code>{{ if_.key }}</code>: {{ if_.description }}
          </span>
        </div>
      </div>

      <!-- Add Field Dialog -->
      <div v-if="showAddField" class="modal-overlay" @click.self="showAddField = false">
        <div class="modal-box">
          <h3>➕ 添加自定义字段</h3>
          <div class="form-row">
            <label>字段名 (key):</label>
            <input v-model="newField.key" placeholder="如 journal, isbn ..." class="form-input" />
          </div>
          <div class="form-row">
            <label>中文标签:</label>
            <input v-model="newField.label" placeholder="如 期刊名" class="form-input" />
          </div>
          <div class="form-row">
            <label>类型:</label>
            <select v-model="newField.type" class="form-input">
              <option v-for="t in validTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
          <p v-if="newField.key && isBuiltin(newField.key)" class="form-error">⚠️ 此字段名与内置字段冲突，请换一个名称。</p>
          <div class="form-actions">
            <button class="btn-cancel" @click="showAddField = false">取消</button>
            <button class="btn-confirm" :disabled="!newField.key || !newField.label || isBuiltin(newField.key)" @click="addField">添加</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab Content: Classification Vocab (read-only, reserved) -->
    <div v-if="activeTab === 'classification' && data" class="tpl-content">
      <div class="toolbar">
        <div class="toolbar-left">
          <span class="field-count">{{ Object.keys(data.classification.vocab || {}).length}} 个词汇分组</span>
        </div>
        <div class="toolbar-right">
          <button class="ctrl-sm" @click="copyJSON('classification')">📋 复制全部 JSON</button>
          <button class="ctrl-sm disabled" title="即将支持在线增删标签值，需同步 labels.js ↔ classification_vocab.py">✏️ 编辑模式 🔒</button>
        </div>
      </div>

      <div class="vocab-list">
        <div v-for="(items, group) in data.classification.vocab" :key="group" class="vocab-card">
          <div class="vocab-card-header" @click="toggleVocab(group)">
            <span class="vocab-arrow">{{ vocabExpanded[group] ? '▼' : '▶' }}</span>
            <strong>{{ group }}</strong>
            <span class="vocab-count">{{ items.length }}项</span>
            <span v-if="data.classification.versions?.[group]" class="vocab-version">v{{ data.classification.versions[group] }}</span>
            <button class="vocab-copy" @click.stop="copyVocabGroup(group, items)">📋</button>
          </div>
          <div v-show="vocabExpanded[group]" class="vocab-body">
            <div class="tag-cloud">
              <template v-for="(item, i) in (vocabExpanded[group] ? items : items.slice(0, vocabPreviewLimit))" :key="i">
                <span class="vocab-tag">{{ item }}</span>
              </template>
            </div>
            <div v-if="items.length > vocabPreviewLimit && !vocabExpanded[group]" class="vocab-more" @click="toggleVocab(group)">
              还有 {{ items.length - vocabPreviewLimit }} 项… 点击展开
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab Content: Discovery Protocol (read-only, reserved) -->
    <div v-if="activeTab === 'discovery' && data" class="tpl-content">
      <div class="toolbar">
        <div class="toolbar-left">
          <span v-if="data.discovery.filename" class="field-count">
            📄 {{ data.discovery.filename }}
            · {{ data.discovery.lines }} 行 · {{ formatSize(data.discovery.size_bytes) }}
          </span>
          <span v-else class="field-count">协议文件未找到</span>
        </div>
        <div class="toolbar-right">
          <button class="ctrl-sm" @click="copyDiscoveryRaw()">📋 复制全文</button>
          <button v-if="data.discovery.path" class="ctrl-sm" @click="alert('文件路径: ' + projectRoot + '/' + data.discovery.path)">📂 文件路径</button>
          <button class="ctrl-sm disabled" title="即将支持在线编辑协议文档并结构化为可配置 JSON">✏️ 编辑模式 🔒</button>
        </div>
      </div>

      <!-- Protocol Info Card -->
      <div v-if="data.discovery.raw" class="protocol-info">
        <pre class="protocol-raw">{{ data.discovery.raw }}</pre>
        <p v-if="data.discovery.truncated" class="truncated-note">内容已截断（仅显示前 15KB）</p>
      </div>
      <div v-else class="empty-state">
        未发现检索协议文档 (docs/discovery-agent-protocol.md)
      </div>
    </div>

    <!-- Loading / Empty -->
    <div v-if="!data && !error" class="empty-state">加载中...</div>
    <div v-if="error" class="empty-state error">加载失败: {{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { getTemplates, saveMetadataTemplate, resetMetadataTemplate } from '../api_templates'

// ---- Constants ----

const validTypes = ['text', 'date-object', 'author-list', 'contributor-list', 'textarea', 'list']
const builtinKeys = new Set([
  'title','title_zh','publication_date','authors','contributors',
  'doi','arxiv_id','venue','url','abstract'
])
const vocabPreviewLimit = 10

const tabs = [
  { key: 'metadata', label: '元数据字段', icon: '📝', locked: false },
  { key: 'classification', label: '分类词汇', icon: '📋', locked: true,
    lockHint: '编辑功能开发中——当前只可查看和导出' },
  { key: 'discovery', label: '检索协议', icon: '🔍', locked: true,
    lockHint: '编辑功能开发中——当前只可查看和导出' },
]

// ---- State ----

const activeTab = ref('metadata')
const data = ref(null)
const originalData = ref(null)
const saving = ref(false)
const error = ref(null)

// Inline editing
const editingIdx = ref(-1)
const editingField = ref('')
const editInput = ref(null)
const editTextarea = ref(null)

// Add field dialog
const showAddField = ref(false)
const newField = ref({ key: '', label: '', type: 'text' })

// Classification vocab expand/collapse
const vocabExpanded = ref({})

// Project root for path display
const projectRoot = 'D:/02_academic/doctoral/literature_library'

// ---- Computed ----

const hasChanges = computed(() => {
  if (!data.value || !originalData.value) return false
  return JSON.stringify(data.value.metadata?.fields) !==
         JSON.stringify(originalData.value.metadata?.fields)
})

// ---- Methods ----

function isBuiltin(key) {
  return builtinKeys.has(key)
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

async function loadTemplates() {
  error.value = null
  try {
    const res = await getTemplates()
    originalData.value = JSON.parse(JSON.stringify(res))
    data.value = res

    // Default all classification groups to collapsed
    if (res.classification?.vocab) {
      const expanded = {}
      // Auto-expand first 3 small groups
      let count = 0
      for (const [k, v] of Object.entries(res.classification.vocab)) {
        if (count < 3 && Array.isArray(v) && v.length <= 15) {
          expanded[k] = true
          count++
        } else {
          expanded[k] = false
        }
      }
      vocabExpanded.value = expanded
    }
  } catch (e) {
    console.error('[TemplateManage] load failed:', e)
    error.value = e.message || String(e)
  }
}

// --- Save ---

async function doSave() {
  if (!data.value?.metadata?.fields) return
  saving.value = true
  try {
    await saveMetadataTemplate({
      version: '1.1',
      fields: data.value.metadata.fields,
      _note: '通过模板管理页面编辑',
    })
    originalData.value = JSON.parse(JSON.stringify(data.value))
    window.__naive_message?.success('模板已保存 ✅')
  } catch (e) {
    console.error('[TemplateManage] save failed:', e)
    window.__naive_message?.error('保存失败: ' + (e.message || e.detail || e))
  } finally {
    saving.value = false
  }
}

function confirmReset() {
  if (!confirm('确定恢复所有元数据字段为内置默认值？\n你的自定义修改将被清除（可通过备份恢复）。')) return
  resetToDefaults()
}

async function resetToDefaults() {
  try {
    await resetMetadataTemplate()
    window.__naive_message?.info('已恢复为内置默认值')
    await loadTemplates()
  } catch (e) {
    window.__naive_message?.error('重置失败: ' + (e.message || e))
  }
}

// --- Inline editing ---

function startEdit(idx, field, event) {
  editingIdx.value = idx
  editingField.value = field
  nextTick(() => {
    if (field === 'label' || field === 'type') {
      const el = editInput.value
      if (el) {
        const arr = Array.isArray(el) ? el : [el]
        arr.forEach(e => e?.focus()?.select())
      }
    } else if (field === 'description') {
      const el = editTextarea.value
      if (el) {
        const arr = Array.isArray(el) ? el : [el]
        arr.forEach(e => e?.focus())
      }
    }
  })
}

function finishEdit() {
  editingIdx.value = -1
  editingField.value = ''
}

function cancelEdit() {
  // Revert changes? For simplicity we just cancel the edit session.
  // Data was already mutated by v-model; user can manually reload to discard.
  finishEdit()
}

// --- Add field ---

function addField() {
  if (!newField.value.key || !newField.value.label || isBuiltin(newField.value.key)) return
  data.value.metadata.fields.push({
    key: newField.value.key,
    label: newField.value.label,
    type: newField.value.type,
    rules: '',
    description: '',
  })
  showAddField.value = false
  newField.value = { key: '', label: '', type: 'text' }
}

function confirmDelete(idx) {
  const f = data.value.metadata.fields[idx]
  if (!confirm(`确定删除字段 "${f.key}" (${f.label})？`)) return
  data.value.metadata.fields.splice(idx, 1)
}

// --- Copy/Export ---

async function copyJSON(section) {
  const obj = section === 'metadata'
    ? data.value.metadata.fields
    : data.value.classification
  try {
    await navigator.clipboard.writeText(JSON.stringify(obj, null, 2))
    window.__naive_message?.success('已复制到剪贴板 ✅')
  } catch {
    window.__naive_message?.warn('复制失败，请手动选择文本复制')
  }
}

async function copyPrompt() {
  const fields = data.value?.metadata?.fields || []
  const lines = fields.map(f => {
    return `  "${f.key}": (${f.type}) ${f.description || ''}${f.rules ? ' — ' + f.rules : ''}`
  })
  const prompt = `## 可抽取字段\n${lines.join('\n')}\n\n请按以上字段从文献内容中抽取信息，输出严格 JSON 格式。`
  try {
    await navigator.clipboard.writeText(prompt)
    window.__naive_message?.success('LLM Prompt 已复制 ✅ （可用于笨模式手动 CLI）')
  } catch {
    window.__naive_message?.warn('复制失败')
  }
}

function toggleVocab(group) {
  vocabExpanded.value[group] = !vocabExpanded.value[group]
}

async function copyVocabGroup(group, items) {
  try {
    await navigator.clipboard.writeText(JSON.stringify({ [group]: items }, null, 2))
    window.__naive_message?.success(`「${group}」词汇已复制 ✅`)
  } catch {
    window.__naive_message?.warn('复制失败')
  }
}

async function copyDiscoveryRaw() {
  try {
    await navigator.clipboard.writeText(data.value.discovery.raw || '')
    window.__naive_message?.success('协议全文已复制 ✅')
  } catch {
    window.__naive_message?.warn('复制失败')
  }
}

// ---- Init ----

onMounted(loadTemplates)
</script>

<style scoped>
.tpl-page {
  max-width: 1100px;
  margin: 0 auto;
}

/* Header */
.tpl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-5);
}
.tpl-header h2 {
  font-size: var(--text-xl);
  font-weight: 600;
}
.tpl-header-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.tpl-last-mod {
  padding: 2px 8px;
  background: var(--bg-muted);
  border-radius: var(--radius-md);
}

/* Tabs */
.tpl-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 2px solid var(--border);
  margin-bottom: var(--space-5);
}
.tpl-tab {
  padding: var(--space-3) var(--space-5);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--text-secondary);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}
.tpl-tab:hover {
  color: var(--text-primary);
  background: var(--bg-muted);
}
.tpl-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.tpl-tab.locked {
  opacity: 0.75;
}
.lock-icon {
  font-size: 10px;
  margin-left: 2px;
}

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
  gap: var(--space-2);
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
}
.field-count {
  color: var(--text-secondary);
}
.changes-badge {
  color: var(--warn);
  font-weight: 500;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.toolbar-right {
  display: flex;
  gap: var(--space-2);
}

/* Buttons */
.btn-save {
  padding: 6px 16px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
}
.btn-save:hover:not(:disabled) { background: var(--accent-hover); }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }

.ctrl-sm {
  padding: 4px 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.ctrl-sm:hover { background: var(--bg-muted); color: var(--text-primary); }
.ctrl-sm.warn:hover { border-color: var(--warn); color: var(--warn); }
.ctrl-sm.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Table */
.field-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}
.field-table th {
  text-align: left;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-muted);
  border-bottom: 2px solid var(--border-strong);
  font-weight: 500;
  position: sticky;
  top: 0;
}
.field-table td {
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.field-table tr:hover td { background: var(--accent-subtle); }
.field-table tr.builtin { opacity: 0.9; }

.cell-key code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-muted);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}
.builtin-tag {
  font-size: 10px;
  color: var(--neutral);
  margin-left: 4px;
}

.cell-editable {
  cursor: pointer;
  min-height: 24px;
  transition: background 0.1s;
}
.cell-editable:hover { background: rgba(37,99,235,0.06); border-radius: 2px; }
.inline-input, .inline-select, .inline-textarea {
  width: 100%;
  padding: 2px 6px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  font: inherit;
  font-size: inherit;
  outline: none;
  box-shadow: var(--shadow-focus);
}
.inline-textarea { resize: vertical; }

.cell-rules .rules-text {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.cell-desc { max-width: 280px; }

.cell-action { width: 36px; text-align: center; }
.btn-del {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.3;
  transition: opacity 0.15s;
}
.btn-del:hover { opacity: 1; }

.type-badge {
  display: inline-block;
  padding: 1px 7px;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}

/* Internal fields */
.internal-section {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px dashed var(--border);
}
.internal-section h4 {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}
.internal-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.itag {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-muted);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}
.itag code { font-family: var(--font-mono); color: var(--text-primary); }

/* Add Field Dialog */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-box {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-6);
  width: 420px;
  max-width: 90vw;
}
.modal-box h3 { margin-bottom: var(--space-4); }
.form-row {
  margin-bottom: var(--space-3);
}
.form-row label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.form-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font: inherit;
  font-size: var(--text-sm);
  box-sizing: border-box;
}
.form-error {
  color: var(--bad);
  font-size: var(--text-xs);
  margin: var(--space-2) 0;
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-5);
}
.btn-cancel, .btn-confirm {
  padding: 6px 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  cursor: pointer;
  font-size: var(--text-sm);
}
.btn-cancel { background: var(--bg-muted); }
.btn-confirm { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-confirm:disabled { opacity: 0.4; cursor: not-allowed; }

/* Classification vocab cards */
.vocab-list {
  display: grid;
  gap: var(--space-3);
}
.vocab-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.vocab-card-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-muted);
  cursor: pointer;
  font-size: var(--text-sm);
  user-select: none;
}
.vocab-card-header:hover { background: var(--border); }
.vocab-arrow { font-size: 10px; color: var(--text-tertiary); }
.vocab-count {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.vocab-version {
  font-size: 10px;
  background: #dbeafe;
  color: #0369a1;
  padding: 0 6px;
  border-radius: 8px;
}
.vocab-copy {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.4;
}
.vocab-copy:hover { opacity: 1; }

.vocab-body {
  padding: var(--space-3) var(--space-4);
}
.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.vocab-tag {
  padding: 2px 10px;
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
  border-radius: 12px;
  font-size: var(--text-xs);
}
.vocab-more {
  font-size: var(--text-xs);
  color: var(--accent);
  cursor: pointer;
  margin-top: var(--space-2);
}

/* Protocol raw */
.protocol-info {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.protocol-raw {
  margin: 0;
  padding: var(--space-5);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 70vh;
  overflow-y: auto;
  background: var(--bg-surface);
}
.truncated-note {
  text-align: center;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  padding: var(--space-2);
  border-top: 1px solid var(--border);
}

/* Empty state */
.empty-state {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: var(--text-base);
}
.empty-state.error { color: var(--bad); }
</style>
