<template>
  <div class="readable-record">
    <ResearchAgentPrompt id="record-agent-prompt" :record="record" />
    <div class="translation-notice" :class="{ missing: !translation }">
      <strong>{{ translation ? '中文展示层（仅供阅读）' : '当前版本暂无绑定的中文展示层' }}</strong>
      <span v-if="translation">
        {{ artifact.artifact_version }} 只翻译描述性内容，并绑定当前 source_record、interpretation 与 snapshot 版本；不会改写已审 payload、claim、审核状态或人工采纳状态。
      </span>
      <span v-else>以下按字段显示已审原始内容；为避免误配，系统不会把其他记录版本的译文套到当前记录。</span>
    </div>
    <div class="record-state">
      <span :class="stateClass(record?.source_record?.content_state)">原文记录 {{ stateLabel(record?.source_record) }}</span>
      <span :class="stateClass(record?.interpretation?.content_state)">解释与分类 {{ stateLabel(record?.interpretation) }}</span>
      <span v-if="record?.source_record?.schema_version" class="state-schema">绑定定义：{{ record.source_record.schema_version }}</span>
    </div>
    <div v-if="activeDraft" class="draft-notice">
      <strong>当前显示包含可编辑工作稿 · {{ activeDraft.review_status === 'pending' ? '待 Agent 核查' : '仅措辞工作稿' }}</strong>
      <span>{{ activeDraft.review_notice }} 原记录审核状态与人工采纳状态没有被改写。</span>
      <span v-if="activeDraft.proposed_ontology_keys?.length">拟议分类标签：{{ activeDraft.proposed_ontology_keys.join('、') }}；它们不属于当前记录绑定的已发布词表版本。</span>
    </div>
    <div v-if="draftResponse?.binding_status === 'stale'" class="draft-notice"><strong>旧工作稿未自动套用</strong><span>底层原文记录或解释记录版本已变化；旧稿保留在历史中，需重新核对后再处理。</span></div>
    <button class="draft-shortcut" type="button" @click="scrollToEditor">对显示内容提建议修改 →</button>

    <!-- 原文记录在前（工单工作包 A）：研究单元、定义、条件、方法、主张、结果与局限 -->
    <section id="record-source" class="readable-layer">
      <div class="layer-title">
        <div><span>SOURCE RECORD</span><h3>原文记录</h3><p class="layer-sub">作者实际说了什么：单元、定义、条件、方法、主张、结果与局限（区别于下方“解释与分类”）。</p></div>
        <code>{{ record?.source_record?.id || '尚未生成' }}</code>
      </div>
      <div v-if="unitEntries.length" class="field-group">
        <h4>研究单元（定义 / 条件 / 方法 / 主张 / 结果 / 局限）</h4>
        <article v-for="unit in unitEntries" :key="unit.key" class="unit-card">
          <header>
            <strong>{{ unit.key }}</strong>
            <span v-if="unit.hasEvidence" class="unit-evidence-link">
              <button type="button" class="mini-link" @click="openUnitEvidence(unit)">查看证据 →</button>
            </span>
            <span v-else-if="!linkedClaims('source', unit.raw).length" class="unit-no-evidence">未建立证据锚点关联（不凭文本相似度冒充）</span>
            <button v-for="claim in linkedClaims('source', unit.raw)" :key="claim.key" type="button" class="mini-link" @click="openClaimEvidence('source', claim)">证据：{{ claim.key }}</button>
          </header>
          <dl>
            <template v-for="field in unit.fields" :key="field.key">
              <dt>{{ field.label }}<code>{{ field.key }}</code><button type="button" class="mini-link" @click="requestFieldFeedback('source_record', 'units[' + unit.key + '].' + field.key, '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('source_record', 'units[' + unit.key + '].' + field.key, '提出质疑')">提出质疑</button></dt>
              <dd>
                <ul v-if="asItems(field.value)"><li v-for="(item, index) in asItems(field.value)" :key="index">{{ displayItem(item) }}</li></ul>
                <p v-else>{{ displayScalar(field.value, field.key, 'source') }}</p><button v-for="claim in linkedClaims('source', field.value)" :key="claim.key" type="button" class="mini-link" @click="openClaimEvidence('source', claim)">证据：{{ claim.key }}</button>
              </dd>
            </template>
          </dl>
        </article>
        <div v-if="sharedItems.length" class="unit-extra">
          <h4>单元共享信息<code>shared_items</code></h4>
          <ul><li v-for="(item, index) in sharedItems" :key="index">{{ displayItem(item) }}</li></ul>
        </div>
      </div>
      <div v-else class="field-group">
        <h4>研究单元</h4>
        <p class="empty-value">该记录未携带 v5 units 结构。</p>
      </div>
      <div class="field-group">
        <h4>当前覆盖与剩余缺口</h4>
        <p class="coverage-line">{{ coverageNowLine }}</p>
        <ul v-if="unitGaps.length" class="gap-list">
          <li v-for="gap in unitGaps" :key="gap.key || gap.detail">
            <strong>{{ GAP_KEY_LABELS[gap.key] || gap.key || '缺口' }}</strong>
            <span class="gap-status" :class="{ open: gap.status === 'open' }">{{ gapStatusLabel(gap.status) }}</span>
            <p>{{ displayItem(gap.detail) }}</p>
          </li>
        </ul>
        <p v-else class="empty-value">该记录未披露额外缺口。</p>
        <p class="gap-note">缺口按其登记状态如实显示；是否阻塞稳定由记录的 content_state 与审查门判断，不在此统一断言。</p>
      </div>
      <div v-for="group in sourceGroups" :key="group.title" class="field-group">
        <h4>{{ group.title }}</h4>
        <dl>
          <template v-for="field in group.fields" :key="field.key">
            <dt>{{ field.label }}<code>{{ field.key }}</code><button type="button" class="mini-link" @click="requestFieldFeedback('source_record', field.key, '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('source_record', field.key, '提出质疑')">提出质疑</button></dt>
            <dd>
              <template v-if="field.key === 'coverage'">
                <p>{{ coverageStatus }}</p>
                <ul v-if="coverageItems.length"><li v-for="(item, index) in coverageItems" :key="index">{{ item }}</li></ul>
                <p v-else class="empty-value">暂无覆盖明细</p>
              </template>
              <ul v-else-if="asItems(sourceValue(field.key))">
                <li v-for="(item, index) in asItems(sourceValue(field.key))" :key="index">{{ displayItem(item) }}</li>
              </ul>
              <p v-else>{{ displayScalar(sourceValue(field.key), field.key, 'source') }}</p><button v-for="claim in linkedClaims('source', sourceValue(field.key))" :key="claim.key" type="button" class="mini-link" @click="openClaimEvidence('source', claim)">证据：{{ claim.key }}</button>
            </dd>
          </template>
        </dl>
      </div>
      <!-- 实质研究扩展保留在研究内容中，用可理解的中文标题 -->
      <div v-if="researchExtensions.source.research.length" class="field-group">
        <h4>研究内容扩展（原文实质信息）</h4>
        <article v-for="(ext, index) in researchExtensions.source.research" :key="index" class="extension-card">
          <header><strong>{{ extensionTitle(ext.name) }}</strong>
            <span v-if="ext.needs_verification" class="ext-verify">待核查</span>
            <code v-if="ext.name" class="ext-name">{{ ext.name }}</code></header>
          <p v-if="ext.scope">范围：{{ displayItem(ext.scope) }}</p>
          <pre class="ext-content">{{ displayItem(ext.content) }}</pre>
        </article>
      </div>
      <details class="maintenance-history">
        <summary>迁移 / 修订历史（{{ researchExtensions.source.maintenance.length }} 项，默认折叠）</summary>
        <p class="maintenance-note">以下为转换账目、版本差异与修订记录，属维护信息；不伪装成当前研究内容或未完成状态。</p>
        <article v-for="(ext, index) in researchExtensions.source.maintenance" :key="index" class="extension-card maintenance">
          <header><strong>{{ extensionTitle(ext.name) }}</strong>
            <span v-if="ext.needs_verification" class="ext-verify">待核查</span>
            <code v-if="ext.name" class="ext-name">{{ ext.name }}</code></header>
          <p v-if="ext.scope">范围：{{ displayItem(ext.scope) }}</p>
          <pre class="ext-content">{{ displayItem(ext.content) }}</pre>
        </article>
        <div class="tech-meta">
          <h5>记录技术信息（保留追溯）</h5>
          <pre>{{ sourceTechMeta }}</pre>
        </div>
      </details>
    </section>

    <!-- 解释与分类在后 -->
    <section id="record-interpretation" class="readable-layer">
      <div class="layer-title">
        <div><span>INTERPRETATION</span><h3>解释与分类</h3><p class="layer-sub">判断、理由、边界与分类坐标；可回查上方原文记录与证据，不等同原文全部。</p></div>
        <code>{{ record?.interpretation?.id || '尚未生成' }}</code>
      </div>
      <div class="field-group core-claim">
        <h4>核心命题与边界</h4>
        <dl>
          <dt>命题<code>statement</code><button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'statement', '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'statement', '提出质疑')">提出质疑</button></dt>
          <dd><p>{{ displayScalar(interpretationValue('statement'), 'statement') }}</p></dd>
          <dt>范围<code>scope</code><button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'scope', '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'scope', '提出质疑')">提出质疑</button></dt>
          <dd>
            <template v-if="scopeEntries">
              <div v-for="entry in scopeEntries" :key="entry.key" class="scope-row">
                <code>{{ entry.key }}</code>
                <ul><li v-for="(item, index) in entry.values" :key="index">{{ displayItem(item) }}</li></ul>
              </div>
            </template>
            <ul v-else-if="asItems(interpretationValue('scope'))">
              <li v-for="(item, index) in asItems(interpretationValue('scope'))" :key="index">{{ displayItem(item) }}</li>
            </ul>
            <p v-else class="empty-value">未声明范围</p>
          </dd>
          <dt>支撑边界<code>support_boundary</code><button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'support_boundary', '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', 'support_boundary', '提出质疑')">提出质疑</button></dt>
          <dd><p>{{ displayScalar(interpretationValue('support_boundary'), 'support_boundary') }}</p></dd>
        </dl>
      </div>
      <div class="ontology-mapping">
        <div class="mapping-heading">
          <div><h4>本体映射（受控词表）</h4><p>与下方“风险现象（自由叙述）”分开保存和展示。</p></div>
          <router-link to="/research/ontology">查看完整词表 →</router-link>
        </div>
        <div v-if="ontologyMappings.length" class="mapping-list">
          <article v-for="item in ontologyMappings" :key="item.id">
            <strong>{{ item.zh }}</strong><code>{{ item.id }}</code>
            <span>{{ item.nature }}</span><span>词表版本：{{ item.version }}</span>
          </article>
        </div>
        <p v-else class="empty-value">未映射</p>
        <div v-if="isPartialMapping" class="mapping-gap">
          <strong>部分映射的具体缺口</strong>
          <ul v-if="mappingIssues.length"><li v-for="(issue, index) in mappingIssues" :key="index">{{ displayItem(issue) }}</li></ul>
          <p v-else>未说明</p>
        </div>
      </div>
      <div v-for="group in interpretationGroups" :key="group.title" class="field-group">
        <h4>{{ group.title }}</h4>
        <dl>
          <template v-for="field in group.fields" :key="field.key">
            <dt>{{ field.label }}<code>{{ field.key }}</code><button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', field.key, '建议修改')">建议修改</button> <button type="button" class="mini-link" @click="requestFieldFeedback('interpretation', field.key, '提出质疑')">提出质疑</button></dt>
            <dd>
              <ul v-if="asItems(interpretationValue(field.key))">
                <li v-for="(item, index) in asItems(interpretationValue(field.key))" :key="index">{{ displayItem(item) }}</li>
              </ul>
              <p v-else>{{ displayScalar(interpretationValue(field.key), field.key) }}</p><button v-for="claim in linkedClaims('interpretation', interpretationValue(field.key))" :key="claim.key" type="button" class="mini-link" @click="openClaimEvidence('interpretation', claim)">证据：{{ claim.key }}</button>
            </dd>
          </template>
        </dl>
      </div>
      <div class="field-group">
        <h4>关联声明（受控词表 v5）</h4>
        <article v-for="(assoc, index) in associations" :key="index" class="association-card">
          <header>
            <span class="assoc-mapping">{{ enumLabel('mapping_status', assoc.mapping_status) }}</span>
            <code v-if="assoc.concept_id">{{ assoc.concept_id }}</code>
          </header>
          <dl>
            <dt>适用范围<code>scope_refs</code></dt>
            <dd>
              <ul v-if="asItems(assoc.scope_refs)"><li v-for="ref in assoc.scope_refs" :key="ref">{{ ref }}</li></ul>
              <p v-else class="empty-value">未说明</p>
            </dd>
            <dt>研究方面<code>research_aspects</code></dt>
            <dd><p>{{ labeledList('research_aspects', assoc.research_aspects) }}</p></dd>
            <dt>研究作用<code>research_roles</code></dt>
            <dd><p>{{ labeledList('research_roles', assoc.research_roles) }}</p></dd>
            <template v-if="assoc.update_intervention">
              <dt>干预粒度<code>update_intervention.kind</code></dt>
              <dd><p>{{ enumLabel('update_intervention_kind', assoc.update_intervention?.kind) }}<span v-if="assoc.update_intervention?.note">（{{ assoc.update_intervention.note }}）</span></p></dd>
            </template>
            <template v-if="asItems(assoc.positions)">
              <dt>位置与关系<code>positions</code></dt>
              <dd>
                <ul><li v-for="(pos, pIndex) in assoc.positions" :key="pIndex">{{ positionLabel(pos) }}<span v-if="asItems(pos?.scope_refs)">（范围：{{ pos.scope_refs.join('、') }}）</span></li></ul>
              </dd>
            </template>
            <template v-if="asItems(assoc.candidates)">
              <dt>歧义候选（未定，不作为已定映射）<code>candidates</code></dt>
              <dd><ul><li v-for="(cand, cIndex) in assoc.candidates" :key="cIndex">{{ displayItem(cand) }}</li></ul></dd>
            </template>
            <template v-if="assoc.reason">
              <dt>理由<code>reason</code></dt>
              <dd><p>{{ assoc.reason }}</p></dd>
            </template>
          </dl>
        </article>
        <p v-if="!associations.length" class="empty-value">该记录未携带结构化关联声明（旧版本记录按其根级字段显示）</p>
      </div>
      <div v-if="researchExtensions.interpretation.research.length" class="field-group">
        <h4>研究内容扩展（解释实质信息）</h4>
        <article v-for="(ext, index) in researchExtensions.interpretation.research" :key="index" class="extension-card">
          <header><strong>{{ extensionTitle(ext.name) }}</strong>
            <span v-if="ext.needs_verification" class="ext-verify">待核查</span>
            <code v-if="ext.name" class="ext-name">{{ ext.name }}</code></header>
          <p v-if="ext.scope">范围：{{ displayItem(ext.scope) }}</p>
          <pre class="ext-content">{{ displayItem(ext.content) }}</pre>
        </article>
      </div>
      <details class="maintenance-history">
        <summary>迁移 / 修订历史（{{ researchExtensions.interpretation.maintenance.length }} 项，默认折叠）</summary>
        <p class="maintenance-note">以下为转换账目与修订记录；旧规则不伪装成当前尚未完成的状态。</p>
        <article v-for="(ext, index) in researchExtensions.interpretation.maintenance" :key="index" class="extension-card maintenance">
          <header><strong>{{ extensionTitle(ext.name) }}</strong>
            <span v-if="ext.needs_verification" class="ext-verify">待核查</span>
            <code v-if="ext.name" class="ext-name">{{ ext.name }}</code></header>
          <p v-if="ext.scope">范围：{{ displayItem(ext.scope) }}</p>
          <pre class="ext-content">{{ displayItem(ext.content) }}</pre>
        </article>
        <div class="tech-meta">
          <h5>记录技术信息（保留追溯）</h5>
          <pre>{{ interpretationTechMeta }}</pre>
        </div>
      </details>
      <details v-if="otherExtensionsPresent" class="maintenance-history unknown-ext">
        <summary>其他具名扩展（未识别，{{ otherExtensionsCount }} 项；兜底展示不丢弃）</summary>
        <article v-for="(ext, index) in otherExtensions" :key="index" class="extension-card">
          <header><strong>{{ ext.name || '未命名扩展' }}</strong>
            <span v-if="ext.needs_verification" class="ext-verify">待核查</span>
            <code v-if="ext.source">{{ ext.source }}</code></header>
          <p v-if="ext.scope">范围：{{ displayItem(ext.scope) }}</p>
          <pre class="ext-content">{{ displayItem(ext.content) }}</pre>
        </article>
      </details>
    </section>

    <section id="research-draft-editor" class="readable-layer editing-layer">
      <div class="layer-title">
        <div><span>EDITABLE OVERLAY</span><h3>建议修改（中文工作稿）</h3></div>
        <code>{{ draftResponse?.revision ? `自动历史 r${draftResponse.revision}` : '尚未保存工作稿' }}</code>
      </div>
      <p class="draft-intro">这里是“建议修改”的交互入口：改动保存为独立展示稿并记入历史，不直接替代正式结论；要推动正式修订请使用下方“质疑与建议修改”登记反馈。既有工作稿、版本绑定与历史数据保留。</p>
      <div class="edit-toolbar">
        <div><strong>保留已审原记录</strong><span>取消不会写入；撤回会恢复上次保存前内容，但保留审计历史。</span></div>
        <button type="button" @click="openEditor">{{ editorOpen ? '重新载入' : '编辑工作稿' }}</button>
        <button type="button" :disabled="!activeDraft || editBusy" @click="undoDraft">撤回上次修改</button>
      </div>
      <p v-if="draftLoadError" class="edit-error">{{ draftLoadError }}</p>
      <p v-if="editMessage" class="edit-message">{{ editMessage }}</p>
      <details v-if="draftResponse?.history?.length" class="draft-history"><summary>查看工作稿历史（{{ draftResponse.history.length }}）</summary><ul><li v-for="event in draftResponse.history" :key="`${event.revision}-${event.action}`"><span>{{ event.action === 'undo' ? '撤回' : '保存' }}</span><code>r{{ event.revision }} · {{ event.at }}</code></li></ul></details>
      <form v-if="editorOpen" class="draft-form" @submit.prevent="saveDraft">
        <label class="change-kind"><span>修改性质</span><select v-model="draftForm.change_kind"><option value="wording">措辞调整（展示层）</option><option value="substantive">事实／结论／分类改动（保存后待核查，不因此成为已审结论）</option></select></label>
        <details v-for="group in editableGroups" :key="group.layer" open>
          <summary>{{ group.label }}</summary>
          <label v-for="field in group.fields" :key="field.key">
            <span>{{ field.label }}</span>
            <textarea v-model="draftForm.display[group.layer][field.key]" rows="3"></textarea>
          </label>
        </details>
        <fieldset>
          <legend>分类标签（受控词表）</legend>
          <label v-for="concept in ontologyDraft.concepts" :key="concept.id" class="concept-choice">
            <input v-model="draftForm.ontology_keys" type="checkbox" :value="concept.id" />
            <span>{{ concept.zh }}<small>{{ concept.id }}</small></span>
          </label>
        </fieldset>
        <label><span>工作稿备注</span><textarea v-model="draftForm.notes" rows="2"></textarea></label>
        <div class="review-request-builder">
          <strong>请 Agent 核查（只保存为待办，不会自动触发 Agent）</strong>
          <div><select v-model="requestField"><option value="">选择字段</option><option v-for="item in reviewFieldOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select><input v-model="requestText" placeholder="用一句话说明要核查什么" /><button type="button" @click="addReviewRequest">加入待办</button></div>
          <ul v-if="Object.keys(draftForm.review_requests).length"><li v-for="(text, field) in draftForm.review_requests" :key="field"><code>{{ field }}</code><span>{{ text }}</span><button type="button" @click="removeReviewRequest(field)">移除</button></li></ul>
        </div>
        <div class="form-actions"><button type="submit" :disabled="editBusy">保存工作稿</button><button type="button" @click="cancelEdit">取消</button></div>
        <p class="evidence-lock">精确 quote 与 offset 不开放直接改字；如证据定位有误，应通过反馈或解析纠错流程重新定位并生成新的正式记录。</p>
      </form>
    </section>

    <section id="record-evidence" class="readable-layer evidence-layer">
      <div class="layer-title"><div><span>EVIDENCE</span><h3>逐条证据</h3><p class="layer-sub">每条判断的固定快照锚点；点“查看证据”在侧栏回查上下文与引文高亮。</p></div></div>
      <div v-for="layer in claimLayers" :key="layer.key" class="claim-group">
        <h4>{{ layer.label }}</h4>
        <article v-for="claim in layer.claims" :key="claim.key" class="claim-card">
          <header>
            <strong>{{ claimText(layer.key, claim) }}</strong><code>{{ claim.key || '无 claim key' }}</code>
            <button v-if="claim.evidence?.length" type="button" class="mini-link" @click="openClaimEvidence(layer.key, claim)" data-testid="view-evidence">
              查看证据（{{ claim.evidence.length }} 条）→
            </button>
          </header>
          <div v-if="claim.evidence?.length" class="evidence-list">
            <div v-for="(evidence, index) in claim.evidence" :key="index" class="evidence-item">
              <small>原文引文（保持原样，不翻译）</small>
              <template v-if="previewFor(layerRecordId(layer.key), claim.key, evidence)">
                <div class="evidence-preview">
                  <code class="preview-context">{{ previewFor(layerRecordId(layer.key), claim.key, evidence)?.context_before
                    || '⟨文首⟩' }}</code>
                  <mark>{{ evidence.quote }}</mark>
                  <code class="preview-context">{{ previewFor(layerRecordId(layer.key), claim.key, evidence)?.context_after
                    || '⟨文末⟩' }}</code>
                </div>
                <small v-if="previewFor(layerRecordId(layer.key), claim.key, evidence)?.quote_occurrence"
                  class="preview-occurrence">
                  重复文本定位：第 {{ previewFor(layerRecordId(layer.key), claim.key, evidence)?.quote_occurrence.index }}
                  / 共 {{ previewFor(layerRecordId(layer.key), claim.key, evidence)?.quote_occurrence.total }} 处
                  · 快照 v{{ previewFor(layerRecordId(layer.key), claim.key, evidence)?.snapshot_version }}
                </small>
              </template>
              <blockquote v-else>{{ evidence.quote || '未提供 quote' }}</blockquote>
              <div class="anchor-meta">
                <code v-if="evidence.start_offset !== undefined">offset {{ evidence.start_offset }}–{{ evidence.end_offset ?? (evidence.start_offset + String(evidence.quote || '').length) }}</code>
                <template v-if="evidence.locator && Object.keys(evidence.locator).length">
                  <small>回查定位（{{ locatorKindLabel(evidence.locator.kind) }}）</small>
                  <code v-for="(value, key) in evidence.locator" :key="key">{{ key }}={{ displayItem(value) }}</code>
                </template>
              </div>
              <small v-if="evidence.locator?.kind === 'figure_region'" class="locator-precision-note">
                当前仅提供绑定快照的页码与坐标，未提供区域画面裁切；请在原件中按页核对后再作内容判断。
              </small>
              <small v-else-if="['page', 'figure_region'].includes(evidence.locator?.kind)
                && previewFor(layerRecordId(layer.key), claim.key, evidence)?.locator_verification?.page_text_correspondence !== 'exact'"
                class="locator-precision-note">
                页数已核对，但解析未提供 page_offsets，当前页码与引文文本位置尚未精确对应。
              </small>
            </div>
          </div>
          <p v-else class="empty-value">暂无证据锚点</p>
        </article>
        <p v-if="!layer.claims.length" class="empty-value">暂无 claim</p>
      </div>
    </section>

    <section id="record-feedback" class="readable-layer feedback-layer">
      <FeedbackPanel ref="feedbackPanel" :record="record" />
    </section>

    <details class="audit-record">
      <summary>审计：查看未改写的原始记录 JSON</summary>
      <pre>{{ originalJson }}</pre>
    </details>

    <EvidenceSidebar :open="sidebar.open" :payload="sidebar.payload" @close="sidebar.open = false" @state-change="$emit('evidence-state', $event)" />
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import ResearchAgentPrompt from './ResearchAgentPrompt.vue'
import FeedbackPanel from './FeedbackPanel.vue'
import EvidenceSidebar from './EvidenceSidebar.vue'
import {
  DISPLAY_ARTIFACT,
  boundDisplayTranslation,
  enumLabel,
  rawResearchValue,
  translatedClaim,
  translatedField,
  researchWorkId,
} from '../../researchPresentation'
import { ontologyConceptDisplay, ontologyDraft } from '../../data/research-ontology-draft'
import { getResearchDraft, saveResearchDraft, undoResearchDraft, getResearchEvidence } from '../../api'

