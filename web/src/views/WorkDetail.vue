<template>
  <div v-if="work">
    <div class="topbar">
      <router-link to="/works" class="back">← 返回文献列表</router-link>
    </div>
    <h1 :contenteditable="editing" @blur="e => work.title = e.target.innerText" ref="titleEl">
      {{ work.title || work.id }}
    </h1>
    <div class="muted tiny">{{ work.id }}</div>

    <div class="section">
      <div class="section-header">
        <h3>元数据</h3>
        <button v-if="!editing" @click="startEdit">编辑</button>
        <template v-else>
          <button class="save" @click="saveEdit">保存</button>
          <button @click="cancelEdit">取消</button>
        </template>
        <template v-if="!editing">
          <button v-if="work.read_status !== 'quarantined'" class="quarantine-btn" @click="quarantine">隔离</button>
          <button v-else class="restore-btn" @click="restore">恢复</button>
        </template>
      </div>
      <div class="kv">
        <div>作者</div>
        <div>
          <template v-if="editing">
            <input v-model="editForm.authors_str" placeholder="用分号分隔" />
          </template>
          <template v-else>
            {{ (work.authors || []).join('; ') || '未知' }}
          </template>
        </div>
        <div>年份</div>
        <div>
          <input v-if="editing" v-model.number="editForm.year" type="number" />
          <span v-else>{{ work.year || '' }}</span>
        </div>
        <div>类型</div>
        <div>
          <select v-if="editing" v-model="editForm.doc_type">
            <option value="paper">论文</option>
            <option value="report">报告</option>
            <option value="system_card">系统卡</option>
            <option value="benchmark">基准测试</option>
            <option value="preprint">预印本</option>
          </select>
          <span v-else>{{ label(DOC_TYPE_LABELS, work.doc_type) }}</span>
        </div>
        <div>语言</div>
        <div>
          <select v-if="editing" v-model="editForm.language">
            <option value="en">英文</option>
            <option value="zh">中文</option>
            <option value="unknown">未知</option>
          </select>
          <span v-else>{{ label(LANGUAGE_LABELS, work.language) }}</span>
        </div>
        <div>arXiv</div><div>{{ work.arxiv_id || '' }}</div>
        <div>DOI</div><div>{{ work.doi || '' }}</div>
        <div>中文标题</div><div>{{ work.title_zh || '' }}</div>
        <div>发表场所</div><div>{{ work.venue || '' }}</div>
        <div>链接</div><div><a v-if="work.url" :href="work.url" target="_blank">{{ work.url }}</a><span v-else></span></div>
        <div>解析状态</div><div :class="'status-' + work.parse_status">{{ label(PARSE_STATUS_LABELS, work.parse_status) }}</div>
        <div>阅读状态</div><div>
          <select v-if="editing" v-model="editForm.read_status">
            <option value="unread">未读</option>
            <option value="quarantined">已隔离</option>
          </select>
          <span v-else>{{ label(READ_STATUS_LABELS, work.read_status) }}</span>
        </div>
      </div>
    </div>

    <div class="section" v-if="work.abstract">
      <h3>摘要</h3>
      <p class="abstract-text">{{ work.abstract }}</p>
    </div>

    <div class="section">
      <div class="section-header">
        <h3>分类信息</h3>
        <button v-if="!editingCls" @click="startEditCls">编辑</button>
        <template v-else>
          <button class="save" @click="saveEditCls">保存</button>
          <button @click="editingCls = false">取消</button>
        </template>
      </div>
      <div class="kv">
        <div>主文档类型</div>
        <div>
          <select v-if="editingCls" v-model="clsForm.primary_doc_type">
            <option :value="null">未知 (unknown)</option>
            <optgroup label="功能定位类型（优先）">
              <option value="system_model_card">系统卡/模型卡 (system_model_card)</option>
              <option value="governance_framework">治理框架 (governance_framework)</option>
              <option value="standard_guideline">标准/指南 (standard_guideline)</option>
              <option value="benchmark_dataset_paper">基准/数据集论文 (benchmark_dataset_paper)</option>
              <option value="evaluation_report">第三方评估报告 (evaluation_report)</option>
            </optgroup>
            <optgroup label="文档形态类型">
              <option value="technical_report">技术报告 (technical_report)</option>
              <option value="institutional_report">机构报告 (institutional_report)</option>
              <option value="research_article">研究论文 (research_article)</option>
              <option value="survey_review">综述/评述 (survey_review)</option>
              <option value="platform_snapshot">平台快照 (platform_snapshot)</option>
              <option value="thesis">学位论文 (thesis)</option>
              <option value="book_chapter">书章 (book_chapter)</option>
              <option value="webpage_blog">网页/博客 (webpage_blog)</option>
              <option value="other_literature">其他 (other_literature)</option>
            </optgroup>
            <optgroup label="存在性标记">
              <option value="workflow_artifact">工作流产物 (workflow_artifact)</option>
              <option value="not_literature">非文献 (not_literature)</option>
            </optgroup>
          </select>
          <span v-else>{{ label(PRIMARY_DOC_TYPE_LABELS, work.primary_doc_type) || '未知' }}</span>
        </div>
        <div>次要文档类型</div>
        <div>
          <select v-if="editingCls" v-model="clsForm.secondary_doc_type">
            <option :value="null">未知 (unknown)</option>
            <optgroup label="功能定位类型">
              <option value="system_model_card">系统卡/模型卡 (system_model_card)</option>
              <option value="governance_framework">治理框架 (governance_framework)</option>
              <option value="standard_guideline">标准/指南 (standard_guideline)</option>
              <option value="benchmark_dataset_paper">基准/数据集论文 (benchmark_dataset_paper)</option>
              <option value="evaluation_report">第三方评估报告 (evaluation_report)</option>
            </optgroup>
            <optgroup label="文档形态类型">
              <option value="technical_report">技术报告 (technical_report)</option>
              <option value="institutional_report">机构报告 (institutional_report)</option>
              <option value="research_article">研究论文 (research_article)</option>
              <option value="survey_review">综述/评述 (survey_review)</option>
              <option value="platform_snapshot">平台快照 (platform_snapshot)</option>
              <option value="thesis">学位论文 (thesis)</option>
              <option value="book_chapter">书章 (book_chapter)</option>
              <option value="webpage_blog">网页/博客 (webpage_blog)</option>
              <option value="other_literature">其他 (other_literature)</option>
            </optgroup>
          </select>
          <span v-else>{{ label(PRIMARY_DOC_TYPE_LABELS, work.secondary_doc_type) || '—' }}</span>
        </div>
        <div>发布状态</div>
        <div>
          <select v-if="editingCls" v-model="clsForm.publication_status">
            <option :value="null">未知 (unknown)</option>
            <option value="published">已发表 (published)</option>
            <option value="preprint">预印本 (preprint)</option>
            <option value="working_paper">工作论文 (working_paper)</option>
            <option value="draft">草案 (draft)</option>
            <option value="living_document">持续更新文档 (living_document)</option>
            <option value="institutional_release">机构正式发布 (institutional_release)</option>
            <option value="webpage_release">网页发布 (webpage_release)</option>
          </select>
          <span v-else>{{ label(PUBLICATION_STATUS_LABELS, work.publication_status) || '未知' }}</span>
        </div>
        <div>入库状态</div>
        <div>
          <select v-if="editingCls" v-model="clsForm.ingestion_state">
            <option :value="null">未知 (unknown)</option>
            <option value="verified">已核验 (verified)</option>
            <option value="needs_review">待核查 (needs_review)</option>
            <option value="provisional">暂留 (provisional)</option>
            <option value="excluded">已排除 (excluded)</option>
            <option value="deprecated">已废弃 (deprecated)</option>
          </select>
          <span v-else>{{ label(INGESTION_STATE_LABELS, work.ingestion_state) || '未知' }}</span>
        </div>
        <div>优先级</div>
        <div>
          <select v-if="editingCls" v-model="clsForm.priority">
            <option :value="null">未知 (unknown)</option>
            <option value="P0">核心必读 (P0)</option>
            <option value="P1">重要 (P1)</option>
            <option value="P2">参考 (P2)</option>
            <option value="P3">边缘 (P3)</option>
            <option value="archive">归档 (archive)</option>
          </select>
          <span v-else>{{ label(PRIORITY_LABELS, work.priority) || '未知' }}</span>
        </div>
      </div>
      <div class="cls-tags" v-if="work.classification_tags && Object.keys(work.classification_tags).length">
        <div v-for="(values, group) in work.classification_tags" :key="group" class="tag-row">
          <span class="tag-group">{{ label(TAG_GROUP_LABELS, group) }}：</span>
          <span class="chip" v-for="v in values" :key="v">{{ label(TAG_VALUE_LABELS[group], v) }}</span>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h3>标签管理</h3>
      </div>
      <div v-if="allTags.length" class="tag-list">
        <div v-for="t in allTags" :key="t.id" class="tag-item">
          <span class="chip" :class="'tag-' + t.review_status">{{ label(TAG_GROUP_LABELS, t.tag_group) }}: {{ t.tag_value }}</span>
          <span class="muted tiny">{{ t.source }}</span>
          <button class="del" @click="removeTag(t.id)">删除</button>
        </div>
      </div>
      <div v-else class="muted tiny" style="margin-bottom:8px">暂无标签</div>
      <div class="add-tag">
        <select v-model="newTag.tag_group" @change="newTag.tag_value = null">
          <option value="reading_lane">阅读用途</option>
          <option value="artifact_focus">贡献对象</option>
          <option value="risk_domain">风险领域</option>
          <option value="method_tags">方法标签</option>
          <option value="processing_flags">处理标记</option>
        </select>
        <n-select
          v-model:value="newTag.tag_value"
          :options="getTagOptions(newTag.tag_group)"
          filterable
          tag
          placeholder="选择标签值..."
          style="min-width: 200px"
        />
        <button @click="addTag" :disabled="!newTag.tag_value">添加</button>
      </div>
    </div>

    <div class="section" v-if="work.source_files?.length">
      <h3>源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ uniqueShaCount }} 个有效 / {{ work.source_files.length }} 个当前)</span></h3>
      <div v-for="s in work.source_files" :key="s.id" class="file-item">
        <span class="file-name">{{ s.original_name || s.id }}</span>
        <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
        <span class="chip tiny" v-if="isDuplicateSha(s)">重复</span>
        <a :href="pdfUrl(work.id)" target="_blank" v-if="s.file_ext === '.pdf'">查看 PDF</a>
      </div>
    </div>

    <div class="section" v-if="work.archived_source_files?.length">
      <h3>已归档源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ work.archived_source_files.length }} 个)</span></h3>
      <div v-for="s in work.archived_source_files" :key="s.id" class="file-item archived">
        <span class="file-name">{{ s.original_name || s.id }}</span>
        <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
        <span class="chip tiny archived-chip">已归档</span>
        <span class="muted tiny" v-if="s.archive_reason">{{ s.archive_reason }}</span>
      </div>
    </div>

    <div class="section" v-if="work.relations?.length">
      <h3>关联文献</h3>
      <div v-for="r in work.relations" :key="r.work_id_a + r.work_id_b + r.relation_type" class="rel-item">
        <router-link :to="'/works/' + (r.work_id_a === work.id ? r.work_id_b : r.work_id_a)">
          {{ r.partner_title }}
        </router-link>
        <span class="chip">{{ label(RELATION_TYPE_LABELS, r.relation_type) }}</span>
        <button class="del" @click="removeRelation(r)">删除</button>
      </div>
    </div>

    <div class="section">
      <h3>添加关联</h3>
      <div class="add-rel">
        <input v-model="newRel.targetId" placeholder="目标 Work ID" />
        <select v-model="newRel.type">
          <option value="translation_of">翻译版本</option>
          <option value="version_of">版本关系</option>
          <option value="same_work">同一作品</option>
          <option value="part_of">组成部分</option>
          <option value="supersedes">取代</option>
          <option value="not_duplicate">非重复</option>
        </select>
        <button @click="addRelation" :disabled="!newRel.targetId">添加</button>
      </div>
    </div>

    <div class="section" v-if="work.codes?.length">
      <h3>质量标记</h3>
      <span class="chip" v-for="c in work.codes" :key="c.code">{{ c.code }}: {{ c.reason }}</span>
    </div>

    <div class="section" v-if="work.duplicates?.length">
      <h3>重复候选</h3>
      <div v-for="d in work.duplicates" :key="d.id" class="muted tiny">
        {{ d.group_id }} · {{ d.reason }} · reviewed={{ d.reviewed }}
      </div>
    </div>

    <div class="section" v-if="content">
      <h3>内容预览</h3>
      <pre class="content-preview">{{ content }}</pre>
    </div>

    <!-- Quarantine Modal -->
    <div v-if="showQuarantineModal" class="modal-overlay" @click.self="showQuarantineModal = false">
      <div class="modal-box">
        <h3>隔离文献</h3>
        <p class="modal-desc">确定要隔离「{{ work?.title || work?.id }}」吗？</p>
        <div class="modal-reason">
          <label>隔离原因（可选）</label>
          <input v-model="quarantineReason" placeholder="例如：内容无关、404 页面..." />
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="showQuarantineModal = false">取消</button>
          <button class="btn-confirm" :disabled="quarantineLoading" @click="confirmQuarantine">
            {{ quarantineLoading ? '处理中...' : '确认隔离' }}
          </button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="empty">加载中...</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { getWork, updateWork, createRelation, deleteRelation, quarantineWork, restoreWork, contentUrl, pdfUrl, getTags, createTag, deleteTag } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, PUBLICATION_STATUS_LABELS, INGESTION_STATE_LABELS, PRIORITY_LABELS, LANGUAGE_LABELS, READ_STATUS_LABELS, PARSE_STATUS_LABELS, RELATION_TYPE_LABELS, TAG_GROUP_LABELS, TAG_VALUE_LABELS, READING_LANE_LABELS, ARTIFACT_FOCUS_LABELS, RISK_DOMAIN_LABELS, METHOD_TAG_LABELS, PROCESSING_FLAGS_LABELS, label } from '../labels'

