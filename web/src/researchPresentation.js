import { displayArtifact } from './researchAssets'

export const DISPLAY_ARTIFACT = displayArtifact

export const ENUM_LABELS = {
  update_object: {
    parameter: '模型参数',
    harness: '运行支架 / 上下文',
    mixed: '参数与运行支架混合',
    none: '无模型干预',
    unclear: '不明确',
  },
  research_role: {
    measure: '测量',
    elicit: '诱发 / 能力引出',
    explain: '解释',
    mitigate: '缓解',
    govern: '治理',
    theorize: '理论分析',
  },
  mapping_status: {
    mapped: '已映射',
    partially_mapped: '部分映射',
    unmapped: '未映射',
    ambiguous: '映射有歧义',
  },
  // 受控词表 v5（§13.4）：关联声明的方面、作用、位置与干预粒度
  research_aspects: {
    capability: '能力',
    conditional_behavior: '条件性行为',
    propensity: '倾向',
    formation_mechanism: '形成机制',
    scenario_consequence: '场景后果',
    control_condition_or_failure: '控制条件或失控',
    method_or_norm: '方法或规范',
  },
  research_roles: {
    measure: '测量',
    elicit: '诱发 / 能力引出',
    explain: '解释',
    mitigate: '缓解',
    theorize: '理论分析',
    govern: '治理',
  },
  update_intervention_kind: {
    parameter: '模型参数',
    harness: '运行支架 / 上下文',
    mixed: '参数与运行支架混合',
    none: '无模型干预',
    unclear: '不明确',
  },
  position_relation: {
    formation: '形成',
    manifestation: '表现',
    impact: '影响',
    measure_target: '测量对象',
  },
  position_location: {
    parameter_update: '参数更新',
    harness_configuration: '支架配置',
    runtime_execution: '运行执行',
    evaluation_feedback: '评估反馈',
    deployment_environment: '部署环境',
    human_organization: '人类组织',
  },
  material_type: {
    'benchmark / experimental paper': '基准 / 实验论文',
    comparative_governance_review: '比较治理综述',
    'conceptual and experimental machine-learning paper': '概念与实验机器学习论文',
    'experimental paper': '实验论文',
    'evaluation report / experimental paper': '评估报告 / 实验论文',
    independent_evaluation_report: '独立评估报告',
    cross_lab_evaluation_report: '跨实验室评估报告',
    'developer system card and evaluation report': '开发者系统卡与评估报告',
    'formal decision-theoretic paper': '形式化决策理论论文',
    frontier_ai_governance_framework: '前沿 AI 治理框架',
    government_governance_profile: '政府治理框架',
    'international scientific review and policy-facing risk report': '国际科学综述与政策风险报告',
    methods_survey: '方法综述',
    'philosophical and normative design-account paper': '哲学与规范性设计论文',
    'position paper with structured evidence audits and formalization': '含结构化证据审计与形式化分析的立场论文',
    'risk-analysis technical report with multi-domain evaluations': '含多领域评估的风险分析技术报告',
    standards_mapping_governance_profile: '标准映射治理框架',
    systematic_analysis_review: '系统分析综述',
  },
  coverage_status: {
    read: '已通读',
    section_scoped: '按章节范围阅读',
    partial: '部分覆盖',
    not_reported: '原文未报告',
  },
}

export function rawResearchValue(value) {
  return value && typeof value === 'object' && 'value' in value ? value.value : value
}

export function researchWorkId(record) {
  return record?.source?.work_id || record?.work_id || ''
}

function rowSnapshotHash(record) {
  return record?.snapshot?.content_sha256
    || record?.snapshot?.source_sha256
    || record?.source?.content_sha256
    || record?.source?.source_sha256
    || record?.interpretation?.snapshot_sha256
    || record?.source_record?.snapshot_sha256
    || ''
}

export function boundDisplayTranslation(record) {
  const item = DISPLAY_ARTIFACT.records?.[researchWorkId(record)]
  if (!item) return null
  const binding = item.binding || {}
  const checks = [
    [binding.batch_id, record?.batch_id],
    [binding.source_record_id, record?.source_record?.id],
    [binding.source_record_version, record?.source_record?.version],
    [binding.interpretation_id, record?.interpretation?.id],
    [binding.interpretation_version, record?.interpretation?.version],
    [binding.snapshot_sha256, rowSnapshotHash(record)],
  ]
  return checks.every(([expected, actual]) => String(expected ?? '') === String(actual ?? '')) ? item : null
}

export function enumLabel(field, value, fallback = '暂无记录') {
  const raw = rawResearchValue(value)
  if (raw === undefined || raw === null || raw === '') return fallback
  return ENUM_LABELS[field]?.[String(raw)] || String(raw)
}

export function translatedField(record, layer, field) {
  const translation = boundDisplayTranslation(record)
  if (translation?.[layer] && Object.prototype.hasOwnProperty.call(translation[layer], field)) {
    return translation[layer][field]
  }
  if (layer === 'interpretation') return rawResearchValue(record?.interpretation?.payload?.[field])
  return rawResearchValue(record?.source_record?.payload?.[field])
}

export function translatedClaim(record, layer, claim) {
  const translated = boundDisplayTranslation(record)?.[layer]?.claims?.[claim?.key]
  return translated || claim?.text || '暂无 claim 描述'
}

export function listFieldDisplay(record, field) {
  const value = translatedField(record, 'interpretation', field)
  if (field === 'update_object' || field === 'research_role' || field === 'mapping_status') {
    return enumLabel(field, value)
  }
  if (Array.isArray(value)) return value.length ? value.join('；') : '暂无记录'
  return value === undefined || value === null || value === '' ? '暂无记录' : String(value)
}