const props = defineProps({ record: { type: Object, required: true } })
defineEmits(['evidence-state'])
const artifact = DISPLAY_ARTIFACT
const translation = computed(() => boundDisplayTranslation(props.record))
const feedbackPanel = ref(null)
function linkedClaims(layer, value) {
  const claims = props.record?.[layer === 'source' ? 'source_record' : 'interpretation']?.claims || []
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? '')
  // Exact declared claim keys only; no title similarity or inference.
  const keys = new Set(text.match(/[A-Za-z][A-Za-z0-9_-]+/g) || [])
  return claims.filter(claim => keys.has(claim.key) && claim.evidence?.length)
}
function requestFieldFeedback(layer, field, action) {
  feedbackPanel.value?.selectTarget(layer, field, action)
  document.getElementById('record-feedback')?.scrollIntoView({ behavior: 'smooth' })
}


// ============ 具名扩展的三分展示（工单工作包 A） ============
// research：实质研究内容（如作者对既有文献的重读）——保留在研究内容区，中文标题；
// maintenance：legacy 转换账目、版本差异、修订记录、旧待查清单——默认折叠；
// other：未认识的具名扩展——兜底展示，绝不白名单过滤静默丢弃。
const RESEARCH_EXTENSION_TITLES = {
  'prior-literature-reinterpretations': '作者对既有研究的重读（原文实质内容）',
}
const MAINTENANCE_EXTENSION_TITLES = {
  'legacy-conversion': 'legacy 转换账目（旧结构迁移记录）',
  'v5-completion': 'v5 补全与修订记录（版本差异账目）',
}
const MAINTENANCE_NAME_RE = /^(legacy-|feedback-revision-|v5-completion|conversion|migration|revision-|checklist|deprecated)/