const message = useMessage()
const dialog = useDialog()

const props = defineProps(['id'])

const work = ref(null)
const content = ref('')
const editing = ref(false)
const editForm = ref({})
const titleEl = ref(null)
const newRel = ref({ targetId: '', type: 'translation_of' })
const editingCls = ref(false)
const clsForm = ref({})
const allTags = ref([])
const newTag = ref({ tag_group: 'reading_lane', tag_value: '' })

const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)

const uniqueShaCount = computed(() => {
  if (!work.value?.source_files) return 0
  const shas = new Set(work.value.source_files.map(s => s.content_sha256).filter(Boolean))
  return shas.size
})

function isDuplicateSha(s) {
  if (!work.value?.source_files) return false
  const sameShaCount = work.value.source_files.filter(f => f.content_sha256 === s.content_sha256).length
  return sameShaCount > 1
}

async function loadWork() {
  work.value = await getWork(props.id)
  try {
    const res = await fetch(contentUrl(props.id))
    if (res.ok) content.value = await res.text()
  } catch {}
  await loadTags()
}

async function loadTags() {
  try {
    const res = await getTags(props.id)
    allTags.value = res.tags
  } catch { allTags.value = [] }
}

const TAG_GROUP_OPTIONS_MAP = {
  reading_lane: READING_LANE_LABELS,
  artifact_focus: ARTIFACT_FOCUS_LABELS,
  risk_domain: RISK_DOMAIN_LABELS,
  method_tags: METHOD_TAG_LABELS,
  processing_flags: PROCESSING_FLAGS_LABELS,
}

