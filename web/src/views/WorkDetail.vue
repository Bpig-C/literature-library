<template>
  <div class="work-layout" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel" :class="{ collapsed: listCollapsed }">
      <div class="list-header">
        <h2>文献</h2>
        <router-link to="/works" class="full-link" title="完整筛选页面" @click="clearSavedFilters">完整</router-link>
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
          @click="router.push({ path: '/works/' + w.id, query: route.query })">
          <div class="list-item-title">{{ w.title || w.id }}</div>
          <div class="list-item-meta">
            <span>{{ formatListDate(w) }}</span>
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
        <div class="detail-header-left"><router-link class="mobile-list-link" to="/works">← 返回文献列表</router-link>
          <h1 :contenteditable="editing" @blur="onTitleBlur" ref="titleEl">
            {{ work.title || work.id }}
          </h1>
          <div class="muted tiny">{{ work.id }}</div>
        </div>
        <div class="detail-header-right">
          <label>PDF 来源 <select v-model="selectedPdfSourceId" aria-label="PDF 来源"><option v-for="source in pdfSources" :key="source.id" :value="source.id">{{ source.id }}</option></select></label>
          <n-button size="small" :disabled="!selectedPdfUrl" :type="showPdf ? 'primary' : 'default'" quaternary @click="togglePdf">
            {{ showPdf ? '关闭 PDF' : 'PDF' }}
          </n-button>
          <a v-if="selectedPdfUrl" :href="selectedPdfUrl" target="_blank" class="pdf-ext-link">外部打开</a>
          <span v-if="pdfSelectionError" role="alert">{{ pdfSelectionError }}</span>
        </div>
      </div>

      <!-- 工作流程条 -->
      <div class="workflow-bar">
        <div class="workflow-step" :class="workflowStepClass('source')">
          <span class="step-icon">1</span>
          <span class="step-label">源文件</span>
          <span class="step-status">{{ sourceStatus }}</span>
        </div>
        <div class="workflow-arrow">→</div>
        <div class="workflow-step" :class="workflowStepClass('parse')">
          <span class="step-icon">2</span>
          <span class="step-label">解析</span>
          <span class="step-status">{{ parseStatus }}</span>
          <n-button v-if="canTriggerParse" size="tiny" quaternary :loading="parseLoading" @click="triggerParse">触发</n-button>
        </div>
        <div class="workflow-arrow">→</div>
        <div class="workflow-step" :class="workflowStepClass('v5')">
          <span class="step-icon">3</span>
          <span class="step-label">A 原数据 · Work 级</span>
          <span class="step-status">{{ metadataStatus }}</span>
          <router-link :to="{ path: '/metadata-workspace', query: { work_id: props.id } }" class="step-link">查看 / 批量交给 Agent</router-link>
        </div>
        <div class="workflow-arrow">→</div>
        <div class="workflow-step" :class="workflowStepClass('research')">
          <span class="step-icon">4</span>
          <span class="step-label">研究来源 · C/D</span>
          <span class="step-status">{{ researchStageStatus }}</span>
          <router-link :to="{ path: '/research', query: { q: props.id } }" class="step-link">查看研究记录</router-link>
          <template v-if="canStageToResearch">
            <n-select
              v-model:value="stageBatchChoice"
              :options="stageBatchOptions"
              size="tiny"
              style="width: 190px"
              :loading="stageBatchesLoading"
              placeholder="仅送入研究库"
              clearable
            />
            <n-button size="tiny" quaternary :loading="stageLoading" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="stageToResearch">
              {{ stageBatchChoice ? '加入所选批次（新一轮）' : '送入研究库' }}
            </n-button>
          </template>
        </div>
      </div>
      <p class="muted tiny">A 可不建研究批次独立抽取；研究批次也可先规划，D 解释提交时再核对其 A 依赖。</p>

      <!-- 元数据 -->
      <div class="section">
        <div class="section-header">
          <h3>基础书目元数据</h3>
          <router-link :to="{ path: '/metadata-workspace', query: { work_id: props.id } }" class="step-link">查看 A 全字段、反馈与批量工单 →</router-link>
          <!-- B9(R6)：目录传播状态持久可见（失败待重试/已传播） -->
          <n-tag v-if="work?.metadata_propagation?.state?.status === 'failed'" type="error" size="small">
            目录传播失败，待重试（{{ work.metadata_propagation.state.error?.slice(0, 60) }}）
          </n-tag>
          <n-tag v-else-if="work?.metadata_propagation?.state?.status === 'propagated'" type="success" size="small">
            已传播到目录
          </n-tag>
          <n-tag v-if="projectionOrigin" size="small" :bordered="false" title="当前书目投影来源">
            投影来源：{{ projectionOrigin.origin_label || projectionOrigin.source_kind }}
          </n-tag>
          <n-tag v-else size="small" type="warning" :bordered="false" title="无活动书目投影">
            无活动投影（未达导出门槛）
          </n-tag>
          <n-button v-if="!editing" size="small" quaternary @click="startEdit">编辑</n-button>
          <template v-else>
            <n-button size="small" type="primary" @click="saveEdit">保存</n-button>
            <n-button size="small" quaternary @click="cancelEdit">取消</n-button>
          </template>
          <template v-if="!editing">
            <n-button v-if="work.read_status !== 'quarantined'" size="small" text type="error" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="quarantine">隔离</n-button>
            <n-button v-else size="small" text type="success" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="restore">恢复</n-button>
          </template>
        </div>
        <div class="kv">
          <div>作者</div>
          <div>
            <n-input v-if="editing" v-model:value="editForm.authors_str" size="small" placeholder="用分号分隔" />
            <span v-else>{{ (work.authors || []).join('; ') || '未知' }}</span>
          </div>
          <div>发布日期</div>
          <div>
            <template v-if="editing">
              <div class="date-edit-row">
                <n-input v-model:value.number="editForm.year" size="small" type="text" placeholder="年" style="width:70px" />
                <n-input v-model:value.number="editForm.month" size="small" type="text" placeholder="月" style="width:50px" />
                <n-input v-model:value.number="editForm.day" size="small" type="text" placeholder="日" style="width:50px" />
              </div>
            </template>
            <span v-else>{{ dateDisplay }}</span>
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
          <div>贡献方</div>
          <div>
            <template v-if="work.contributors?.length">
              <span v-for="(c, i) in work.contributors" :key="i">
                <n-tag size="small" :type="contribType(c.type)" round>{{ c.name }}</n-tag>
              </span>
              <span class="contrib-legend">
                <n-tag size="tiny" type="info" round>大学</n-tag>
                <n-tag size="tiny" type="warning" round>公司</n-tag>
                <n-tag size="tiny" type="error" round>政府</n-tag>
                <n-tag size="tiny" type="success" round>实验室</n-tag>
              </span>
            </template>
            <span v-else class="muted">—</span>
          </div>
          <div>链接</div><div><a v-if="work.url" :href="work.url" target="_blank">{{ work.url }}</a></div>
          <div>解析状态</div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span :class="'status-' + work.parse_status">{{ label(PARSE_STATUS_LABELS, work.parse_status) }}</span>
            <n-button size="small" quaternary :loading="parseLoading"
                      :disabled="work.parse_status === 'succeeded'"
                      @click="triggerParse">触发解析</n-button>
            <n-select v-model:value="parseBackend" size="tiny" style="width:190px"
                      :options="parseBackendOptions" :consistent-menu-width="false" />
            <n-button size="small" quaternary type="primary" :loading="parseLoading" :disabled="readOnly"
                      title="只读部署：写操作被服务端禁用" @click="reparseWork">重新解析</n-button>
          </div>
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

      <!-- 研究记录：只读显式 batch 中的 research tables -->
      <div class="section research-section">
        <div class="section-header research-section-header">
          <h3>研究记录</h3>
          <router-link :to="researchViewLink" class="full-link">在研究视图中打开</router-link>
        </div>
        <div v-if="!researchBatchId" class="research-empty">
          请先从研究视图选择明确的 batch_id，再打开单篇记录。系统不会自动选择最新轮次或混入 legacy analysis。
        </div>
        <n-spin v-else-if="researchLoading" size="small" />
        <div v-else-if="researchError" class="research-unavailable">
          研究记录暂时不可用，不影响文献详情与原文阅读。
          <n-button text type="primary" size="tiny" @click="loadResearch">重试</n-button>
        </div>
        <div v-else-if="researchRecords.length" class="research-records">
          <article v-for="(record, index) in researchRecords" :key="researchRecordKey(record, index)" class="research-card">
            <div class="research-card-head">
              <div>
                <strong>{{ researchRecordTitle(record, index) }}</strong>
                <span v-if="researchField(record, 'update_object')">更新对象：{{ readableResearchField(record, 'update_object') }}</span>
              </div>
            </div>

            <div v-if="interpretationNeedsReview(record)" class="ontology-review-note">
              解释状态为 stale：可能由 ontology 或上游原文记录修订触发；来源快照保持不变，不表示需要重新解析 PDF。
            </div>

            <div class="research-summary-grid">
              <div><span>研究作用</span><strong>{{ readableResearchField(record, 'research_role') }}</strong></div>
              <div><span>部署条件</span><strong>{{ readableResearchField(record, 'deployment_condition') }}</strong></div>
              <div><span>映射状态</span><strong>{{ researchStatusLabel(researchStatus(record, 'mapping_status'), 'mapping') }}</strong></div>
            </div>

            <div class="research-layer-grid">
              <section v-for="layer in researchLayers" :key="layer.key" class="research-layer-card" :class="{ missing: !researchLayerRecord(record, layer.key) }">
                <header><strong>{{ layer.label }}</strong><code>{{ researchLayerRecord(record, layer.key)?.id || '尚未生成' }}</code></header>
                <div>
                  <span v-for="state in researchLayerStatuses" :key="state.key">
                    <small>{{ state.label }}</small>
                    <n-tag size="small" :type="researchStatusType(researchLayerStatus(record, layer.key, state.key), state.context)">
                      {{ researchStatusLabel(researchLayerStatus(record, layer.key, state.key), state.context) }}
                    </n-tag>
                  </span>
                </div>
              </section>
            </div>
            <div class="research-adoption-policy" :class="{ warning: researchAdoptionGateMismatch(record) }">
              消费口径：可用基线 = 结构校验通过 + 独立 Agent 审查通过 + 内容稳定 + 有效；人工采纳是叠加判断，不参与该门槛，未读或人工待定的材料继续参与消费。原文记录存在本身不代表已经核验；对解释的局部人工采纳只覆盖其声明范围，不等于整条认可。
            </div>

            <ResearchRecordReadable :record="record" />
            <div class="research-provenance">
              <span>source_file_id</span><code>{{ researchSourceValue(record, 'source_file_id') }}</code>
              <span>parse_run_id</span><code>{{ researchSourceValue(record, 'parse_run_id') }}</code>
              <span>snapshot hash</span><code>{{ researchSourceValue(record, 'snapshot_hash') }}</code>
              <span>质量状态</span><strong>{{ researchSourceQuality(record) }}</strong>
            </div>
          </article>

        </div>
        <div v-else class="research-empty">当前 batch 没有这篇文献的 research 记录。文献与解析产物仍然保留。</div>
      </div>

      <!-- PLATFORM-003：全批次研究谱系（batch 无关，只读聚合） -->
      <div class="section">
        <div class="section-header">
          <h3>研究谱系（全批次）</h3>
          <n-tag v-if="profileTaskStatus" size="small" round
                 :type="profileTaskStatus === 'stable' ? 'success' : profileTaskStatus === 'excluded' ? 'default' : 'warning'">
            A 队列：{{ profileTaskStatus }}
          </n-tag>
        </div>
        <p class="muted tiny">
          按 work 聚合全部批次的 A/C/D/R、来源快照、反馈、人工采纳与推荐基线；多个合法研究范围并列展示，不按时间强选。
          stable / approved 只表示 Agent 稳定与独立核查，不代表人工认可或科学正确。
        </p>
        <div v-if="profileLoading" class="muted tiny">加载研究谱系…</div>
        <div v-else-if="profileError" class="research-empty">研究谱系暂不可用（研究库未初始化或服务未启动）。</div>
        <template v-else-if="researchProfile">
          <div class="research-summary-grid">
            <div><span>A 记录</span><strong>{{ researchProfile.metadata?.records?.length || 0 }} 版 · 头 {{ researchProfile.metadata?.head_record_id || '无' }}</strong></div>
            <div><span>研究来源</span><strong>{{ researchProfile.sources?.length || 0 }}</strong></div>
            <div><span>C 记录（全批）</span><strong>{{ researchProfile.source_records?.length || 0 }}</strong></div>
            <div><span>D 记录（全批）</span><strong>{{ researchProfile.interpretations?.length || 0 }}</strong></div>
            <div><span>引用对象</span><strong>{{ Object.values(researchProfile.references?.by_lifecycle || {}).reduce((a, b) => a + b, 0) || 0 }}（active {{ researchProfile.references?.by_lifecycle?.active || 0 }}）</strong></div>
            <div><span>开放反馈</span><strong>{{ researchProfile.feedback?.open?.length || 0 }}</strong></div>
          </div>
          <div v-if="!profileBaselines.length" class="research-empty">
            尚无跨批稳定解释基线；无 research source 的 work 仍可在 A 队列完成元数据闭环。
          </div>
          <article v-for="b in profileBaselines" :key="b.interpretation_id" class="research-record-card">
            <header>
              <strong>推荐基线候选 · {{ b.interpretation_id }} v{{ b.version }}</strong>
              <n-tag size="small" round :type="b.eligible_recommended ? 'success' : 'warning'">
                {{ b.eligible_recommended ? '依赖可用 · 可推荐' : '依赖阻断：' + (b.dependency_status || '') }}
              </n-tag>
            </header>
            <div class="research-summary-grid">
              <div><span>批次</span><code>{{ b.batch_id }}</code></div>
              <div><span>范围</span><code>{{ JSON.stringify(b.scope || {}) }}</code></div>
            </div>
            <p v-if="b.reason" class="muted tiny">{{ b.reason }}</p>
          </article>
        </template>
      </div>

      <!-- 旧目录分类只读保留；新分类进入解释记录与研究本体 -->
      <div class="section">
        <div class="section-header">
          <h3>历史目录分类（只读）</h3>
        </div>
        <p class="muted tiny">库务字段（文档类型/发布状态/入库状态/优先级）随 works 行展示；科学分类判断已迁移到 v5 研究解释记录。旧抽取标签只读归档。</p>
        <div class="kv">
          <div>主文档类型</div>
          <div>
