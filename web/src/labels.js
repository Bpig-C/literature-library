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
  framework: '框架',
  taxonomy: '分类法',
  evaluation_framework: '评估框架',
  benchmark: '基准测试',
  dataset: '数据集',
  evaluation_suite: '评测套件',
  metric: '度量指标',
  model: '模型',
  system_card: '系统卡',
  model_card: '模型卡',
  safety_report: '安全报告',
  transparency_report: '透明度报告',
  safety_case_argument: '安全论证',
  risk_update: '风险更新',
  interpretability_finding: '可解释性发现',
  audit_finding: '审计发现',
  standard: '标准',
  guideline: '指南',
  governance: '治理',
  policy: '政策',
  risk_management: '风险管理',
  audit: '审计',
  red_teaming: '红队测试',
  safety_case: '安全论证',
  transparency: '透明度',
  monitorability: '可监控性',
  interpretability: '可解释性',
  leaderboard: '排行榜',
  platform: '平台',
  trend: '趋势',
  literature_index: '文献索引',
  workflow_cache: '工作流缓存',
}

export const RISK_DOMAIN_LABELS = {
  deception: '欺骗',
  scheming: '策略性欺骗',
  sandbagging: '能力隐藏',
  evaluation_awareness: '评测意识',
  information_concealment: '信息遮蔽',
  persuasion: '影响操纵',
  misinformation: '错误信息',
  autonomy: '自主性',
  self_replication: '自复制',
  resource_acquisition: '资源获取',
  goal_preservation: '目标守护',
  covert_action: '隐蔽行动',
  oversight_subversion: '监控规避',
  autonomous_ai_rnd: '自主AI研发',
  multi_agent_collusion: '多智能体串谋',
  sabotage: '破坏行为',
  cybersecurity: '网络安全',
  biosecurity: '生物安全',
  chemical_security: '化学安全',
  dual_use: '双重用途',
  catastrophic_risk: '灾难性风险',
  misuse: '滥用',
  governance_risk: '治理失效',
  model_behavior: '模型行为',
  privacy: '隐私',
  fairness: '公平性',
  robustness: '鲁棒性',
  safety_case_validity: '安全论证有效性',
  unknown: '未知',
}

export const METHOD_TAG_LABELS = {
  benchmark_construction: '基准构建',
  dataset_curation: '数据集策划',
  evaluation_protocol: '评估流程设计',
  evaluation_execution: '评估实施',
  pre_deployment_evaluation: '部署前评估',
  multi_model_comparison: '多模型比较',
  capability_evaluation: '能力评估',
  risk_assessment: '风险评估',
  red_teaming: '红队测试',
  auditing: '审计',
  external_audit: '外部审计',
  sandbagging_detection: '沙袋检测',
  elicitation: '能力引出',
  evaluation_awareness_testing: '评测意识测试',
  reward_hacking_detection: '奖励黑客检测',
  cross_modality_consistency: '跨模态一致性',
  agentic_behavior_audit: 'Agent行为审计',
  multi_agent_sandbox: '多智能体沙箱',
  white_box_probing: '白盒探针',
  safety_case_construction: '安全论证构建',
  safety_case: '安全论证',
  model_card_analysis: '模型卡分析',
  policy_mapping: '政策映射',
  taxonomy_building: '分类法构建',
  standard_comparison: '标准比较',
  empirical_experiment: '实证实验',
  case_study: '案例研究',
  expert_elicitation: '专家征询',
  leaderboard_comparison: '排行榜比较',
  text_extraction: '正文抽取',
  document_repair: '文档修复',
  summary_synthesis: '摘要综合',
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

export const PROCESSING_FLAGS_LABELS = {
  needs_pdf_conversion: '需转PDF',
  html_retained: '保留HTML',
  screenshot_only: '仅截图',
  homepage_snapshot_problem: '首页快照',
  not_original_document: '非原文',
  text_extraction_failed: '抽取失败',
  text_extraction_fixed: '抽取已修复',
  duplicate_candidate: '疑似重复',
  duplicate_confirmed: '确认重复',
  cache_only: '仅缓存',
  repair_workspace: '修复工作区',
  source_url_uncertain: '来源URL不确定',
  source_url_dead: '来源URL失效',
  manually_verified: '已人工核验',
  needs_relocation: '需移动',
  deprecated_version: '旧版本',
}

/** Map of tag_group -> value labels for resolving tag values to Chinese. */
export const TAG_VALUE_LABELS = {
  reading_lane: READING_LANE_LABELS,
  artifact_focus: ARTIFACT_FOCUS_LABELS,
  risk_domain: RISK_DOMAIN_LABELS,
  method_tags: METHOD_TAG_LABELS,
  processing_flags: PROCESSING_FLAGS_LABELS,
}

/** Get a Chinese label or fall back to the raw value. */
export function label(map, key) {
  return map[key] || key
}
