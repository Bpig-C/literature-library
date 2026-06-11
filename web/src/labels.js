/** Shared Chinese label mappings for display values. */

export const DOC_TYPE_LABELS = {
  paper: '论文',
  report: '报告',
  system_card: '系统卡',
  benchmark: '基准测试',
  preprint: '预印本',
}

export const PRIMARY_DOC_TYPE_LABELS = {
  research_article: '研究论文',
  survey_review: '综述/评述',
  technical_report: '技术报告',
  system_model_card: '系统卡/模型卡',
  evaluation_report: '第三方评估报告',
  standard_guideline: '标准/指南',
  governance_framework: '治理框架',
  benchmark_dataset_paper: '基准/数据集论文',
  institutional_report: '机构报告',
  webpage_blog: '网页/博客',
  platform_snapshot: '平台快照',
  thesis: '学位论文',
  book_chapter: '书章',
  workflow_artifact: '工作流产物',
  other_literature: '其他文献',
  not_literature: '非文献',
}

export const PUBLICATION_STATUS_LABELS = {
  published: '已发表',
  preprint: '预印本',
  working_paper: '工作论文',
  draft: '草案',
  living_document: '持续更新文档',
  institutional_release: '机构正式发布',
  webpage_release: '网页发布',
  unknown: '未知',
}

export const INGESTION_STATE_LABELS = {
  verified: '已核验',
  needs_review: '待核查',
  provisional: '暂留',
  excluded: '已排除',
  deprecated: '已废弃',
}

export const PRIORITY_LABELS = {
  P0: '核心必读',
  P1: '重要',
  P2: '参考',
  P3: '边缘',
  archive: '归档',
}

export const LANGUAGE_LABELS = {
  en: '英文',
  zh: '中文',
  unknown: '未知',
}

export const READ_STATUS_LABELS = {
  unread: '未读',
  quarantined: '已隔离',
}

export const PARSE_STATUS_LABELS = {
  succeeded: '成功',
  failed: '失败',
  pending: '待解析',
  unknown: '未知',
}

export const RELATION_TYPE_LABELS = {
  translation_of: '翻译版本',
  version_of: '版本关系',
  same_work: '同一作品',
  part_of: '组成部分',
  supersedes: '取代',
  not_duplicate: '非重复',
  parent: '父级',
  child: '子级',
  companion: '伴随文献',
}

export const TAG_GROUP_LABELS = {
  reading_lane: '阅读用途',
  artifact_focus: '贡献对象',
  risk_domain: '风险领域',
  method_tags: '方法标签',
  processing_flags: '处理标记',
}

export const READING_LANE_LABELS = {
  framework_taxonomy: '框架与分类',
  evaluation_method: '评测方法',
  governance_method: '治理方法',
  system_transparency: '系统透明度',
  model_technical_profile: '模型技术特征',
  institutional_landscape: '机构生态',
  safety_case_method: '安全论证',
  interpretability_method: '可解释性',
  background_theory: '理论背景',
  literature_mapping: '文献综述',
  workflow_support: '工作流支持',
}

export const ARTIFACT_FOCUS_LABELS = {
  benchmark: '基准测试',
  dataset: '数据集',
  eval_suite: '评测套件',
  audit_finding: '审计发现',
  safety_report: '安全报告',
  capability_profile: '能力画像',
  risk_assessment: '风险评估',
  policy_analysis: '政策分析',
  framework_proposal: '框架提案',
  tool_release: '工具发布',
  empirical_finding: '实证发现',
  theoretical_contribution: '理论贡献',
}

export const RISK_DOMAIN_LABELS = {
  scheming: '策略性欺骗',
  deception: '欺骗',
  evaluation_awareness: '评测意识',
  reward_hacking: '奖励黑客',
  power_seeking: '权力寻求',
  self_preservation: '自我保存',
  jailbreak_resistance: '越狱抵抗',
  alignment_tax: '对齐税',
  cyber_offense: '网络攻击',
  bio_risk: '生物风险',
  persuasion: '说服力',
  autonomous_replication: '自主复制',
  distributional_risk: '分布风险',
  systemic_risk: '系统性风险',
}

export const METHOD_TAG_LABELS = {
  benchmark_construction: '基准构建',
  evaluation_execution: '评测执行',
  red_teaming: '红队测试',
  interpretability_analysis: '可解释性分析',
  formal_verification: '形式化验证',
  dataset_curation: '数据集策划',
  survey_synthesis: '综述合成',
  case_study: '案例研究',
  empirical_measurement: '实证测量',
  theoretical_analysis: '理论分析',
  policy_review: '政策审查',
  framework_design: '框架设计',
}

export const SOURCE_ACTOR_TYPE_LABELS = {
  frontier_ai_company: '前沿 AI 公司',
  domestic_ai_company: '国内 AI 公司',
  evaluation_lab: '评测实验室',
  government_agency: '政府机构',
  standards_body: '标准组织',
  international_network: '国际网络',
  academic_group: '学术机构',
  civil_society_org: '民间组织',
  platform_dashboard: '平台/仪表盘',
  unknown: '未知',
}

export const REGION_LABELS = {
  US: '美国',
  UK: '英国',
  EU: '欧盟',
  CN: '中国',
  JP: '日本',
  KR: '韩国',
  SG: '新加坡',
  international: '国际',
  unknown: '未知',
}

/** Map of tag_group -> value labels for resolving tag values to Chinese. */
export const TAG_VALUE_LABELS = {
  reading_lane: READING_LANE_LABELS,
  artifact_focus: ARTIFACT_FOCUS_LABELS,
  risk_domain: RISK_DOMAIN_LABELS,
  method_tags: METHOD_TAG_LABELS,
}

/** Get a Chinese label or fall back to the raw value. */
export function label(map, key) {
  return map[key] || key
}
