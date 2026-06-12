<template>
  <div class="work-layout" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel" :class="{ collapsed: listCollapsed }">
      <div class="list-header">
        <h2>文献</h2>
        <router-link to="/works" class="full-link" title="完整筛选页面">完整</router-link>
      </div>
      <div class="list-filters">
        <n-input v-model:value="listSearch" placeholder="搜索..." size="small" clearable @input="debouncedLoadList" />
        <n-select v-model:value="listSortKey" :options="listSortOptions" size="small" style="width: 100px" @update:value="loadList()" />
        <n-button text @click="toggleSortDir" :title="listSortDir === 'desc' ? '降序' : '升序'" style="flex-shrink:0">
          {{ listSortDir === 'desc' ? '↓' : '↑' }}
        </n-button>
      </div>
      <div class="list-body">
        <div v-for="w in worksList" :key="w.id"
          class="list-item" :class="{ selected: w.id === props.id, quarantined: w.read_status === 'quarantined' }"
          @click="router.push('/works/' + w.id)">
          <div class="list-item-title">{{ w.title || w.id }}</div>
          <div class="list-item-meta">
            <span>{{ w.year || '' }}</span>
            <span v-if="w.primary_doc_type" class="type-chip">{{ label(PRIMARY_DOC_TYPE_LABELS, w.primary_doc_type) }}</span>
            <span v-if="w.priority" class="priority-chip" :class="w.priority">{{ w.priority }}</span>
          </div>
        </div>
        <div v-if="!worksList.length" class="list-empty">没有匹配的文献</div>
      </div>
      <n-pagination v-if="listTotalPages > 1" v-model:page="listPage" :page-count="listTotalPages" size="small" @update:page="loadList()" style="padding: 8px" />
      <div class="list-collapse-bar" @click="toggleListCollapse" :title="listCollapsed ? '展开列表' : '收起列表'">
        {{ listCollapsed ? '»' : '«' }}
      </div>
    </div>

    <ResizeHandle @resize="onResizeList" />

    <!-- Right: detail panel -->
    <div class="detail-panel" v-if="work">
      <div class="detail-header">
        <div class="detail-header-left">
          <h1 :contenteditable="editing" @blur="e => work.title = e.target.innerText" ref="titleEl">
            {{ work.title || work.id }}
          </h1>
          <div class="muted tiny">{{ work.id }}</div>
        </div>
        <div class="detail-header-right">
          <n-button size="small" :type="showPdf ? 'primary' : 'default'" quaternary @click="togglePdf">
            {{ showPdf ? '关闭 PDF' : 'PDF' }}
          </n-button>
          <a :href="pdfUrl(props.id)" target="_blank" class="pdf-ext-link">外部打开</a>
        </div>
      </div>

      <!-- 元数据 -->
      <div class="section">
        <div class="section-header">
          <h3>元数据</h3>
          <n-button v-if="!editing" size="small" quaternary @click="startEdit">编辑</n-button>
          <template v-else>
            <n-button size="small" type="primary" @click="saveEdit">保存</n-button>
            <n-button size="small" quaternary @click="cancelEdit">取消</n-button>
          </template>
          <template v-if="!editing">
            <n-button v-if="work.read_status !== 'quarantined'" size="small" text type="error" @click="quarantine">隔离</n-button>
            <n-button v-else size="small" text type="success" @click="restore">恢复</n-button>
          </template>
        </div>
        <div class="kv">
          <div>作者</div>
          <div>
            <n-input v-if="editing" v-model:value="editForm.authors_str" size="small" placeholder="用分号分隔" />
            <span v-else>{{ (work.authors || []).join('; ') || '未知' }}</span>
          </div>
          <div>年份</div>
          <div>
            <n-input v-if="editing" v-model:value.number="editForm.year" size="small" type="text" />
            <span v-else>{{ work.year || '' }}</span>
          </div>
          <div>类型</div>
          <div>
            <n-select v-if="editing" v-model:value="editForm.doc_type" :options="docTypeOptions" size="small" />
            <span v-else>{{ label(DOC_TYPE_LABELS, work.doc_type) }}</span>
          </div>
          <div>语言</div>
          <div>
            <n-select v-if="editing" v-model:value="editForm.language" :options="langOptions" size="small" />
            <span v-else>{{ label(LANGUAGE_LABELS, work.language) }}</span>
          </div>
          <div>arXiv</div><div>{{ work.arxiv_id || '' }}</div>
          <div>DOI</div><div>{{ work.doi || '' }}</div>
          <div>中文标题</div><div>{{ work.title_zh || '' }}</div>
          <div>发表场所</div><div>{{ work.venue || '' }}</div>
          <div>链接</div><div><a v-if="work.url" :href="work.url" target="_blank">{{ work.url }}</a></div>
          <div>解析状态</div><div :class="'status-' + work.parse_status">{{ label(PARSE_STATUS_LABELS, work.parse_status) }}</div>
          <div>阅读状态</div>
          <div>
            <n-select v-if="editing" v-model:value="editForm.read_status" :options="readStatusOptions" size="small" />
            <span v-else :class="'status-' + work.read_status">{{ label(READ_STATUS_LABELS, work.read_status) }}</span>
          </div>
        </div>
      </div>

      <!-- 摘要 -->
      <div class="section" v-if="work.abstract">
        <h3>摘要</h3>
        <p class="abstract-text">{{ work.abstract }}</p>
      </div>

      <!-- 分类信息 -->
      <div class="section">
        <div class="section-header">
          <h3>分类信息</h3>
          <n-button v-if="!editingCls" size="small" quaternary @click="startEditCls">编辑</n-button>
          <template v-else>
            <n-button size="small" type="primary" @click="saveEditCls">保存</n-button>
            <n-button size="small" quaternary @click="editingCls = false">取消</n-button>
          </template>
        </div>
        <div class="kv">
          <div>主文档类型</div>
          <div>
            <n-select v-if="editingCls" v-model:value="clsForm.primary_doc_type" :options="primaryDocTypeOptions" clearable size="small" />
            <span v-else>{{ label(PRIMARY_DOC_TYPE_LABELS, work.primary_doc_type) || '未知' }}</span>
          </div>
          <div>次要文档类型</div>
          <div>
            <n-select v-if="editingCls" v-model:value="clsForm.secondary_doc_type" :options="primaryDocTypeOptions" clearable size="small" />
            <span v-else>{{ label(PRIMARY_DOC_TYPE_LABELS, work.secondary_doc_type) || '—' }}</span>
          </div>
          <div>发布状态</div>
          <div>
            <n-select v-if="editingCls" v-model:value="clsForm.publication_status" :options="pubStatusOptions" clearable size="small" />
            <span v-else>{{ label(PUBLICATION_STATUS_LABELS, work.publication_status) || '未知' }}</span>
          </div>
          <div>入库状态</div>
          <div>
            <n-select v-if="editingCls" v-model:value="clsForm.ingestion_state" :options="ingestionStateOptions" clearable size="small" />
            <span v-else>{{ label(INGESTION_STATE_LABELS, work.ingestion_state) || '未知' }}</span>
          </div>
          <div>优先级</div>
          <div>
            <n-select v-if="editingCls" v-model:value="clsForm.priority" :options="priorityOptions" clearable size="small" />
            <span v-else :class="work.priority ? 'priority-' + work.priority : ''">{{ label(PRIORITY_LABELS, work.priority) || '未知' }}</span>
          </div>
        </div>
        <div class="cls-tags" v-if="work.classification_tags && Object.keys(work.classification_tags).length">
          <div v-for="(values, group) in work.classification_tags" :key="group" class="tag-row">
            <span class="tag-group">{{ label(TAG_GROUP_LABELS, group) }}：</span>
            <n-tag v-for="v in values" :key="v" size="small" round>{{ label(TAG_VALUE_LABELS[group], v) }}</n-tag>
          </div>
        </div>
      </div>

      <!-- 标签管理 -->
      <div class="section">
        <div class="section-header"><h3>标签管理</h3></div>
        <div v-if="allTags.length" class="tag-list">
          <div v-for="t in allTags" :key="t.id" class="tag-item">
            <n-tag :type="t.review_status === 'approved' ? 'success' : t.review_status === 'rejected' ? 'error' : 'warning'" size="small">
              {{ label(TAG_GROUP_LABELS, t.tag_group) }}: {{ t.tag_value }}
            </n-tag>
            <span class="muted tiny">{{ t.source }}</span>
            <n-button text type="error" size="tiny" @click="removeTag(t.id)">删除</n-button>
          </div>
        </div>
        <div v-else class="muted tiny" style="margin-bottom:8px">暂无标签</div>
        <div class="add-tag">
          <n-select v-model:value="newTag.tag_group" :options="tagGroupOptions" style="width: 120px" size="small" @update:value="newTag.tag_value = null" />
          <n-select v-model:value="newTag.tag_value" :options="getTagOptions(newTag.tag_group)" filterable tag placeholder="选择标签值..." style="min-width: 200px" size="small" />
          <n-button size="small" type="primary" :disabled="!newTag.tag_value" @click="addTag">添加</n-button>
        </div>
      </div>

      <!-- 源文件 -->
      <div class="section" v-if="work.source_files?.length">
        <h3>源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ uniqueShaCount }} 个有效 / {{ work.source_files.length }} 个当前)</span></h3>
        <div v-for="s in work.source_files" :key="s.id" class="file-item">
          <span class="file-name">{{ s.original_name || s.id }}</span>
          <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
          <n-tag v-if="isDuplicateSha(s)" size="small" type="warning">重复</n-tag>
          <a :href="pdfUrl(work.id)" target="_blank" v-if="s.file_ext === '.pdf'" class="pdf-ext-link">查看 PDF</a>
        </div>
      </div>

      <!-- 已归档源文件 -->
      <div class="section" v-if="work.archived_source_files?.length">
        <h3>已归档源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ work.archived_source_files.length }} 个)</span></h3>
        <div v-for="s in work.archived_source_files" :key="s.id" class="file-item archived">
          <span class="file-name">{{ s.original_name || s.id }}</span>
          <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
          <n-tag size="small">已归档</n-tag>
          <span class="muted tiny" v-if="s.archive_reason">{{ s.archive_reason }}</span>
        </div>
      </div>

      <!-- 关联文献 -->
      <div class="section" v-if="work.relations?.length">
        <h3>关联文献</h3>
        <div v-for="r in work.relations" :key="r.work_id_a + r.work_id_b + r.relation_type" class="rel-item">
          <router-link :to="'/works/' + (r.work_id_a === work.id ? r.work_id_b : r.work_id_a)">
            {{ r.partner_title }}
          </router-link>
          <n-tag size="small">{{ label(RELATION_TYPE_LABELS, r.relation_type) }}</n-tag>
          <n-button text type="error" size="tiny" @click="removeRelation(r)">删除</n-button>
        </div>
      </div>

      <!-- 添加关联 -->
      <div class="section">
        <h3>添加关联</h3>
        <div class="add-rel">
          <n-input v-model:value="newRel.targetId" placeholder="目标 Work ID" size="small" style="width: 200px" />
          <n-select v-model:value="newRel.type" :options="relationTypeOptions" size="small" style="width: 140px" />
          <n-button size="small" :disabled="!newRel.targetId" @click="addRelation">添加</n-button>
        </div>
      </div>

      <!-- 质量标记 -->
      <div class="section" v-if="work.codes?.length">
        <h3>质量标记</h3>
        <n-tag v-for="c in work.codes" :key="c.code" size="small" type="warning" style="margin-right: 6px">{{ c.code }}: {{ c.reason }}</n-tag>
      </div>

      <!-- 重复候选 -->
      <div class="section" v-if="work.duplicates?.length">
        <h3>重复候选</h3>
        <div v-for="d in work.duplicates" :key="d.id" class="muted tiny">
          {{ d.group_id }} · {{ d.reason }} · reviewed={{ d.reviewed }}
        </div>
      </div>

      <!-- 内容预览 -->
      <div class="section" v-if="content">
        <h3>内容预览</h3>
        <pre class="content-preview">{{ content }}</pre>
      </div>
    </div>
    <div v-else class="detail-panel empty-panel">
      <n-spin size="large" />
    </div>

    <ResizeHandle v-if="showPdf" @resize="onResizeDetail" />

    <!-- PDF drawer -->
    <PdfPreviewDrawer v-if="showPdf" :url="pdfUrl(props.id)" :work-id="props.id" @close="showPdf = false" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { getWorks, getWork, updateWork, createRelation, deleteRelation, quarantineWork, restoreWork, contentUrl, pdfUrl, getTags, createTag, deleteTag } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, PUBLICATION_STATUS_LABELS, INGESTION_STATE_LABELS, PRIORITY_LABELS, LANGUAGE_LABELS, READ_STATUS_LABELS, PARSE_STATUS_LABELS, RELATION_TYPE_LABELS, TAG_GROUP_LABELS, TAG_VALUE_LABELS, READING_LANE_LABELS, ARTIFACT_FOCUS_LABELS, RISK_DOMAIN_LABELS, METHOD_TAG_LABELS, PROCESSING_FLAGS_LABELS, label } from '../labels'