<span>{{ label(PRIMARY_DOC_TYPE_LABELS, work.primary_doc_type) || '未知' }}</span>
          </div>
          <div>次要文档类型</div>
          <div>
<span>{{ label(PRIMARY_DOC_TYPE_LABELS, work.secondary_doc_type) || '—' }}</span>
          </div>
          <div>发布状态</div>
          <div>
<span>{{ label(PUBLICATION_STATUS_LABELS, work.publication_status) || '未知' }}</span>
          </div>
          <div>入库状态</div>
          <div>
<span>{{ label(INGESTION_STATE_LABELS, work.ingestion_state) || '未知' }}</span>
          </div>
          <div>优先级</div>
          <div>
<span :class="work.priority ? 'priority-' + work.priority : ''">{{ label(PRIORITY_LABELS, work.priority) || '未知' }}</span>
          </div>
        </div>

        <!-- LL-DECOUPLE-20260920：旧多值标签（阅读用途/关注对象/风险领域/方法标签）
             已退役；当前风险关联与分类判断来自 v5 研究解释记录。 -->
        <div class="cls-multi-tags">
          <div class="cls-tag-row">
            <span class="cls-tag-label">v5 稳定风险关联</span>
            <div class="cls-tag-chips">
              <span v-for="v in researchRiskValues" :key="v" class="tag-with-conf">
                <n-tag size="small" round>{{ v }}</n-tag>
              </span>
              <span v-if="!researchRiskValues.length" class="muted tiny">
                {{ work.research_summary?.available === false ? '研究库不可用' : '尚无活动、稳定且独立核查通过的解释记录' }}
              </span>
            </div>
          </div>
          <div class="cls-tag-row">
            <span class="cls-tag-label">v5 元数据</span>
            <div class="cls-tag-chips">
              <n-tag v-if="v5MetadataHead" size="small" round :type="v5MetadataHead.agent_review_status === 'approved' ? 'success' : 'warning'">
                {{ v5MetadataHead.agent_review_status }} · v{{ v5MetadataHead.version }}
              </n-tag>
              <span v-else class="muted tiny">尚无元数据记录</span>
            </div>
          </div>
          <p class="muted tiny" style="margin:8px 0 0">
            历史风险/方法标签已归档，可在
            <router-link :to="'/classification?search=' + encodeURIComponent(work.id)" class="step-link">历史分类（只读）</router-link>
            回查，不再作为当前结论展示。
          </p>
        </div>
      </div>

      <!-- 源文件 -->
      <div class="section" v-if="work.source_files?.length">
        <h3>源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ uniqueShaCount }} 个有效 / {{ work.source_files.length }} 个当前)</span></h3>
        <div v-for="s in work.source_files" :key="s.id" class="file-item">
          <span class="file-name">{{ s.original_name || s.id }}</span>
          <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
          <n-tag v-if="isDuplicateSha(s)" size="small" type="warning">重复</n-tag>
          <a :href="fixedPdfUrl(s.id)" target="_blank" v-if="s.file_ext === '.pdf' && fixedPdfUrl(s.id)" class="pdf-ext-link">查看 PDF</a>
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

      <!-- 内容预览：合并版（旁路资产，可溯源）/ 解析版渲染 / 解析源码 -->
      <!-- 三种含义严格区分：合并版=云 VLM 旁路资产；解析版渲染=解析产物 content.md
           的排版视图（非 PDF 原件）；解析源码=content.md 原文（保留 source 查看）。 -->
      <div class="section" v-if="content || contentError || mergedContent || mergedUnavailableReason">
        <p v-if="contentError" role="alert">{{ contentError }} <n-button size="small" @click="loadWork">重试正文</n-button></p>
        <p v-if="imageError" role="alert">{{ imageError }} <n-button size="small" @click="retryImages">重试图片</n-button></p>
        <details><summary>登记解析 / 页面问题（无固定快照时请 Agent 判断，避免绑定错版）</summary><FeedbackPanel :record="{ work_id: work.id }" /></details>
        <h3 style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          内容预览 <span v-if="materialSelector.version" class="muted tiny">材料版本 {{ materialSelector.version }}</span>
          <label>解析记录 <select v-model="selectedParseId" @change="loadWork"><option value="">当前解析</option><option v-for="run in work.parse_runs?.filter(r => r.status === 'succeeded')" :key="run.id" :value="run.id">{{ run.source_file_id }} · {{ run.id }}</option></select></label>
          <n-radio-group v-model:value="contentMode" size="tiny">
            <n-radio-button value="merged" title="仅云 VLM 解析生成；点击查看本篇合并版不可用的真实原因">合并版</n-radio-button>
            <n-radio-button value="render">解析版渲染</n-radio-button>
            <n-radio-button value="raw">解析源码</n-radio-button>
          </n-radio-group>
          <span v-if="contentMode === 'merged' && mergedContent" class="muted tiny">含解析图片</span>
          <a v-if="contentMode === 'merged' && mergedContent" class="muted tiny" :href="workDetailJsonUrl(props.id, materialSelector)" target="_blank">合并诊断 JSON</a>
          <a v-if="content && fixedPdfUrl(materialSelector.source_file_id)" class="muted tiny" :href="fixedPdfUrl(materialSelector.source_file_id)" target="_blank">查看原件 PDF</a>
        </h3>
        <p v-if="contentMode === 'merged' && !mergedContent && mergedUnavailableReason" class="content-mode-note">
          {{ mergedUnavailableReason }}
        </p>
        <p v-else-if="contentMode === 'merged' && mergedContent" class="content-mode-note">合并版为云 VLM 解析旁路资产（MinerU 结构 + PyMuPDF 样式），不是 PDF 原件。</p>
        <p v-else-if="contentMode === 'render'" class="content-mode-note">解析版渲染来自解析产物 content.md（{{ parseRouteLabel }}），用于按需核对；公式与表格为解析文本的排版，不代表 PDF 原版面。</p>
        <p v-else-if="contentMode === 'raw'" class="content-mode-note">解析源码即 content.md 原文，供精确核对与引用定位。</p>
        <div v-if="contentMode === 'merged' && mergedContent" class="content-markdown" v-html="mergedHtml" @error.capture="onImageError"></div>
        <div v-else-if="contentMode === 'render' && content" class="content-markdown" v-html="contentHtml" @error.capture="onImageError"></div>
        <pre v-else-if="contentMode === 'raw' && content" class="content-preview">{{ content }}</pre>
        <p v-else class="muted tiny">解析产物尚未读取到。</p>
      </div>
    </div>
    <div v-else class="detail-panel empty-panel">
      <n-spin size="large" />
    </div>

    <ResizeHandle v-if="showPdf" @resize="onResizeDetail" />

    <!-- PDF drawer -->
    <PdfPreviewDrawer v-if="showPdf && selectedPdfUrl" :url="selectedPdfUrl" :work-id="props.id" @close="showPdf = false" />

    <!-- 悬浮任务入口（工单工作包 C）：有研究记录时提供三模式任务面板 -->
    <AgentTaskFab v-if="work" :record="{ work_id: work.id }" initial-mode="organize" />

    <!-- Quarantine Modal -->
    <n-modal v-model:show="showQuarantineModal" preset="card" title="隔离文献" style="width: 460px">
      <p class="modal-desc">隔离后，这篇文献会从默认列表和批量操作中移出。</p>
      <div class="modal-reasons">
        <label v-for="r in QUARANTINE_REASONS" :key="r.key" class="reason-option">
          <input type="radio" v-model="quarantineReason" :value="r.key" />
          <span>{{ r.label }}</span>
        </label>
      </div>
      <template #action>
        <n-button @click="showQuarantineModal = false">取消</n-button>
        <n-button type="error" :disabled="!quarantineReason || quarantineLoading" :loading="quarantineLoading" @click="confirmQuarantine">确认隔离</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { useRuntimeMode } from '../composables/useRuntimeMode'