function extensionKind(name) {
  if (name && Object.prototype.hasOwnProperty.call(RESEARCH_EXTENSION_TITLES, name)) return 'research'
  if (name && (Object.prototype.hasOwnProperty.call(MAINTENANCE_EXTENSION_TITLES, name) || MAINTENANCE_NAME_RE.test(name))) return 'maintenance'
  return 'other'
}
function extensionTitle(name) {
  return RESEARCH_EXTENSION_TITLES[name] || MAINTENANCE_EXTENSION_TITLES[name] || name || '未命名扩展'
}

function splitExtensions(list) {
  const source = Array.isArray(list) ? list : []
  return {
    research: source.filter(ext => extensionKind(ext?.name) === 'research'),
    maintenance: source.filter(ext => extensionKind(ext?.name) === 'maintenance'),
    other: source.filter(ext => extensionKind(ext?.name) === 'other'),
  }
}

function layerExtensions(payload) {
  const split = splitExtensions(payload?.extensions)
  return { research: split.research, maintenance: split.maintenance }
}
const researchExtensions = computed(() => ({
  source: layerExtensions(props.record?.source_record?.payload),
  interpretation: layerExtensions(props.record?.interpretation?.payload),
}))
const otherExtensions = computed(() => ([
  ...splitExtensions(props.record?.source_record?.payload?.extensions).other.map(ext => ({ ...ext, _layer: 'source_record' })),
  ...splitExtensions(props.record?.interpretation?.payload?.extensions).other.map(ext => ({ ...ext, _layer: 'interpretation' })),
]))
const otherExtensionsPresent = computed(() => otherExtensions.value.length > 0)
const otherExtensionsCount = computed(() => otherExtensions.value.length)