import ResizeHandle from '../components/ResizeHandle.vue'
import PdfPreviewDrawer from '../components/PdfPreviewDrawer.vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const props = defineProps(['id'])

// --- List panel state ---
const worksList = ref([])
const listSearch = ref('')
const listPage = ref(1)
const listTotal = ref(0)
const listPerPage = 100
const listTotalPages = computed(() => Math.ceil(listTotal.value / listPerPage))
const listSortKey = ref('created_at')
const listSortDir = ref('desc')
const listSortOptions = [
  { label: '入库时间', value: 'created_at' },
  { label: '年份', value: 'year' },
  { label: '标题', value: 'title' },
  { label: '优先级', value: 'priority' },
]
const listWidth = ref(300)
const listPrevWidth = ref(300)
const listCollapsed = ref(false)

// --- Detail state ---
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
const showPdf = ref(false)

const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)

// --- Options ---
const docTypeOptions = [
  { label: '论文', value: 'paper' }, { label: '报告', value: 'report' },
  { label: '系统卡', value: 'system_card' }, { label: '基准测试', value: 'benchmark' },
  { label: '预印本', value: 'preprint' },
]
const langOptions = [
  { label: '英文', value: 'en' }, { label: '中文', value: 'zh' }, { label: '未知', value: 'unknown' },
]
const readStatusOptions = [
  { label: '未读', value: 'unread' }, { label: '已隔离', value: 'quarantined' },
]
const primaryDocTypeOptions = [
  { type: 'group', label: '功能定位类型（优先）', children: [
    { label: '系统卡/模型卡', value: 'system_model_card' },
    { label: '治理框架', value: 'governance_framework' },
    { label: '标准/指南', value: 'standard_guideline' },
    { label: '基准/数据集论文', value: 'benchmark_dataset_paper' },
    { label: '第三方评估报告', value: 'evaluation_report' },
  ]},
  { type: 'group', label: '文档形态类型', children: [
    { label: '技术报告', value: 'technical_report' },
    { label: '机构报告', value: 'institutional_report' },
    { label: '研究论文', value: 'research_article' },
    { label: '综述/评述', value: 'survey_review' },
    { label: '平台快照', value: 'platform_snapshot' },
    { label: '学位论文', value: 'thesis' },
    { label: '书章', value: 'book_chapter' },
    { label: '网页/博客', value: 'webpage_blog' },
    { label: '其他', value: 'other_literature' },
  ]},
  { type: 'group', label: '存在性标记', children: [
    { label: '工作流产物', value: 'workflow_artifact' },
    { label: '非文献', value: 'not_literature' },
  ]},
]
const pubStatusOptions = [
  { label: '已发表', value: 'published' }, { label: '预印本', value: 'preprint' },
  { label: '工作论文', value: 'working_paper' }, { label: '草案', value: 'draft' },
  { label: '持续更新文档', value: 'living_document' }, { label: '机构正式发布', value: 'institutional_release' },
  { label: '网页发布', value: 'webpage_release' }, { label: '未知', value: 'unknown' },
]
const ingestionStateOptions = [
  { label: '已核验', value: 'verified' }, { label: '待核查', value: 'needs_review' },
  { label: '暂留', value: 'provisional' }, { label: '已排除', value: 'excluded' },
  { label: '已废弃', value: 'deprecated' },
]
const priorityOptions = [
  { label: '核心必读 (P0)', value: 'P0' }, { label: '重要 (P1)', value: 'P1' },
  { label: '参考 (P2)', value: 'P2' }, { label: '边缘 (P3)', value: 'P3' },
  { label: '归档', value: 'archive' },
]
const tagGroupOptions = [
  { label: '阅读用途', value: 'reading_lane' }, { label: '贡献对象', value: 'artifact_focus' },
  { label: '风险领域', value: 'risk_domain' }, { label: '方法标签', value: 'method_tags' },
  { label: '处理标记', value: 'processing_flags' },
]
const relationTypeOptions = [
  { label: '翻译版本', value: 'translation_of' }, { label: '版本关系', value: 'version_of' },
  { label: '同一作品', value: 'same_work' }, { label: '组成部分', value: 'part_of' },
  { label: '取代', value: 'supersedes' }, { label: '非重复', value: 'not_duplicate' },
]