const { readOnly } = useRuntimeMode()
import { getWorks, getWork, getOverview, getResearchWork, getResearchWorkProfile, updateWork, createRelation, deleteRelation, quarantineWork, restoreWork, contentUrl, pdfUrl, workImageUrl, mergedContentUrl, workDetailJsonUrl, parseTrigger, stageWorkToResearch, getMaterialSelection } from '../api'
import { renderMarkdown } from '../utils/markdown'
import { readMaterial, freezeMaterialSelection } from '../utils/storage-feedback'
import { getPdfSelection } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, PUBLICATION_STATUS_LABELS, INGESTION_STATE_LABELS, PRIORITY_LABELS, LANGUAGE_LABELS, READ_STATUS_LABELS, PARSE_STATUS_LABELS, RELATION_TYPE_LABELS, label } from '../labels'
import { useNextStep } from '../composables/useNextStep'
import ResizeHandle from '../components/ResizeHandle.vue'
import EmptyState from '../components/EmptyState.vue'
import ResearchRecordReadable from '../components/research/ResearchRecordReadable.vue'
import AgentTaskFab from '../components/research/AgentTaskFab.vue'
import FeedbackPanel from '../components/research/FeedbackPanel.vue'
import { listFieldDisplay } from '../researchPresentation'
import {
  normalizeBatchChoice,
  stageErrorText,
  submitStageWork,
  stageSuccessRoute,
} from '../stageResearch'

const PdfPreviewDrawer = defineAsyncComponent(() => import('../components/PdfPreviewDrawer.vue'))

const router = useRouter()
const route = useRoute()
const message = useMessage()
const dialog = useDialog()
const { notifyNext } = useNextStep()

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
// Persisted filter state from Works page (survives list refreshes within this session)
const savedFilters = ref(null)