// 当前覆盖：coverage_now 登记在维护扩展里，但“当前覆盖范围”属研究内容，提到前面展示
const coverageNowLine = computed(() => {
  const split = layerExtensions(props.record?.source_record?.payload)
  const all = [...split.maintenance, ...split.research]
  for (const ext of all) {
    const content = ext?.content
    if (content && typeof content === 'object' && !Array.isArray(content) && content.coverage_now) {
      return `已覆盖（登记于修订账目）：${displayItem(content.coverage_now)}`
    }
  }
  return '覆盖范围：该记录未登记 coverage_now；请结合下方缺口与审查状态理解。'
})

const GAP_KEY_LABELS = {
  'figures-not-extracted': '图线数值未提取',
  'instructgpt-attribution-open': 'InstructGPT 案例归属未定',
  'parse-quality-unchecked': '解析质量未检查',
}
function gapStatusLabel(status) {
  return { open: '已披露 · 待处理', resolved: '已解决', accepted: '已知悉并接受', wonthold: '暂缓' }[status] || status || '状态未提供'
}

// 技术元数据（字段名/执行者/范围）折叠保留追溯
const sourceTechMeta = computed(() => JSON.stringify({
  id: props.record?.source_record?.id,
  version: props.record?.source_record?.version,
  schema_version: props.record?.source_record?.schema_version,
  record_mode: props.record?.source_record?.payload?.record_mode,
  submitted_by: props.record?.source_record?.submitted_by,
  scope: props.record?.source_record?.scope || props.record?.source_record?.payload?.scope,
  snapshot_id: props.record?.snapshot?.id,
  release_id: props.record?.source_record?.release_id,
  content_state: props.record?.source_record?.content_state,
  agent_review_status: props.record?.source_record?.agent_review_status,
  human_adoption_status: props.record?.source_record?.human_adoption_status,
}, null, 2))
const interpretationTechMeta = computed(() => JSON.stringify({
  id: props.record?.interpretation?.id,
  version: props.record?.interpretation?.version,
  schema_version: props.record?.interpretation?.schema_version,
  submitted_by: props.record?.interpretation?.submitted_by,
  ontology_version: props.record?.interpretation?.ontology_version,
  scope: props.record?.interpretation?.scope || props.record?.interpretation?.payload?.scope,
  release_id: props.record?.interpretation?.release_id,
  content_state: props.record?.interpretation?.content_state,
  agent_review_status: props.record?.interpretation?.agent_review_status,
  human_adoption_status: props.record?.interpretation?.human_adoption_status,
}, null, 2))