// --- Layout ---
const detailWidth = ref(null)
const layoutStyle = computed(() => {
  if (showPdf.value) {
    const detail = detailWidth.value === null ? 'minmax(320px, 1fr)' : `${detailWidth.value}px`
    return { gridTemplateColumns: `${listWidth.value}px 6px ${detail} 6px minmax(420px, 42vw)` }
  }
  return { gridTemplateColumns: `${listWidth.value}px 6px minmax(0, 1fr)` }
})

function onResizeList(w) { listWidth.value = Math.max(200, Math.min(w, 500)) }
function onResizeDetail(w) { detailWidth.value = Math.max(300, Math.min(w, 900)) }

function toggleListCollapse() {
  if (listCollapsed.value) {
    listWidth.value = listPrevWidth.value
    listCollapsed.value = false
  } else {
    listPrevWidth.value = listWidth.value
    listWidth.value = 48
    listCollapsed.value = true
  }
}

function togglePdf() { showPdf.value = !showPdf.value }

// --- Computed ---
const uniqueShaCount = computed(() => {
  if (!work.value?.source_files) return 0
  return new Set(work.value.source_files.map(s => s.content_sha256).filter(Boolean)).size
})

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
  return Object.entries(map).map(([k, v]) => ({ label: `${v} (${k})`, value: k }))
}