function getTagOptions(group) {
  const map = TAG_GROUP_OPTIONS_MAP[group]
  if (!map) return []
  return Object.entries(map).map(([k, v]) => ({
    label: `${v} (${k})`,
    value: k,
  }))
}

async function addTag() {
  if (!newTag.value.tag_value) return
  await createTag(props.id, {
    tag_group: newTag.value.tag_group,
    tag_value: newTag.value.tag_value,
  })
  newTag.value.tag_value = ''
  await loadTags()
  await loadWork()
}

async function removeTag(tagId) {
  await deleteTag(tagId)
  await loadTags()
  await loadWork()
}

function startEdit() {
  editForm.value = {
    title: work.value.title,
    authors_str: (work.value.authors || []).join('; '),
    year: work.value.year,
    doc_type: work.value.doc_type,
    language: work.value.language,
    read_status: work.value.read_status,
  }
  editing.value = true
}

function cancelEdit() { editing.value = false }

function startEditCls() {
  clsForm.value = {
    primary_doc_type: work.value.primary_doc_type || null,
    secondary_doc_type: work.value.secondary_doc_type || null,
    publication_status: work.value.publication_status || null,
    ingestion_state: work.value.ingestion_state || null,
    priority: work.value.priority || null,
  }
  editingCls.value = true
}