const draftResponse = ref(null)
const activeDraft = computed(() => draftResponse.value?.draft || null)
const editorOpen = ref(false)
const editBusy = ref(false)
const editMessage = ref('')
const draftLoadError = ref('')
const requestField = ref('')
const requestText = ref('')
const draftForm = ref({ change_kind: 'wording', display: { source: {}, interpretation: {} }, ontology_keys: [], notes: '', review_requests: {} })

const interpretationGroups = [
  { title: '研究定位', fields: [
    { key: 'update_object', label: '更新对象' }, { key: 'research_role', label: '研究作用' }, { key: 'mapping_status', label: '映射状态' },
  ] },
  { title: '研究设计与观察', fields: [
    { key: 'intervention', label: '干预' }, { key: 'observation_access', label: '观察访问' }, { key: 'formation_or_manifestation', label: '形成 / 表现' },
  ] },
  { title: '风险链条', fields: [
    { key: 'risk_phenomena', label: '风险现象（自由叙述）' }, { key: 'mechanisms', label: '机制' }, { key: 'consequences', label: '后果' },
  ] },
  { title: '证据边界与判断', fields: [
    { key: 'deployment_condition', label: '部署条件' }, { key: 'reasoning', label: '推理依据' }, { key: 'evidence_strength', label: '证据强度' },
  ] },
  { title: '不确定性', fields: [
    { key: 'assumptions', label: '假设' }, { key: 'competing_explanations', label: '竞争性解释' }, { key: 'classification_issues', label: '分类问题' }, { key: 'unresolved', label: '未决项' },
  ] },
]

const sourceGroups = [
  { title: '材料与覆盖', fields: [{ key: 'material_type', label: '材料类型' }, { key: 'coverage', label: '覆盖范围' }] },
  { title: '研究事实', fields: [{ key: 'conditions', label: '条件' }, { key: 'author_claims', label: '作者主张' }, { key: 'observations', label: '观察结果' }] },
  { title: '限制与未决', fields: [{ key: 'limitations', label: '局限' }, { key: 'unresolved', label: '未决项' }] },
]

const editableGroups = [
  { layer: 'source', label: '原文记录的中文表述（不含精确引文）', fields: [
    { key: 'conditions', label: '条件' }, { key: 'author_claims', label: '作者主张' },
    { key: 'observations', label: '观察结果' }, { key: 'limitations', label: '局限' }, { key: 'unresolved', label: '未决项' },
  ] },
  { layer: 'interpretation', label: '研究解释与备注', fields: [
    { key: 'intervention', label: '干预' }, { key: 'observation_access', label: '观察访问' },
    { key: 'formation_or_manifestation', label: '形成／表现' }, { key: 'risk_phenomena', label: '风险现象' },
    { key: 'mechanisms', label: '机制' }, { key: 'consequences', label: '后果' },
    { key: 'deployment_condition', label: '部署条件' }, { key: 'reasoning', label: '解释／推理依据' },
    { key: 'assumptions', label: '假设' }, { key: 'competing_explanations', label: '竞争性解释' },
    { key: 'evidence_strength', label: '证据强度' }, { key: 'classification_issues', label: '分类问题' },
    { key: 'unresolved', label: '未决项' },
  ] },
]
const reviewFieldOptions = [
  ...editableGroups.flatMap(group => group.fields.map(field => ({ value: `${group.layer}.${field.key}`, label: `${group.label} · ${field.label}` }))),
  { value: 'ontology_keys', label: '分类标签' }, { value: 'notes', label: '工作稿备注' },
]

function overlayValue(layer, key) {
  const values = activeDraft.value?.display?.[layer]
  return values && Object.prototype.hasOwnProperty.call(values, key) ? values[key] : undefined
}

const ontologyVersion = computed(() => props.record?.interpretation?.ontology_version || '未说明')
const effectiveOntologyKeys = computed(() => activeDraft.value?.ontology_keys || props.record?.interpretation?.ontology_keys || [])
const ontologyMappings = computed(() => effectiveOntologyKeys.value.map(key => ontologyConceptDisplay(
  key,
  activeDraft.value?.proposed_ontology_keys?.includes(key) ? `${ontologyDraft.pilotVersion}（拟议）` : ontologyVersion.value,
)))
const mappingStatus = computed(() => rawResearchValue(props.record?.interpretation?.payload?.mapping_status))
const isPartialMapping = computed(() => mappingStatus.value === 'partially_mapped')
const mappingIssues = computed(() => {
  const issues = interpretationValue('classification_issues')
  if (Array.isArray(issues)) return issues.filter(item => item !== undefined && item !== null && item !== '')
  return issues === undefined || issues === null || issues === '' ? [] : [issues]
})

function editableBaseValue(layer, key) {
  const overlay = overlayValue(layer, key)
  return overlay !== undefined ? overlay : translatedField(props.record, layer, key)
}

function valueToText(value) {
  if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : JSON.stringify(item, null, 2)).join('\n')
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  return value === undefined || value === null ? '' : String(value)
}

function textToValue(text, original) {
  if (Array.isArray(original)) return String(text).split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  if (original && typeof original === 'object') {
    try { return JSON.parse(text) } catch { return text }
  }
  return text
}

function resetDraftForm() {
  const display = { source: {}, interpretation: {} }
  for (const group of editableGroups) {
    for (const field of group.fields) display[group.layer][field.key] = valueToText(editableBaseValue(group.layer, field.key))
  }
  draftForm.value = {
    change_kind: activeDraft.value?.change_kind || 'wording',
    display,
    ontology_keys: [...effectiveOntologyKeys.value],
    notes: activeDraft.value?.notes || '',
    review_requests: { ...(activeDraft.value?.review_requests || {}) },
  }
  requestField.value = ''
  requestText.value = ''
}

async function loadDraft() {
  const workId = researchWorkId(props.record)
  const batchId = props.record?.batch_id
  draftResponse.value = null
  draftLoadError.value = ''
  if (!workId || !batchId) return
  try {
    draftResponse.value = await getResearchDraft(workId, batchId)
  } catch (error) {
    draftLoadError.value = error?.status === 409 ? '试点编辑入口尚未启用；当前仍以只读方式显示。' : `无法读取工作稿：${error?.message || '请求失败'}`
  }
}

async function openEditor() {
  if (!draftResponse.value) await loadDraft()
  if (!draftResponse.value) return
  resetDraftForm()
  editorOpen.value = true
  editMessage.value = ''
}

function scrollToEditor() {
  document.getElementById('research-draft-editor')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  openEditor()
}

function cancelEdit() {
  editorOpen.value = false
  resetDraftForm()
  editMessage.value = '已取消：没有写入任何内容。'
}

function addReviewRequest() {
  if (!requestField.value || !requestText.value.trim()) return
  draftForm.value.review_requests[requestField.value] = requestText.value.trim()
  requestField.value = ''
  requestText.value = ''
}

function removeReviewRequest(field) {
  delete draftForm.value.review_requests[field]
}