function isDuplicateSha(s) {
  if (!work.value?.source_files) return false
  return work.value.source_files.filter(f => f.content_sha256 === s.content_sha256).length > 1
}

// --- List ---
let listTimer = null
function debouncedLoadList() {
  clearTimeout(listTimer)
  listTimer = setTimeout(() => { listPage.value = 1; loadList() }, 300)
}

function toggleSortDir() {
  listSortDir.value = listSortDir.value === 'desc' ? 'asc' : 'desc'
  loadList()
}

async function loadList() {
  const params = {
    page: listPage.value,
    per_page: listPerPage,
    sort: listSortKey.value,
    order: listSortDir.value,
    classified_only: true,
  }
  if (listSearch.value) params.search = listSearch.value
  const q = new URLSearchParams(params).toString()
  const res = await getWorks('?' + q)
  worksList.value = res.works
  listTotal.value = res.total_matching
}

// --- Detail ---
async function loadWork() {
  work.value = await getWork(props.id)
  content.value = ''
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

async function addTag() {
  if (!newTag.value.tag_value) return
  await createTag(props.id, { tag_group: newTag.value.tag_group, tag_value: newTag.value.tag_value })
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

async function saveEdit() {
  const data = { ...editForm.value }
  data.authors = data.authors_str.split(';').map(s => s.trim()).filter(Boolean)
  delete data.authors_str
  await updateWork(props.id, data)
  editing.value = false
  await loadWork()
}

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

async function addRelation() {
  if (!newRel.value.targetId) return
  await createRelation({ work_id_a: props.id, work_id_b: newRel.value.targetId, relation_type: newRel.value.type })
  newRel.value.targetId = ''
  await loadWork()
}

async function removeRelation(r) {
  await deleteRelation({ work_id_a: r.work_id_a, work_id_b: r.work_id_b, relation_type: r.relation_type })
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
  } finally { quarantineLoading.value = false }
}

function restore() {
  dialog.warning({
    title: '恢复文献',
    content: '确认恢复此文献？',
    positiveText: '恢复', negativeText: '取消',
    onPositiveClick: async () => {
      await restoreWork(props.id)
      await loadWork()
      message.success('已恢复')
    },
  })
}

// Load list once, then load detail on id change
onMounted(loadList)
watch(() => props.id, loadWork, { immediate: true })
</script>

<style scoped>
.work-layout {
  display: grid; height: calc(100vh - 60px); overflow: hidden;
}

/* List panel */
.list-panel {
  display: flex; flex-direction: column; overflow: hidden; background: #fafbfc;
  border-right: 1px solid var(--line); min-width: 0;
}
.list-panel.collapsed .list-header,
.list-panel.collapsed .list-filters,
.list-panel.collapsed .list-body,
.list-panel.collapsed .n-pagination { display: none; }
.list-panel.collapsed .list-collapse-bar { writing-mode: vertical-rl; text-orientation: mixed; height: auto; flex: 1; }

.list-header {
  display: flex; align-items: center; justify-content: space-between; padding: 10px 12px 6px;
}
.list-header h2 { font-size: 16px; margin: 0; }
.full-link { font-size: 11px; color: var(--accent); text-decoration: none; }
.full-link:hover { text-decoration: underline; }

.list-filters {
  display: flex; gap: 4px; padding: 0 10px 8px; align-items: center;
}

.list-body { flex: 1; overflow-y: auto; }
.list-item {
  padding: 8px 12px; border-bottom: 1px solid var(--line); cursor: pointer;
}
.list-item:hover { background: #eef5ff; }
.list-item.selected { background: #dbeafe; border-left: 3px solid var(--accent); }
.list-item.quarantined { opacity: 0.5; }
.list-item-title { font-size: 13px; font-weight: 600; line-height: 1.4; }
.list-item-meta { display: flex; gap: 6px; align-items: center; font-size: 11px; margin-top: 2px; color: var(--muted); }
.type-chip { background: #ede9fe; color: #6d28d9; padding: 0 5px; border-radius: 3px; font-size: 10px; }
.priority-chip { padding: 0 5px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.priority-chip.P0 { background: #fee2e2; color: #991b1b; }
.priority-chip.P1 { background: #fef3c7; color: #92400e; }
.priority-chip.P2 { background: #dbeafe; color: #1e40af; }
.priority-chip.P3 { background: #f3f4f6; color: #6b7280; }
.priority-chip.archive { background: #f9fafb; color: #9ca3af; }

.list-empty { padding: 20px; text-align: center; color: var(--muted); font-size: 13px; }
.list-collapse-bar {
  height: 24px; display: flex; align-items: center; justify-content: center;
  border-top: 1px solid var(--line); cursor: pointer; font-size: 12px; color: var(--muted);
  background: #f8fafc; flex-shrink: 0;
}
.list-collapse-bar:hover { background: #eef2f7; color: var(--accent); }

/* Detail panel */
.detail-panel {
  overflow-y: auto; padding: 16px 24px; min-width: 0;
}
.empty-panel { display: flex; align-items: center; justify-content: center; }

.detail-header {
  display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;
}
.detail-header-left { min-width: 0; flex: 1; }
.detail-header-right { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.pdf-ext-link { font-size: 11px; color: var(--accent); text-decoration: none; }
.pdf-ext-link:hover { text-decoration: underline; }

h1 { font-size: 20px; margin: 0 0 4px; outline: none; line-height: 1.3; }
h1[contenteditable] { border-bottom: 2px solid var(--accent); padding-bottom: 2px; }

.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); }
.section h3 { font-size: 13px; text-transform: uppercase; color: #475467; margin-bottom: 8px; }
.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.section-header h3 { margin-bottom: 0; }

.kv { display: grid; grid-template-columns: 100px 1fr; gap: 6px 8px; font-size: 13px; }
.kv div:nth-child(odd) { color: var(--muted); }

.abstract-text { font-size: 13px; line-height: 1.6; color: #374151; margin: 0; }

.cls-tags { margin-top: 10px; }
.tag-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 4px 0; }
.tag-group { font-size: 12px; color: var(--muted); min-width: 80px; }
.tag-list { margin-bottom: 8px; }
.tag-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.add-tag { display: flex; gap: 8px; align-items: center; }

.file-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
.file-item.archived { opacity: 0.6; }
.file-name { font-weight: 600; font-size: 13px; }
.rel-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.add-rel { display: flex; gap: 8px; align-items: center; }
.content-preview { font-size: 12px; font-family: Consolas, monospace; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

.status-succeeded { color: var(--ok); font-weight: 600; }
.status-failed { color: var(--bad); font-weight: 600; }
.status-verified { color: var(--ok); }
.status-needs_review { color: #d97706; }
.status-quarantined { color: var(--bad); font-weight: 600; }
.priority-P0 { color: #991b1b; font-weight: 600; }
.priority-P1 { color: #92400e; font-weight: 600; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: #fff; border-radius: 8px; padding: 24px; width: 420px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; }
.modal-desc { margin: 0 0 16px; font-size: 13px; color: #6b7280; }
.modal-reason label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