// --- Detail state ---
const work = ref(null)
const content = ref('')
const selectedParseId = ref('')
const materialSelector = ref({})
const pdfSelections = ref({})
const selectedPdfSourceId = ref('')
const pdfSelectionError = ref('')
const pdfSources = computed(() => (work.value?.source_files || []).filter(s => s.file_ext === '.pdf'))
function fixedPdfUrl(sourceId) {
  const fixed = pdfSelections.value[sourceId]
  return fixed ? pdfUrl(props.id, fixed.source_file_id, fixed.pdf_version) : ''
}
const selectedPdfUrl = computed(() => fixedPdfUrl(selectedPdfSourceId.value))
let materialLoadGeneration = 0
const contentError = ref('')
const imageError = ref('')
const failedImages = new Set()
function onImageError(event) {
  if (event.target?.tagName !== 'IMG') return
  failedImages.add(event.target)
  imageError.value = '部分解析图片读取失败，请重试或核查材料状态。'
}
function retryImages() {
  for (const image of failedImages) image.src = image.src
  failedImages.clear()
  imageError.value = ''
}
const researchDetail = ref(null)
const researchLoading = ref(false)
const researchError = ref(false)
// 内容预览模式：merged=合并版（MinerU结构+PyMuPDF样式，仅 vlm 解析有）；
// render=原版渲染（content.md）；raw=原版原文
const contentMode = ref('merged')
const mergedContent = ref('')
// 合并版不可用的真实原因：区分“产物不存在”与“读取失败”，并说明解析路线；
// 不误报“图片型 PDF 不支持”，也不默认触发付费云重解析。
const mergedUnavailableReason = ref('')
// 重解析后端选择：auto=D13 自动路由；pymupdf/vlm=强制后端
const parseBackend = ref('auto')
const parseBackendOptions = [
  { label: '路由：自动', value: 'auto' },
  { label: '强制 PyMuPDF（本地，快）', value: 'pymupdf' },
  { label: '强制云 VLM（保留版面图）', value: 'vlm' },
]
const editing = ref(false)
const editForm = ref({})
const titleEl = ref(null)
const newRel = ref({ targetId: '', type: 'translation_of' })
const stageLoading = ref(false)
const showPdf = ref(false)
const parseLoading = ref(false)

function researchResponseBody() {
  return researchDetail.value?.data ?? researchDetail.value ?? {}
}

function normalizeResearchList(value) {
  if (!value) return []
  return Array.isArray(value) ? value : [value]
}

const allResearchRecords = computed(() => {
  const body = researchResponseBody()
  const records = Array.isArray(body) ? body : body.items || []
  return normalizeResearchList(records).map(item => ({
    ...item,
    batch_id: item?.batch_id || body?.batch_id || researchBatchId.value,
  }))
})

const researchRecords = computed(() => allResearchRecords.value)
const researchBatchId = computed(() => String(route.query.batch_id || ''))
const researchViewLink = computed(() => ({
  path: '/research',
  query: researchBatchId.value ? { batch_id: researchBatchId.value, q: props.id } : {},
}))
const researchLayers = [
  { key: 'source_record', label: '原文层（source_record）' },
  { key: 'interpretation', label: '解释层（interpretation）' },
]
const researchLayerStatuses = [
  { key: 'validation_status', label: '结构与证据锚点', context: 'validation' },
  { key: 'agent_review_status', label: 'Agent 审阅', context: 'agent' },
  { key: 'human_adoption_status', label: '人工采纳', context: 'human' },
  { key: 'validity_status', label: '有效性', context: 'validity' },
]

function researchRawValue(value) {
  return value && typeof value === 'object' && 'value' in value ? value.value : value
}

function researchField(record, key) {
  if (['update_object', 'research_role', 'deployment_condition'].includes(key)) {
    return researchRawValue(record?.interpretation?.payload?.[key])
  }
  return researchRawValue(
    record?.[key]
    ?? record?.interpretation?.[key]
    ?? record?.interpretation?.payload?.[key]
    ?? record?.source_record?.[key]
    ?? record?.source_record?.payload?.[key]
  )
}

function formatResearchValue(value, fallback = '—') {
  if (value === undefined || value === null || value === '') return fallback
  if (Array.isArray(value)) return value.length ? value.map(v => formatResearchValue(v, '')).filter(Boolean).join('；') : fallback
  if (typeof value === 'object') return Object.entries(value).map(([k, v]) => `${k}: ${formatResearchValue(v, '')}`).join('；') || fallback
  return String(value)
}

function readableResearchField(record, key) { return listFieldDisplay(record, key) }

function researchStatus(record, key) {
  const value = key === 'mapping_status'
    ? (record?.mapping_status ?? record?.interpretation?.payload?.mapping_status)
    : researchField(record, key)
  if (value === undefined || value === null || value === '') return 'unknown'
  return String(value).toLowerCase()
}

function researchStatusLabel(status, context) {
  const labels = {
    validation: { pending: '待验证', passed: '验证通过', failed: '验证失败' },
    agent: { pending: '待 Agent 审阅', approved: 'Agent 已通过', needs_revision: 'Agent 要求修订', rejected: 'Agent 已拒绝' },
    human: { pending: '待人工采纳', adopted: '人工已采纳', rejected: '人工未采纳' },
    mapping: { mapped: '已映射', partially_mapped: '部分映射', unmapped: '未映射', ambiguous: '映射有歧义' },
    validity: { active: '有效', stale: '待重审', superseded: '已被替代' },
  }
  if (status === 'missing') return '尚未生成'
  if (status === 'unknown') return '状态未提供'
  return labels[context]?.[status] || status || '未知'
}

function researchStatusType(status, context) {
  if (context === 'human' && status === 'adopted') return 'success'
  if (context === 'agent' && status === 'approved') return 'info'
  if (context === 'validation' && status === 'passed') return 'success'
  if (context === 'mapping' && status === 'mapped') return 'success'
  if (context === 'validity' && status === 'active') return 'success'
  if (['rejected', 'failed'].includes(status)) return 'error'
  if (['needs_revision', 'stale', 'superseded', 'partially_mapped', 'ambiguous'].includes(status)) return 'warning'
  return 'default'
}

function researchLayerRecord(record, layer) { return record?.[layer] || null }
function researchLayerStatus(record, layer, key) {
  const layerValue = researchLayerRecord(record, layer)
  if (!layerValue) return 'missing'
  const value = layerValue?.[key]
  return value === undefined || value === null || value === '' ? 'unknown' : String(value).toLowerCase()
}
function researchAdoptionGateMismatch(record) {
  if (researchLayerStatus(record, 'interpretation', 'human_adoption_status') !== 'adopted') return false
  return researchLayerStatus(record, 'source_record', 'validation_status') !== 'passed'
    || researchLayerStatus(record, 'source_record', 'agent_review_status') !== 'approved'
    || researchLayerStatus(record, 'source_record', 'human_adoption_status') !== 'adopted'
    || researchLayerStatus(record, 'source_record', 'validity_status') !== 'active'
    || researchLayerStatus(record, 'interpretation', 'validation_status') !== 'passed'
    || researchLayerStatus(record, 'interpretation', 'agent_review_status') !== 'approved'
    || researchLayerStatus(record, 'interpretation', 'validity_status') !== 'active'
}

function researchRecordKey(record, index) { return record?.interpretation?.id || record?.source_record?.id || record?.source?.id || index }
function researchRecordTitle(record, index) { return record?.source?.citation_key || record?.source?.work_id || `研究记录 ${index + 1}` }
function researchSourceObject(record) { return record?.source || {} }
function researchSourceValue(record, key) {
  const source = researchSourceObject(record)
  const aliases = key === 'snapshot_hash' ? ['content_sha256', 'source_sha256'] : [key]
  for (const alias of aliases) {
    const value = record?.snapshot?.[alias] ?? source?.[alias] ?? record?.[alias]
    if (value !== undefined && value !== null && value !== '') return formatResearchValue(value)
  }
  return '—'
}
function researchSourceQuality(record) {
  const source = researchSourceObject(record)
  if (source?.parse_exists === false) return '解析产物缺失'
  const quality = source?.parse_quality
  return { unchecked: '未检查', passed: '解析质量通过', failed: '解析质量失败' }[quality] || formatResearchValue(quality)
}
function interpretationNeedsReview(record) {
  return record?.interpretation?.validity_status === 'stale'
}

const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)
const QUARANTINE_REASONS = [
  { key: 'bad_source', label: '坏源：PDF 内容为空、反爬页、扫描损坏等' },
  { key: 'out_of_scope', label: '不在范围：不属于当前研究主题或综述范围' },
  { key: 'not_literature', label: '非文献：不是论文、报告、标准等目标文献' },
  { key: 'duplicate_residual', label: '重复残留：已由其他 work 覆盖' },
  { key: 'needs_rerun', label: '待重跑：主题对，但上传文档本身有问题' },
  { key: 'user_removed', label: '用户移除：明确不想保留' },
]

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

function isDuplicateSha(s) {
  if (!work.value?.source_files) return false
  return work.value.source_files.filter(f => f.content_sha256 === s.content_sha256).length > 1
}