async function saveDraft() {
  const workId = researchWorkId(props.record)
  const batchId = props.record?.batch_id
  if (!workId || !batchId) return
  editBusy.value = true
  editMessage.value = ''
  try {
    const display = { source: {}, interpretation: {} }
    for (const group of editableGroups) {
      for (const field of group.fields) {
        display[group.layer][field.key] = textToValue(draftForm.value.display[group.layer][field.key], editableBaseValue(group.layer, field.key))
      }
    }
    draftResponse.value = await saveResearchDraft(workId, {
      batch_id: batchId,
      expected_revision: draftResponse.value?.revision || 0,
      change_kind: draftForm.value.change_kind,
      display,
      ontology_keys: draftForm.value.ontology_keys,
      notes: draftForm.value.notes,
      review_requests: draftForm.value.review_requests,
    })
    editorOpen.value = false
    editMessage.value = activeDraft.value?.review_status === 'pending'
      ? '工作稿已保存并记入历史；核查待办已记录，但尚未触发或完成 Agent 核查。正式结论未变。'
      : '措辞工作稿已保存并记入历史。正式结论未变。'
  } catch (error) {
    editMessage.value = `保存失败：${error?.detail || error?.message || '请求失败'}`
  } finally {
    editBusy.value = false
  }
}

async function undoDraft() {
  const workId = researchWorkId(props.record)
  const batchId = props.record?.batch_id
  if (!activeDraft.value || !workId || !batchId) return
  editBusy.value = true
  try {
    draftResponse.value = await undoResearchDraft(workId, batchId, draftResponse.value.revision)
    editorOpen.value = false
    editMessage.value = '已撤回上次保存；审计历史仍然保留。'
  } catch (error) {
    editMessage.value = `撤回失败：${error?.detail || error?.message || '请求失败'}`
  } finally {
    editBusy.value = false
  }
}

watch(() => [props.record?.batch_id, researchWorkId(props.record)], () => {
  editorOpen.value = false
  editMessage.value = ''
  loadDraft()
})

function interpretationValue(key) {
  if (['update_object', 'research_role', 'mapping_status'].includes(key)) {
    return props.record?.interpretation?.payload?.[key]
  }
  const overlay = overlayValue('interpretation', key)
  if (overlay !== undefined) return overlay
  return translatedField(props.record, 'interpretation', key)
}

function sourceValue(key) {
  if (key === 'material_type') return props.record?.source_record?.payload?.[key]
  const overlay = overlayValue('source', key)
  if (overlay !== undefined) return overlay
  return translatedField(props.record, 'source', key)
}

function asItems(value) { return Array.isArray(value) && value.length ? value : null }
// U19(R5/R6)：证据预览逐条键控（claim + 自身 offset/quote），多条证据互不串行
const evidencePreview = ref({})
watch(() => [props.record?.source_record?.id, props.record?.interpretation?.id], async () => {
  const map = {}
  for (const recordId of [props.record?.source_record?.id, props.record?.interpretation?.id]) {
    if (!recordId) continue
    try {
      const response = await getResearchEvidence(recordId)
      const rows = response?.items || response || []
      for (const row of rows) {
        map[`${recordId}::${row.claim_key}::${row.start_offset}::${row.quote}`] = row
      }
    } catch {
      // preview is best-effort; claim cards still render quote/offset
    }
  }
  evidencePreview.value = map
}, { immediate: true })

function previewFor(recordId, claimKey, evidence) {
  const start = evidence?.start_offset
  const quote = evidence?.quote
  if (start !== undefined && quote) {
    return evidencePreview.value[`${recordId}::${claimKey}::${start}::${quote}`] || null
  }
  return null
}

// ===== 证据侧栏（工单工作包 D）：按证据绑定快照回查，多证据可切换 =====
const sidebar = reactive({ open: false, payload: null })
function layerRecordId(layerKey) {
  return layerKey === 'source' ? props.record?.source_record?.id : props.record?.interpretation?.id
}
function enrichEvidence(layerKey, claim, evidenceItem) {
  const preview = previewFor(layerRecordId(layerKey), claim.key, evidenceItem)
  return {
    ...evidenceItem,
    ...(preview || {}),
    source_id: props.record?.source?.id,
  }
}
function openClaimEvidence(layerKey, claim) {
  if (!claim.evidence?.length) return
  sidebar.payload = {
    evidence: enrichEvidence(layerKey, claim, claim.evidence[0]),
    list: claim.evidence.map(ev => enrichEvidence(layerKey, claim, ev)),
    claimText: claimText(layerKey, claim),
  }
  sidebar.open = true
}
function openUnitEvidence(unit) {
  const evidenceList = Array.isArray(unit.raw?.evidence) ? unit.raw.evidence : []
  if (!evidenceList.length) return
  sidebar.payload = {
    evidence: { ...evidenceList[0], source_id: props.record?.source?.id },
    list: evidenceList.map(ev => ({ ...ev, source_id: props.record?.source?.id })),
    claimText: `研究单元 ${unit.key}`,
  }
  sidebar.open = true
}

const scopeEntries = computed(() => {
  const scope = interpretationValue('scope')
  if (!scope || typeof scope !== 'object' || Array.isArray(scope)) return null
  return Object.entries(scope).map(([key, value]) => ({
    key,
    values: Array.isArray(value) ? value : [value],
  }))
})
function displayItem(value) {
  if (value === undefined || value === null || value === '') return '暂无记录'
  if (Array.isArray(value)) return value.length ? value.map(displayItem).join('；') : '暂无记录'
  if (typeof value === 'object') {
    const entries = Object.entries(value)
    return entries.length ? entries.map(([key, item]) => `${key}：${displayItem(item)}`).join('；') : '暂无记录'
  }
  return String(value)
}
// U19 证据回查链：locator.kind 的人读标签
const LOCATOR_KIND_LABELS = {
  text_offset: '文本偏移', page: '页码', figure_region: '图表区域',
  html_anchor: 'HTML 锚点', markdown_line: 'Markdown 行号',
}
function locatorKindLabel(kind) {
  return LOCATOR_KIND_LABELS[kind] || kind || '未声明类型'
}
function displayScalar(value, key, layer = 'interpretation') {
  if (['update_object', 'research_role', 'mapping_status'].includes(key)) return enumLabel(key, value)
  if (layer === 'source' && key === 'material_type') return enumLabel('material_type', value)
  return displayItem(value)
}

// ----- v5 结构化字段：关联声明（受控词表）与原文层分析单元 -----
const associations = computed(() => {
  const list = props.record?.interpretation?.payload?.associations
  return Array.isArray(list) ? list : []
})

function labeledList(field, values) {
  const items = Array.isArray(values) ? values : values ? [values] : []
  return items.length ? items.map(item => enumLabel(field, item)).join('；') : '暂无记录'
}

function positionLabel(pos) {
  const parts = [enumLabel('position_relation', pos?.relation, ''), enumLabel('position_location', pos?.location, '')]
  const label = parts.filter(Boolean).join(' @ ')
  return label || displayItem(pos)
}

const UNIT_FIELD_LABELS = {
  definitions: '作者定义 / 操作化判据', setup: '设置', process_constraints: '过程约束',
  methods: '方法', conditions: '条件', measures: '测量', findings: '发现',
  author_claims: '作者主张', author_explanations: '作者解释',
  author_limitations: '作者局限', author_open_questions: '作者未决问题',
}

const unitEntries = computed(() => {
  const units = props.record?.source_record?.payload?.units
  if (!Array.isArray(units)) return []
  return units.filter(unit => unit && typeof unit === 'object').map(unit => ({
    key: unit.unit_key || '(未命名单元)',
    raw: unit,
    hasEvidence: Array.isArray(unit.evidence) && unit.evidence.length > 0,
    fields: Object.entries(unit)
      .filter(([key]) => key !== 'unit_key' && key !== 'evidence')
      .map(([key, value]) => ({ key, label: UNIT_FIELD_LABELS[key] || key, value })),
  }))
})

const sharedItems = computed(() => props.record?.source_record?.payload?.shared_items || [])
const unitGaps = computed(() => props.record?.source_record?.payload?.gaps || [])