async function saveEditCls() {
  await updateWork(props.id, clsForm.value)
  editingCls.value = false
  await loadWork()
}

async function saveEdit() {
  const data = { ...editForm.value }
  data.authors = data.authors_str.split(';').map(s => s.trim()).filter(Boolean)
  delete data.authors_str
  await updateWork(props.id, data)
  editing.value = false
  await loadWork()
}

async function addRelation() {
  if (!newRel.value.targetId) return
  await createRelation({
    work_id_a: props.id,
    work_id_b: newRel.value.targetId,
    relation_type: newRel.value.type,
  })
  newRel.value.targetId = ''
  await loadWork()
}

async function removeRelation(r) {
  await deleteRelation({
    work_id_a: r.work_id_a,
    work_id_b: r.work_id_b,
    relation_type: r.relation_type,
  })
  await loadWork()
}

function quarantine() {
  quarantineReason.value = ''
  quarantineLoading.value = false
  showQuarantineModal.value = true
}

async function confirmQuarantine() {
  if (quarantineLoading.value) return
  quarantineLoading.value = true
  try {
    await quarantineWork(props.id, quarantineReason.value)
    showQuarantineModal.value = false
    await loadWork()
    message.success('已隔离')
  } catch (e) {
    message.error('隔离失败: ' + (e.message || e))
  } finally {
    quarantineLoading.value = false
  }
}