function contribType(type) {
  if (type === 'university') return 'info'
  if (type === 'company') return 'warning'
  if (type === 'government') return 'error'
  if (type === 'lab') return 'success'
  return 'default'
}

function formatListDate(w) {
  try {
    const pdj = w.publication_date_json ? JSON.parse(w.publication_date_json) : null
    if (pdj && typeof pdj === 'object') {
      const parts = []
      if (pdj.year) parts.push(pdj.year)
      if (pdj.month) parts.push(String(pdj.month).padStart(2, '0'))
      if (pdj.day) parts.push(String(pdj.day).padStart(2, '0'))
      if (parts.length > 1) return parts.join('-')
    }
  } catch {}
  return w.year || ''
}


// Workflow status computed properties
const sourceStatus = computed(() => {
  if (!work.value) return '未知'
  return work.value.source_files?.length ? '已入库' : '无源文件'
})

const parseStatus = computed(() => {
  if (!work.value) return '未知'
  const s = work.value.parse_status
  if (s === 'succeeded') return '已完成'
  if (s === 'pending') return '待解析'
  if (s === 'failed') return '失败'
  return s || '未知'
})

// LL-DECOUPLE-20260920：旧抽取状态退役；v5 元数据/研究接力状态取而代之。
const researchSummary = computed(() => work.value?.research_summary || null)

const v5MetadataHead = computed(() => researchSummary.value?.metadata_head || null)

const metadataStatus = computed(() => {
  const head = v5MetadataHead.value
  if (!head) return researchSummary.value?.available === false ? '研究库不可用' : '尚无记录'
  if (head.agent_review_status === 'approved' && head.content_state === 'stable') return '已核查稳定'
  if (head.agent_review_status === 'approved') return `已核准（${head.content_state}）`
  return `${head.agent_review_status || '待处理'}`
})

const researchStageStatus = computed(() => {
  const rs = researchSummary.value
  if (!rs) return '未知'
  if (rs.available === false) return '研究库不可用'
  return rs.staged ? '已进入研究库' : '待送入'
})

const canStageToResearch = computed(() => {
  const rs = researchSummary.value
  return Boolean(work.value && work.value.parse_status === 'succeeded'
    && rs && rs.available
    && work.value.read_status !== 'quarantined')
})

// R1 B3：加入已有批次。v5 批次是不可变计划，加入所选批次会创建带
// parent_batch_id 的新一轮（原批次保持不变），界面上明示。
watch(researchBatchId, (value) => {
  stageBatchChoice.value = normalizeBatchChoice(value)
})

const stageBatchOptions = ref([])
const stageBatchesLoading = ref(false)
const stageBatchChoice = ref(null)

async function loadStageBatches() {
  stageBatchesLoading.value = true
  try {
    const res = await getOverview()
    const batches = res?.research?.batches || []
    stageBatchOptions.value = batches.map(b => ({
      label: `${b.name}（${b.id}${b.works ? ' · ' + b.works + ' 篇' : ''}）`,
      value: b.id,
    }))
  } catch {
    stageBatchOptions.value = []
  } finally {
    stageBatchesLoading.value = false
  }
}

const researchRiskValues = computed(() => {
  const records = researchSummary.value?.interpretations || []
  const values = new Set()
  for (const r of records) {
    // Detail chips are a compact reliable-baseline view.  Candidates and
    // needs-revision records remain visible in the research view, but must not
    // look like the work's current stable classification here.
    if (r.validity_status !== 'active'
      || r.content_state !== 'stable'
      || r.agent_review_status !== 'approved') continue
    for (const v of (r.risk_phenomena || [])) values.add(v)
  }
  return [...values].sort()
})

const projectionOrigin = computed(() => work.value?.bibliographic_projection || null)

const canTriggerParse = computed(() => {
  return work.value && work.value.parse_status !== 'succeeded'
})

// content.md 渲染为 markdown+图片：相对 images/ 引用改写到后端静态端点
function markdownToHtml(md) {
  return renderMarkdown(md, {
    resolveImageSrc: (src) => {
      const m = /^\.?\/?images\/(.+)$/.exec(String(src || '').trim())
      if (m) return workImageUrl(props.id, m[1], materialSelector.value)
      return src
    },
  })
}

const contentHtml = computed(() => {
  if (!content.value || contentMode.value !== 'render') return ''
  return markdownToHtml(content.value)
})

// 合并版（MinerU 结构 + PyMuPDF 样式）渲染；图片路径与原版同一套 images/ 契约
const mergedHtml = computed(() => {
  if (!mergedContent.value || contentMode.value !== 'merged') return ''
  return markdownToHtml(mergedContent.value)
})

const hasParsedImages = computed(() => /\]\(\.?\/?images\//.test(content.value || ''))

const hasMergedImages = computed(() => /\]\([^)]*images\//.test(mergedContent.value || ''))


function workflowStepClass(step) {
  if (!work.value) return ''
  switch (step) {
    case 'source':
      return work.value.source_files?.length ? 'completed' : 'pending'
    case 'parse':
      return work.value.parse_status === 'succeeded' ? 'completed' :
             work.value.parse_status === 'pending' ? 'in-progress' : 'pending'
    case 'research': {
      const rs = work.value.research_summary
      if (!rs || rs.available === false) return 'pending'
      return rs.staged ? 'completed' : 'in-progress'
    }
    case 'v5': {
      const head = work.value.research_summary?.metadata_head
      if (!head) return 'pending'
      return (head.agent_review_status === 'approved' && head.content_state === 'stable')
        ? 'completed' : 'in-progress'
    }
    default:
      return ''
  }
}

// Date display from publication_date_json
const dateDisplay = computed(() => {
  if (!work.value) return ''
  try {
    const pdj = work.value.publication_date_json ? JSON.parse(work.value.publication_date_json) : null
    if (pdj && typeof pdj === 'object') {
      const parts = []
      if (pdj.year) parts.push(pdj.year)
      if (pdj.month) parts.push(String(pdj.month).padStart(2, '0'))
      if (pdj.day) parts.push(String(pdj.day).padStart(2, '0'))
      if (parts.length > 1) return parts.join('-')
      if (pdj.raw) return pdj.raw
    }
  } catch {}
  return work.value.year || ''
})

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
  // On first call, read filter state from sessionStorage (set by Works page)
  if (!savedFilters.value) {
    try {
      const raw = sessionStorage.getItem('works_filters')
      if (raw) savedFilters.value = JSON.parse(raw)
    } catch {}
  }

  const params = {
    page: listPage.value,
    per_page: listPerPage,
    sort: listSortKey.value,
    order: listSortDir.value,
  }
  // Apply persisted filters, or default to classified_only
  if (savedFilters.value) {
    const f = savedFilters.value
    params.classified_only = f.classified_only || false
    // List's own search/sort override saved filters
    if (listSearch.value) {
      params.search = listSearch.value
    } else if (f.search) {
      params.search = f.search
    }
    if (f.status && f.status !== 'all') params.status = f.status
    if (f.doc_type && f.doc_type !== 'all') params.doc_type = f.doc_type
    if (f.language && f.language !== 'all') params.language = f.language
    if (f.primary_doc_type) params.primary_doc_type = f.primary_doc_type
    if (f.publication_status) params.publication_status = f.publication_status
    if (f.ingestion_state) params.ingestion_state = f.ingestion_state
    if (f.priority) params.priority = f.priority
    if (f.reading_lane?.length) params.reading_lane = f.reading_lane
    if (f.risk_domain?.length) params.risk_domain = f.risk_domain
    if (f.artifact_focus?.length) params.artifact_focus = f.artifact_focus
  } else {
    params.classified_only = true
    if (listSearch.value) params.search = listSearch.value
  }
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      searchParams.append(key, value)
    }
  }
  // Use repeated params for array values (matches Works.vue behavior)
  const arrayParams = { reading_lane: params.reading_lane, risk_domain: params.risk_domain, artifact_focus: params.artifact_focus }
  for (const [key, values] of Object.entries(arrayParams)) {
    if (Array.isArray(values)) {
      searchParams.delete(key)
      for (const v of values) searchParams.append(key, v)
    }
  }
  const q = searchParams.toString()
  const res = await getWorks('?' + q)
  worksList.value = res.works
  listTotal.value = res.total_matching
}

function clearSavedFilters() {
  savedFilters.value = null
  sessionStorage.removeItem('works_filters')
}