const coverage = computed(() => translation.value?.source?.coverage || props.record?.source_record?.payload?.coverage || {})
const coverageStatus = computed(() => `阅读状态：${enumLabel('coverage_status', coverage.value?.status)}`)
const coverageItems = computed(() => {
  const items = []
  for (const section of coverage.value?.sections || []) items.push(`章节：${displayItem(section)}`)
  for (const unit of coverage.value?.units || []) items.push(`分析单元：${displayItem(unit)}`)
  if (coverage.value?.note) items.push(`说明：${displayItem(coverage.value.note)}`)
  return items
})

const claimLayers = computed(() => [
  { key: 'source', label: '原文层 claim', claims: props.record?.source_record?.claims || [] },
  { key: 'interpretation', label: '解释层 claim', claims: props.record?.interpretation?.claims || [] },
])
function claimText(layer, claim) { return translatedClaim(props.record, layer, claim) }
const originalJson = computed(() => JSON.stringify({ source_record: props.record?.source_record, interpretation: props.record?.interpretation }, null, 2))

const CONTENT_STATE_LABELS = { needs_completion: '待补全（暂不可用）', needs_review: '待审查', stable: '稳定' }
function stateLabel(layerRecord) {
  if (!layerRecord) return '尚未生成'
  const state = layerRecord.content_state
  return `v${layerRecord.version} · ${CONTENT_STATE_LABELS[state] || state || '状态未提供'}`
}
function stateClass(state) {
  return { stable: 'is-stable', needs_completion: 'is-incomplete', needs_review: 'is-review' }[state] || ''
}
</script>