function restore() {
  dialog.warning({
    title: '恢复文献',
    content: '确认恢复此文献？文件将移回 works 目录。',
    positiveText: '恢复',
    negativeText: '取消',
    onPositiveClick: async () => {
      await restoreWork(props.id)
      await loadWork()
      message.success('已恢复')
    },
  })
}

onMounted(loadWork)
</script>

<style scoped>
h1 { font-size: 20px; margin-bottom: 4px; outline: none; }
h1[contenteditable] { border-bottom: 2px solid var(--accent); padding-bottom: 2px; }
.topbar { margin-bottom: 12px; }
.back { font-size: 13px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.section { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--line); }
.section h3 { font-size: 13px; text-transform: uppercase; color: #475467; margin-bottom: 8px; }
.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.section-header h3 { margin-bottom: 0; }
.kv { display: grid; grid-template-columns: 100px 1fr; gap: 6px 8px; font-size: 13px; }
.kv div:nth-child(odd) { color: var(--muted); }
.kv input, .kv select { height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 8px; font: inherit; }
button { height: 30px; padding: 0 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
button.save { background: var(--accent); color: #fff; border-color: var(--accent); }
button.quarantine-btn { color: var(--bad); border-color: var(--bad); }
button.restore-btn { color: var(--ok); border-color: var(--ok); }
button.del { font-size: 12px; color: var(--bad); border: none; background: none; padding: 0 4px; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; margin-left: 6px; }
.file-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
.file-item.archived { opacity: 0.6; }
.file-name { font-weight: 600; }
.archived-chip { background: #f3f4f6; color: #6b7280; }
.rel-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.add-rel { display: flex; gap: 8px; align-items: center; }
.add-rel input, .add-rel select { height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; font: inherit; }
.content-preview { font-size: 12px; font-family: Consolas, monospace; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
.status-succeeded { color: var(--ok); font-weight: 600; }
.status-failed { color: var(--bad); font-weight: 600; }
.abstract-text { font-size: 13px; line-height: 1.6; color: #374151; margin: 0; }
.cls-tags { margin-top: 10px; }
.tag-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 4px 0; }
.tag-group { font-size: 12px; color: var(--muted); min-width: 80px; }
.tag-list { margin-bottom: 8px; }
.tag-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.tag-approved { background: #dcfce7; color: #166534; }
.tag-pending { background: #fef3c7; color: #92400e; }
.tag-rejected { background: #fee2e2; color: #991b1b; }
.add-tag { display: flex; gap: 8px; align-items: center; }
.add-tag select, .add-tag input { height: 30px; border: 1px solid var(--line); border-radius: 4px; padding: 0 8px; font: inherit; font-size: 12px; }
.add-tag button { height: 30px; padding: 0 10px; border: 1px solid var(--line); border-radius: 4px; background: #fff; cursor: pointer; font: inherit; font-size: 12px; }
.empty { padding: 28px; text-align: center; color: var(--muted); }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: #fff; border-radius: 8px; padding: 24px; width: 420px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; }
.modal-desc { margin: 0 0 16px; font-size: 13px; color: #6b7280; }
.modal-reason label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.modal-reason input { width: 100%; height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; box-sizing: border-box; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn-cancel { height: 32px; padding: 0 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; font-size: 13px; }
.btn-confirm { height: 32px; padding: 0 14px; border: none; border-radius: 6px; background: var(--bad, #dc2626); color: #fff; cursor: pointer; font: inherit; font-size: 13px; }
.btn-confirm:disabled { opacity: 0.5; cursor: default; }
</style>