// --- Detail ---
// 当前解析路线人读标签（backend/parse_method 来自 literature_parse_runs）
const parseRouteLabel = computed(() => {
  const runs = work.value?.parse_runs || []
  if (!runs.length) return '解析路线未报告'
  const latest = runs[0]
  const backend = latest.backend || 'unknown'
  const routeNames = { pipeline: '本地 pipeline 路线', pymupdf: '本地 PyMuPDF 路线', vlm: '云 VLM 路线', auto: 'auto 路由' }
  return routeNames[backend] || `解析路线 ${backend}`
})

async function loadWork() {
  const generation = ++materialLoadGeneration
  const workId = props.id
  // Clear rendered text before changing any selector, including a Work switch.
  content.value = ''
  contentError.value = ''
  imageError.value = ''
  failedImages.clear()
  mergedContent.value = ''
  mergedUnavailableReason.value = ''
  pdfSelections.value = {}
  pdfSelectionError.value = ''
  let selector
  try {
    const detail = await getWork(workId)
    if (generation !== materialLoadGeneration) return
    work.value = detail
    const selections = await Promise.allSettled((detail.source_files || []).filter(s => s.file_ext === '.pdf').map(s => getPdfSelection(workId,s.id)))
    if (generation !== materialLoadGeneration) return
    for (const result of selections) {
      if (result.status === 'fulfilled' && Number.isInteger(result.value.pdf_version) && result.value.pdf_version > 0) {
        const fixed = Object.freeze({source_file_id:result.value.source_file_id,pdf_version:result.value.pdf_version})
        pdfSelections.value[fixed.source_file_id] = fixed
      } else pdfSelectionError.value = '部分 PDF 来源版本未能读取，请重新加载。'
    }
    if (!pdfSelections.value[selectedPdfSourceId.value]) selectedPdfSourceId.value = Object.keys(pdfSelections.value).sort()[0] || ''
    const runs = (detail.parse_runs || []).filter(run => run.status === 'succeeded')
      .sort((a, b) => String(b.finished_at || '').localeCompare(String(a.finished_at || '')) || String(b.id).localeCompare(String(a.id)))
    if (!runs.some(run => run.id === selectedParseId.value)) selectedParseId.value = runs[0]?.id || ''
    selector = freezeMaterialSelection(await getMaterialSelection(workId, { parse_run_id: selectedParseId.value }))
    if (generation !== materialLoadGeneration) return
    materialSelector.value = selector
    if (pdfSelections.value[selector.source_file_id]) selectedPdfSourceId.value = selector.source_file_id
    const res = await fetch(contentUrl(workId, selector), { cache: 'no-store' })
    const text = await readMaterial(res)
    if (generation !== materialLoadGeneration) return
    content.value = text
  } catch (error) {
    if (generation !== materialLoadGeneration) return
    contentError.value = error.message || '正文读取失败，请重试。'
    if (!selector) { await loadResearch(); return }
  }
  // 合并版旁路资产（仅云 VLM 解析有）：404=产物不存在（如本地 pipeline 路线）；
  // 其他状态=读取失败。no-store：force 重解析会同路径覆盖产物，绝不能读缓存旧响应
  try {
    const mres = await fetch(mergedContentUrl(workId, selector), { cache: 'no-store' })
    const text = mres.ok ? await mres.text() : ''
    if (generation !== materialLoadGeneration) return
    if (mres.ok) mergedContent.value = text
    else if (mres.status === 404) {
      mergedUnavailableReason.value =
        `合并版产物不存在（HTTP 404）：当前解析路线为${parseRouteLabel.value}，` +
        '合并版仅在云 VLM 路线成功后生成。这不是“图片型 PDF 不受支持”，本页也不会自动触发付费云重解析；如需合并版，可在上方解析状态行选择“强制云 VLM”后手动重新解析。'
    } else {
      mergedUnavailableReason.value = `合并版读取失败（HTTP ${mres.status}），产物是否存在未确认。`
    }
  } catch {
    if (generation !== materialLoadGeneration) return
    mergedUnavailableReason.value = '合并版读取失败（网络错误）；请确认服务可用后重试。'
  }
  if (mergedUnavailableReason.value && contentMode.value === 'merged') {
    contentMode.value = 'render'
  }
  if (generation === materialLoadGeneration) await loadResearch()
}

async function loadResearch() {
  if (!researchBatchId.value) {
    researchLoading.value = false
    researchError.value = false
    researchDetail.value = null
    return
  }
  researchLoading.value = true
  researchError.value = false
  researchDetail.value = null
  try {
    researchDetail.value = await getResearchWork(props.id, { batch_id: researchBatchId.value })
  } catch (error) {
    if (error?.status === 404) researchDetail.value = { items: [] }
    else researchError.value = true
  } finally {
    researchLoading.value = false
  }
}


function startEdit() {
  let month = null, day = null
  try {
    const pdj = work.value.publication_date_json ? JSON.parse(work.value.publication_date_json) : null
    if (pdj) { month = pdj.month || null; day = pdj.day || null }
  } catch {}
  editForm.value = {
    title: work.value.title,
    authors_str: (work.value.authors || []).join('; '),
    year: work.value.year,
    month,
    day,
    doc_type: work.value.doc_type,
    language: work.value.language,
    read_status: work.value.read_status,
  }
  editing.value = true
}
function cancelEdit() { editing.value = false }

function onTitleBlur(e) {
  // Keep the editable title, the display value, and the submission form in sync.
  // saveEdit() submits editForm, so the edited title must land there — otherwise
  // the user's title change is silently dropped on save.
  const t = (e.target.innerText || '').trim()
  work.value.title = t
  if (editForm.value) editForm.value.title = t
}

async function saveEdit() {
  const data = { ...editForm.value }
  data.authors = data.authors_str.split(';').map(s => s.trim()).filter(Boolean)
  delete data.authors_str
  // Build publication_date_json from year/month/day
  const pdj = { year: data.year || null, month: data.month || null, day: data.day || null }
  if (pdj.year || pdj.month || pdj.day) {
    data.publication_date_json = JSON.stringify(pdj)
  }
  delete data.month
  delete data.day
  try {
    const result = await updateWork(props.id, data)
    editing.value = false
    await loadWork()
    await loadList()
    // B9(R6): 类型/状态修改进入元数据修订（待核查），如实告知当前书目未变
    if (result?.type_note) {
      message.info(result.type_note)
    }
  } catch (e) {
    message.error(backendReason(e) || ('保存失败：' + (e.message || e)))
  }
}

// B9: surface the backend refusal reason (e.g. the v5 classification
// readonly notice) instead of a bare HTTP status string.
function backendReason(e) {
  try {
    const parsed = JSON.parse(e?.detail || '')
    const detail = parsed?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') return detail.message || detail.error || JSON.stringify(detail)
    return parsed?.message || ''
  } catch { return '' }
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

// 同步解析：born-digital 走 PyMuPDF（秒级）；扫描型走 cloud vlm 可能耗时数分钟，
// 期间按钮置 loading。成功后用 loadWork() 全量刷新（含 content.md 预览）。
async function triggerParse() {
  parseLoading.value = true
  try {
    const res = await parseTrigger({ work_ids: [props.id] })
    const r = (res.results || [])[0] || {}
    // 解析成功后的下一步（元数据抽取）在本页工作流条上操作，接力提示不跳转
    if (r.status === 'succeeded') {
      notifyNext(`解析完成${r.backend ? ' (' + r.backend + ')' : ''}，可以继续元数据抽取`, { label: '继续元数据抽取' })
    } else {
      message.success(`解析：${r.status || '?'}${r.backend ? ' (' + r.backend + ')' : ''}`)
    }
    await loadWork()  // 刷新 parse_status 徽标 + content.md 预览
  } catch (e) {
    message.error('触发解析失败：' + e.message)
  } finally {
    parseLoading.value = false
  }
}

// 强制重解析（force=true，不限 pending 状态），后端按下拉选择：
// PyMuPDF 本地快但只有文本层栅格图；云 VLM 保留版面图表但耗时数分钟且耗额度。
async function reparseWork() {
  parseLoading.value = true
  try {
    const res = await parseTrigger({
      work_ids: [props.id],
      force: true,
      backend: parseBackend.value,
    })
    const r = (res.results || [])[0] || {}
    if (r.status === 'succeeded') {
      notifyNext(`重解析完成 (${r.backend || parseBackend.value})，content.md 已更新`, { label: '查看内容预览' })
    } else {
      message.warning(`重解析：${r.status || '?'} — ${r.error || ''}`)
    }
    await loadWork()
  } catch (e) {
    message.error('重解析失败：' + e.message)
  } finally {
    parseLoading.value = false
  }
}

async function stageToResearch() {
  stageLoading.value = true
  try {
    const batchId = normalizeBatchChoice(stageBatchChoice.value)
    const { result: res } = await submitStageWork(
      stageWorkToResearch, props.id, batchId)
    if (batchId && res.batch) {
      const b = res.batch
      if (b.round_created) {
        message.success(
          `已创建批次 ${b.batch_id} 作为所选批次的新一轮（parent=${b.parent_batch_id}，共 ${b.items} 项）；原批次保持不变`)
        await router.push(stageSuccessRoute(res))
      } else {
        notifyNext(
          `该文献已在批次 ${b.batch_id} 及其后续轮次中（${b.reason || '幂等'}），未重复建轮`,
          { label: '查看批次', to: { path: '/research', query: { batch_id: b.batch_id } } })
      }
    } else {
      notifyNext(
        res.created ? '已送入研究库；可在研究视图规划批次并生成 v5 任务包'
                    : '该文献已在研究库中（幂等，未重复导入）',
        { label: '进入研究视图', to: { path: '/research', query: { q: props.id } } })
    }
    await loadWork()
  } catch (e) {
    message.error(stageErrorText(e))
  } finally {
    stageLoading.value = false
  }
}

async function confirmQuarantine() {
  if (quarantineLoading.value) return
  quarantineLoading.value = true
  try {
    await quarantineWork(props.id, quarantineReason.value)
    showQuarantineModal.value = false
    await loadWork()
    await loadList()
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
      const result = await restoreWork(props.id)
      await loadWork()
      await loadList()
      message.success('已恢复')
      if (result.read_status_basis === 'legacy_default_unread') message.warning('历史隔离未保存原阅读状态，本次按未读恢复')
    },
  })
}