<style scoped>
.readable-record { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.readable-record :deep(*) { min-width: 0; box-sizing: border-box; }
.readable-record :deep(pre) { max-width: 100%; white-space: pre-wrap; overflow-wrap: anywhere; }
.readable-record :deep(table) { width: 100%; max-width: 100%; table-layout: fixed; }
.readable-record :deep(img) { max-width: 100%; height: auto; }
.translation-notice { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; color: var(--info-fg); border: 1px solid var(--info-border); border-radius: var(--radius-md); background: var(--info-bg); font-size: 11px; line-height: 1.55; }
.translation-notice.missing { color: var(--warn-fg); border-color: var(--warn-border); background: var(--warn-bg); }
.draft-notice { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; color: var(--warn-fg); border: 1px solid var(--warn-border); border-radius: var(--radius-md); background: var(--warn-bg); font-size: 11px; line-height: 1.55; }
.draft-shortcut { justify-self: start; padding: 6px 9px; color: var(--accent-ink); border: 1px solid var(--accent-mute); border-radius: var(--radius-sm); background: var(--accent-subtle); cursor: pointer; font-size: 10px; font-weight: 620; }
.readable-layer { padding-top: 2px; margin-top: 0; }
.layer-title { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.layer-title span { color: var(--text-tertiary); font-size: 9px; letter-spacing: .08em; }
.layer-title h3 { margin: 1px 0 0; color: var(--text-primary); font-size: 15px; letter-spacing: normal; text-transform: none; }
.layer-sub { margin: 3px 0 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }
.layer-title code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.field-group { margin-top: 12px; }
.ontology-mapping { padding: 12px; margin-top: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.mapping-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.mapping-heading h4 { margin: 0; font-size: 12px; }.mapping-heading p { margin-top: 2px; color: var(--text-tertiary); font-size: 10px; }.mapping-heading a { flex: 0 0 auto; color: var(--accent); font-size: 10px; font-weight: 600; }
.mapping-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 7px; margin-top: 9px; }.mapping-list article { display: flex; flex-direction: column; gap: 2px; padding: 9px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-surface); }.mapping-list strong { font-size: 11px; }.mapping-list code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }.mapping-list span { color: var(--text-secondary); font-size: 9px; }
.mapping-gap { padding: 9px 10px; margin-top: 9px; color: var(--warn-fg); border-left: 3px solid var(--warn); background: var(--warn-bg); }.mapping-gap strong { font-size: 10px; }.mapping-gap ul { margin-top: 5px; }.mapping-gap p, .mapping-gap li { font-size: 10px; line-height: 1.55; }
.field-group h4, .claim-group h4 { margin: 0 0 7px; color: var(--text-secondary); font-size: 11px; }
.association-card, .unit-card, .extension-card { margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-surface); }
.association-card header, .unit-card header, .extension-card header { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.association-card header code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.assoc-mapping { padding: 2px 7px; border: 1px solid var(--accent-mute); border-radius: 999px; color: var(--accent-ink); background: var(--accent-subtle); font-size: 9px; font-weight: 620; }
.unit-card header strong, .extension-card header strong { font-size: 11px; }
.ext-name { margin-left: auto; overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.ext-verify { padding: 1px 7px; border-radius: 999px; color: var(--warn-fg); background: var(--warn-bg); font-size: 9px; }
.unit-evidence-link { margin-left: auto; }
.unit-no-evidence { margin-left: auto; color: var(--text-tertiary); font-size: 9px; }
.mini-link { padding: 2px 8px; border: 1px solid var(--accent-mute); border-radius: 999px; background: var(--accent-subtle); color: var(--accent-ink); cursor: pointer; font-size: 10px; font-weight: 620; }
.unit-extra { padding: 9px 10px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-page); }
.unit-extra h4 { margin: 0 0 5px; font-size: 10px; }
.unit-extra li { font-size: 10px; line-height: 1.55; }
.coverage-line { margin: 0; padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-page); color: var(--text-secondary); font-size: 10px; line-height: 1.7; }
.gap-list { display: grid; gap: 7px; padding: 0; margin: 8px 0 0; list-style: none; }
.gap-list li { padding: 9px 10px; border: 1px solid var(--border); border-left: 3px solid var(--info-mute, var(--border-strong)); border-radius: var(--radius-sm); background: var(--bg-page); }
.gap-list li strong { font-size: 10px; }
.gap-status { margin-left: 8px; padding: 1px 7px; border-radius: 999px; font-size: 9px; color: var(--info-fg); background: var(--info-bg); }
.gap-status.open { color: var(--warn-fg); background: var(--warn-bg); }
.gap-list p { margin: 4px 0 0; font-size: 10px; line-height: 1.6; color: var(--text-secondary); }
.gap-note { margin: 6px 0 0; color: var(--text-tertiary); font-size: 9px; line-height: 1.6; }
dl { display: grid; grid-template-columns: minmax(120px, 160px) minmax(0, 1fr); margin: 0; border-top: 1px solid var(--border); }
dt, dd { padding: 9px 10px; border-bottom: 1px solid var(--border); }
dt { display: flex; flex-direction: column; gap: 2px; color: var(--text-secondary); background: var(--bg-page); font-size: 11px; }
dt code { color: var(--text-tertiary); font-size: 9px; }
dd { margin: 0; font-size: 12px; line-height: 1.65; }
dd p { margin: 0; white-space: pre-wrap; }
ul { padding-left: 18px; margin: 0; }
li + li { margin-top: 4px; }
.claim-group { margin-top: 12px; }
.claim-card { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.claim-card + .claim-card { margin-top: 8px; }
.claim-card header { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.claim-card header strong { font-size: 12px; line-height: 1.55; }
.claim-card header code { color: var(--text-tertiary); font-size: 9px; }
.evidence-item { margin-top: 9px; }
.evidence-item small { color: var(--text-secondary); font-size: 9px; }
blockquote { padding: 8px 10px; margin: 4px 0 6px; border-left: 3px solid var(--border-strong); background: var(--bg-surface); font: 11px/1.55 var(--font-mono); white-space: pre-wrap; }
.anchor-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--text-tertiary); }
.anchor-meta code { font-size: 9px; }
.empty-value { margin: 0; color: var(--text-tertiary); font-size: 11px; }
/* 迁移/修订历史：默认折叠的维护信息 */
.maintenance-history { margin-top: 12px; padding: 9px 12px; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); background: var(--bg-page); }
.maintenance-history > summary { cursor: pointer; color: var(--text-secondary); font-size: 11px; font-weight: 620; }
.maintenance-history.unknown-ext > summary { color: var(--warn-fg); }
.maintenance-note { margin: 8px 0 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }
.extension-card.maintenance { background: var(--bg-page); }
.tech-meta { margin-top: 10px; }
.tech-meta h5 { margin: 0 0 4px; font-size: 10px; color: var(--text-secondary); }
.tech-meta pre { max-height: 220px; overflow: auto; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-surface); font: 9px/1.6 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
.editing-layer { padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-page); }
.draft-intro { margin: 8px 0 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.7; }
.edit-toolbar { display: flex; align-items: center; gap: 8px; margin-top: 11px; }.edit-toolbar > div { display: flex; min-width: 0; flex: 1; flex-direction: column; }.edit-toolbar strong { font-size: 11px; }.edit-toolbar span { color: var(--text-tertiary); font-size: 10px; }.edit-toolbar button, .draft-form button { padding: 6px 9px; color: var(--accent-ink); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); cursor: pointer; font-size: 10px; }.edit-toolbar button:disabled, .draft-form button:disabled { cursor: not-allowed; opacity: .5; }
.edit-error, .edit-message { padding: 8px 10px; margin-top: 9px; color: var(--warn-fg); border-radius: var(--radius-sm); background: var(--warn-bg); font-size: 10px; }.edit-message { color: var(--info-fg); background: var(--info-bg); }
.draft-history { margin-top: 8px; color: var(--text-secondary); font-size: 10px; }.draft-history summary { cursor: pointer; }.draft-history ul { padding-left: 0; margin-top: 5px; list-style: none; }.draft-history li { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; border-top: 1px solid var(--border); }.draft-history code { color: var(--text-tertiary); font-size: 8px; }
.draft-form { display: grid; gap: 11px; padding-top: 12px; margin-top: 12px; border-top: 1px solid var(--border); }.draft-form label { display: grid; gap: 4px; color: var(--text-secondary); font-size: 10px; }.draft-form textarea, .draft-form input, .draft-form select { width: 100%; padding: 7px 8px; color: var(--text-primary); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); font: 11px/1.55 var(--font-sans); }.draft-form textarea { resize: vertical; }.change-kind { grid-template-columns: 120px minmax(0, 1fr); align-items: center; }.draft-form details { padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); }.draft-form details summary { margin-bottom: 9px; cursor: pointer; font-size: 11px; font-weight: 620; }.draft-form details label + label { margin-top: 9px; }
.draft-form fieldset { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); }.draft-form legend { padding: 0 4px; color: var(--text-secondary); font-size: 10px; }.concept-choice { display: flex !important; width: auto !important; flex-direction: row; align-items: flex-start; gap: 5px !important; padding: 5px 7px; border: 1px solid var(--border); border-radius: var(--radius-sm); }.concept-choice input { width: auto; margin-top: 2px; }.concept-choice span { display: flex; flex-direction: column; color: var(--text-primary); }.concept-choice small { color: var(--text-tertiary); font: 8px var(--font-mono); }
.review-request-builder { padding: 10px; border-left: 3px solid var(--info); background: var(--info-bg); }.review-request-builder > strong { color: var(--info-fg); font-size: 10px; }.review-request-builder > div { display: grid; grid-template-columns: 190px minmax(0, 1fr) auto; gap: 6px; margin-top: 7px; }.review-request-builder ul { margin-top: 8px; padding-left: 0; list-style: none; }.review-request-builder li { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 5px 0; border-top: 1px solid var(--info-border); }.review-request-builder code { overflow-wrap: anywhere; font-size: 8px; }.review-request-builder span { font-size: 10px; }.form-actions { display: flex; gap: 7px; }.form-actions button:first-child { color: #fff; border-color: var(--accent); background: var(--accent); }.evidence-lock { color: var(--text-tertiary); font-size: 10px; }
.audit-record { margin-top: 2px; }
.audit-record summary { color: var(--accent); cursor: pointer; font-size: 11px; }
.audit-record pre { max-height: 320px; overflow: auto; padding: 10px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); font: 10px/1.55 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
.record-state { display: flex; flex-wrap: wrap; gap: 6px; }
.record-state span { padding: 4px 9px; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); color: var(--text-secondary); font-size: 10px; font-weight: 620; }
.record-state span.is-stable { color: var(--ok-fg, var(--text-secondary)); border-color: var(--ok-border, var(--border-strong)); background: var(--ok-bg, var(--bg-surface)); }
.record-state span.is-incomplete { color: var(--error-fg, var(--warn-fg)); border-color: var(--error-border, var(--warn-border)); background: var(--error-bg, var(--warn-bg)); }
.record-state span.is-review { color: var(--warn-fg); border-color: var(--warn-border); background: var(--warn-bg); }
.record-state span.state-schema { font-weight: 400; color: var(--text-tertiary); }
.feedback-layer .feedback-intro { margin: 9px 0 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }
.feedback-list { display: grid; gap: 8px; padding: 0; margin: 10px 0 0; list-style: none; }
.feedback-list li { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.feedback-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.feedback-head code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.feedback-status { flex: 0 0 auto; padding: 2px 7px; border-radius: var(--radius-sm); font-size: 9px; font-weight: 620; }
.feedback-status.is-open { color: var(--warn-fg); background: var(--warn-bg); }
.feedback-status.is-pending { color: var(--info-fg); background: var(--info-bg); }
.feedback-status.is-closed { color: var(--text-secondary); border: 1px solid var(--border-strong); background: var(--bg-surface); }
.feedback-claim { margin: 0; font-size: 12px; line-height: 1.6; }
.feedback-meta { margin: 0; color: var(--text-secondary); font-size: 10px; }
.feedback-meta code { overflow-wrap: anywhere; font-size: 9px; }
.feedback-form { display: grid; gap: 7px; padding-top: 10px; margin-top: 4px; border-top: 1px solid var(--border); }
.feedback-form label { display: grid; gap: 4px; color: var(--text-secondary); font-size: 10px; }
.feedback-form textarea { width: 100%; padding: 7px 8px; color: var(--text-primary); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); font: 11px/1.55 var(--font-sans); resize: vertical; }
.feedback-form button { justify-self: start; padding: 6px 10px; color: #fff; border: 1px solid var(--accent); border-radius: var(--radius-sm); background: var(--accent); cursor: pointer; font-size: 10px; font-weight: 620; }
.feedback-form button:disabled { cursor: not-allowed; opacity: .5; }
.audit-record summary { color: var(--accent); cursor: pointer; font-size: 11px; }
.evidence-preview { margin: 4px 0; line-height: 1.6; }
.evidence-preview .preview-context { display: inline; color: var(--text-secondary); }
.evidence-preview mark { background: rgba(255, 213, 79, .35); padding: 0 2px; }
.preview-occurrence { display: block; margin-top: 2px; color: var(--text-secondary); }
.scope-row { display: flex; gap: 8px; align-items: baseline; margin: 3px 0; }
.scope-row ul { margin: 0; padding-left: 16px; }
@media (max-width: 720px) { dl { grid-template-columns: 1fr; } dt { border-bottom: 0; }.edit-toolbar { align-items: stretch; flex-direction: column; }.review-request-builder > div, .review-request-builder li { grid-template-columns: 1fr; }.change-kind { grid-template-columns: 1fr; } }
</style>