// Load list once, then load detail on id change
// PLATFORM-003: 全批次研究谱系（无需 batch），加载失败不阻塞页面
const researchProfile = ref(null)
const profileLoading = ref(false)
const profileError = ref(false)
async function loadResearchProfile() {
  profileLoading.value = true
  profileError.value = false
  researchProfile.value = null
  try {
    researchProfile.value = await getResearchWorkProfile(props.id)
  } catch (error) {
    if (error?.status !== 404) profileError.value = true
  } finally {
    profileLoading.value = false
  }
}
const profileBaselines = computed(() => researchProfile.value?.recommended_baselines || [])
const profileTaskStatus = computed(() =>
  researchProfile.value?.metadata?.queue_task?.status || null)

onMounted(() => {
  stageBatchChoice.value = researchBatchId.value || null
  loadStageBatches()
  loadList()
  loadResearchProfile()
})
watch(() => [props.id, researchBatchId.value], loadWork, { immediate: true })
</script>

<style scoped>
.work-layout {
  display: grid; height: calc(100vh - 60px); overflow: hidden;
}

 .mobile-list-link { display: none; }
/* List panel */
.list-panel {
  display: flex; flex-direction: column; overflow: hidden; background: var(--bg-surface);
  border-right: 1px solid var(--border); min-width: 0; min-height: 0;
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
  padding: 8px 12px; border-bottom: 1px solid var(--border); cursor: pointer;
}
.list-item:hover { background: var(--selected-bg); }
.list-item.selected { background: var(--accent-subtle); border-left: 3px solid var(--accent); }
.list-item.quarantined { opacity: 0.5; }
.list-item-title { font-size: 13px; font-weight: 600; line-height: 1.4; }
.list-item-meta { display: flex; gap: 6px; align-items: center; font-size: 11px; margin-top: 2px; color: var(--text-secondary); }
.type-chip { background: var(--accent-subtle); color: var(--accent); padding: 0 5px; border-radius: 3px; font-size: 10px; }
.priority-chip { padding: 0 5px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.priority-chip.P0 { background: var(--bad-bg); color: var(--bad-fg); }
.priority-chip.P1 { background: var(--warn-bg); color: var(--warn-fg); }
.priority-chip.P2 { background: var(--info-bg); color: var(--info-fg); }
.priority-chip.P3 { background: var(--bg-muted); color: var(--text-secondary); }
.priority-chip.archive { background: var(--bg-page); color: var(--text-tertiary); }

.list-empty { padding: 20px; text-align: center; color: var(--text-secondary); font-size: 13px; }
.list-collapse-bar {
  height: 24px; display: flex; align-items: center; justify-content: center;
  border-top: 1px solid var(--border); cursor: pointer; font-size: 12px; color: var(--text-secondary);
  background: var(--bg-page); flex-shrink: 0;
}
.list-collapse-bar:hover { background: var(--bg-muted); color: var(--accent); }

/* Detail panel */
.detail-panel {
  overflow-y: auto; padding: 16px 24px; min-width: 0; min-height: 0;
}
.empty-panel { display: flex; align-items: center; justify-content: center; }

.detail-header {
  display: flex; flex-direction: column; align-items: stretch; gap: 8px; margin-bottom: 12px;
}
.detail-header-left { min-width: 0; width: 100%; }
.detail-header-right { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; min-width: 0; }
.detail-header-right label { display: inline-flex; gap: 4px; align-items: center; font-size: 12px; }
.pdf-ext-link { font-size: 11px; color: var(--accent); text-decoration: none; }
.pdf-ext-link:hover { text-decoration: underline; }

h1 { font-size: 20px; margin: 0 0 4px; outline: none; line-height: 1.3; }
h1[contenteditable] { border-bottom: 2px solid var(--accent); padding-bottom: 2px; }

.muted { color: var(--text-secondary); }
.tiny { font-size: 12px; }
.section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
.section h3 { font-size: 13px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 8px; }
.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.section-header h3 { margin-bottom: 0; }

.kv { display: grid; grid-template-columns: 100px 1fr; gap: 6px 8px; font-size: 13px; }
.kv div:nth-child(odd) { color: var(--text-secondary); }

.abstract-text { font-size: 13px; line-height: 1.6; color: var(--text-primary); margin: 0; }
.research-section-header { justify-content: space-between; }
.research-unavailable, .research-empty { padding: 12px; color: var(--text-secondary); border: 1px dashed var(--border-strong); border-radius: var(--radius-md); background: var(--bg-page); font-size: 12px; }
.research-unavailable { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.research-records { display: flex; flex-direction: column; gap: 12px; }
.research-card { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.research-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.research-card-head > div:first-child { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.research-card-head strong { font-size: 14px; }
.research-card-head span { color: var(--text-secondary); font-size: 11px; }
.ontology-review-note { padding: 8px 10px; margin-top: 10px; color: var(--warn-fg); border: 1px solid var(--warn-border); border-radius: var(--radius-md); background: var(--warn-bg); font-size: 11px; }
.research-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 12px; }
.research-summary-grid div { display: flex; min-width: 0; flex-direction: column; gap: 3px; padding: 8px; border-radius: var(--radius-md); background: var(--bg-page); }
.research-summary-grid span, .research-provenance span { color: var(--text-secondary); font-size: 10px; }
.research-summary-grid strong { overflow-wrap: anywhere; font-size: 11px; font-weight: 580; }
.research-layer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 12px; }
.research-layer-card { padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.research-layer-card.missing { border-style: dashed; }
.research-layer-card header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding-bottom: 7px; border-bottom: 1px solid var(--border); }
.research-layer-card header strong { font-size: 11px; }
.research-layer-card header code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.research-layer-card > div { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 8px; }
.research-layer-card span { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; }
.research-layer-card small { color: var(--text-secondary); font-size: 9px; }
.research-adoption-policy { padding: 8px 10px; margin-top: 9px; color: var(--text-secondary); border-left: 3px solid var(--border-strong); background: var(--bg-page); font-size: 10px; }
.research-adoption-policy.warning { color: var(--bad-fg); border-color: var(--bad); background: var(--bad-bg); }
.research-block { margin-top: 12px; }
.research-block h4 { margin-bottom: 5px; color: var(--text-secondary); font-size: 10px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.research-block p { font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
.research-block pre, .original-record pre { max-height: 280px; overflow: auto; padding: 10px; color: var(--text-primary); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); font: 11px/1.55 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
.research-provenance { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 5px 8px; margin-top: 12px; padding: 10px; border-radius: var(--radius-md); background: var(--bg-page); }
.research-provenance code { overflow-wrap: anywhere; font-size: 10px; }
.research-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.original-record { margin-top: 12px; }
.original-record summary { color: var(--accent); cursor: pointer; font-size: 11px; }
.original-record pre { margin-top: 8px; }
@media (max-width: 760px) {
  .work-layout { display: block; height: calc(100dvh - 110px); }
  .work-layout > .list-panel, .work-layout > :deep(.resize-handle) { display: none; }
  .detail-panel { width: 100%; height: 100%; box-sizing: border-box; padding: 12px 8px 88px; }
  .detail-header { flex-direction: column; gap: 10px; }
  .detail-header-right { flex-wrap: wrap; }
  .mobile-list-link { display: inline-block; margin-bottom: 12px; }
  .kv { grid-template-columns: minmax(0, 95px) minmax(0, 1fr); }
  .kv > div { overflow-wrap: anywhere; }

  .research-summary-grid { grid-template-columns: 1fr 1fr; }
  .research-layer-grid { grid-template-columns: 1fr; }
  .research-columns { grid-template-columns: 1fr; }
  .research-card-head { flex-direction: column; }
}

.cls-multi-tags { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.invalid-tags-banner { padding: 6px 10px; margin-bottom: 4px; border-radius: var(--radius-lg); background: var(--warn-bg); color: var(--warn-fg); font-size: 12px; }
.cls-tag-row { display: flex; align-items: center; gap: 8px; }
.cls-tag-label { font-size: 12px; color: var(--text-secondary); min-width: 60px; flex-shrink: 0; }
.cls-tag-chips { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.date-edit-row { display: flex; gap: 6px; align-items: center; }
.tag-with-conf { display: inline-flex; align-items: center; gap: 2px; }
.conf-badge { padding: 0 5px; border-radius: 999px; font-size: 10px; font-weight: 600; }
.conf-badge.high { background: var(--ok-bg); color: var(--ok-fg); }
.conf-badge.medium { background: var(--warn-bg); color: var(--warn-fg); }
.conf-badge.low { background: var(--bad-bg); color: var(--bad-fg); }
.cls-evidence { margin-top: 8px; }
.cls-evidence-header { display: flex; align-items: center; justify-content: space-between; cursor: pointer; font-size: 12px; color: var(--text-secondary); padding: 4px 0; }
.cls-evidence-toggle { color: var(--accent); font-size: 11px; }
.cls-evidence-body { margin-top: 4px; }
.cls-evidence-item { display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
.cls-evidence-key { color: var(--text-secondary); min-width: 120px; flex-shrink: 0; }
.cls-evidence-val { color: var(--text-primary); }

.file-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--border); }
.file-item.archived { opacity: 0.6; }
.file-name { font-weight: 600; font-size: 13px; }
.rel-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.add-rel { display: flex; gap: 8px; align-items: center; }
.content-preview { font-size: 12px; font-family: Consolas, monospace; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 12px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

/* --- 内容预览 markdown 渲染样式 --- */
.content-markdown {
  font-size: 13px; line-height: 1.7; color: var(--text-primary);
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 16px 20px;
  max-height: 560px; overflow: auto; word-break: break-word;
}
.content-markdown .md-h { margin: 14px 0 8px; font-weight: 600; line-height: 1.4; }
.content-markdown .md-h:first-child { margin-top: 0; }
.content-markdown .md-h1 { font-size: 20px; }
.content-markdown .md-h2 { font-size: 17px; }
.content-markdown .md-h3 { font-size: 15px; }
.content-markdown .md-h4, .content-markdown .md-h5, .content-markdown .md-h6 { font-size: 14px; }
.content-markdown .md-p { margin: 8px 0; }
.content-markdown .md-img { max-width: 100%; height: auto; display: block; margin: 10px auto; border: 1px solid var(--border); border-radius: var(--radius-sm, 6px); background: #fff; }
.content-markdown .md-code { background: var(--bg-page, #f6f6f8); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; overflow: auto; font-size: 12px; font-family: Consolas, monospace; margin: 10px 0; }
.content-markdown .md-code-inline { background: var(--bg-page, #f6f6f8); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; font-size: 12px; font-family: Consolas, monospace; }
.content-markdown .md-quote { margin: 10px 0; padding: 6px 14px; border-left: 3px solid var(--border); color: var(--text-secondary); }
.content-markdown .md-list { margin: 8px 0; padding-left: 24px; }
.content-markdown .md-list li { margin: 4px 0; }
.content-markdown .md-hr { border: none; border-top: 1px solid var(--border); margin: 14px 0; }
/* 宽表格在容器内横向滚动（rowspan/colspan 结构保留），不撑破页面。
   注意：管道表格与解析产物中的 HTML 表格统一只按包装容器选择器着样式。 */
.content-markdown .md-table-wrap { overflow-x: auto; max-width: 100%; margin: 10px 0; scrollbar-width: thin; }
.content-markdown .md-table-wrap table { border-collapse: collapse; font-size: 12px; min-width: 40%; }
.content-markdown .md-table-wrap th, .content-markdown .md-table-wrap td { border: 1px solid var(--border); padding: 5px 10px; text-align: left; vertical-align: top; }
.content-markdown .md-table-wrap th { background: var(--bg-page, #f6f6f8); font-weight: 600; }
/* 数学公式：块级可横向滚动；异常公式降级源码可见 */
.content-markdown .md-math-block { display: block; overflow-x: auto; padding: 4px 0; }
.content-markdown .md-math-inline { display: inline-block; max-width: 100%; overflow-x: auto; vertical-align: middle; }
.content-markdown .md-math .katex-display { margin: 6px 0; }
.content-markdown .md-math .katex { font-size: 1.05em; }
.content-markdown .md-math-fallback { color: var(--warn-fg); font-family: Consolas, monospace; }
.content-mode-note { margin: 6px 0 10px; padding: 8px 12px; border: 1px solid var(--info-border); border-radius: 6px; background: var(--info-bg); color: var(--info-fg); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }

.contrib-legend { display: inline-flex; gap: 3px; margin-left: 6px; opacity: 0.6; vertical-align: middle; }
.status-succeeded { color: var(--ok); font-weight: 600; }
.status-failed { color: var(--bad); font-weight: 600; }
.status-verified { color: var(--ok); }
.status-needs_review { color: var(--warn); }
.status-quarantined { color: var(--bad); font-weight: 600; }
.priority-P0 { color: var(--bad-fg); font-weight: 600; }
.priority-P1 { color: var(--warn-fg); font-weight: 600; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: var(--bg-surface); border-radius: var(--radius-lg); padding: 24px; width: 420px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; }
.modal-desc { margin: 0 0 16px; font-size: 13px; color: var(--text-secondary); }
.modal-reasons { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.reason-option { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; padding: 6px 8px; border-radius: var(--radius-lg); }
.reason-option:hover { background: var(--bg-muted); }
.reason-option input { margin-top: 2px; }
.modal-reason label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

/* Workflow bar */
.workflow-bar {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  background: var(--bg-page); border: 1px solid var(--border); border-radius: var(--radius-lg);
  margin-bottom: 16px; flex-wrap: wrap;
}
.workflow-step {
  display: flex; align-items: center; gap: 6px; padding: 6px 10px;
  border-radius: var(--radius-lg); font-size: 12px; background: var(--bg-surface);
  border: 1px solid var(--border); min-width: 80px;
}
.workflow-step.completed {
  background: var(--ok-bg); border-color: var(--ok); color: var(--ok-fg);
}
.workflow-step.in-progress {
  background: var(--info-bg); border-color: var(--accent-mute); color: var(--info-fg);
}
.workflow-step.pending {
  background: var(--bg-page); border-color: var(--border); color: var(--text-secondary);
}
.step-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%; font-size: 10px;
  font-weight: 600; background: var(--border); color: var(--text-primary);
}
.workflow-step.completed .step-icon { background: #22c55e; color: #fff; }
.workflow-step.in-progress .step-icon { background: #3b82f6; color: #fff; }
.step-label { font-weight: 600; }
.step-status { color: var(--text-secondary); font-size: 11px; }
.step-link { font-size: 11px; color: var(--accent); text-decoration: none; }
.step-link:hover { text-decoration: underline; }
.workflow-arrow { color: var(--text-secondary); font-size: 14px; }
</style>
