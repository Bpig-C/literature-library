/**
 * 选项常量集中管理
 * 从各页面提取的静态选项，统一维护
 */

/** 主要文档类型 */
export const PRIMARY_DOC_TYPE_OPTIONS = [
  { value: 'research_article', label: '研究论文' },
  { value: 'review_article', label: '综述' },
  { value: 'conference_paper', label: '会议论文' },
  { value: 'thesis', label: '学位论文' },
  { value: 'book', label: '图书' },
  { value: 'book_chapter', label: '书章节' },
  { value: 'report', label: '报告' },
  { value: 'preprint', label: '预印本' },
  { value: 'dataset', label: '数据集' },
  { value: 'other', label: '其他' },
]

/** 阅读通道 */
export const READING_LANE_OPTIONS = [
  { value: 'must_read', label: '必读' },
  { value: 'should_read', label: '应读' },
  { value: 'nice_to_read', label: '可读' },
  { value: 'skim', label: '浏览' },
  { value: 'skip', label: '跳过' },
]

/** 出版状态 */
export const PUBLICATION_STATUS_OPTIONS = [
  { value: 'published', label: '已出版' },
  { value: 'in_press', label: '待出版' },
  { value: 'submitted', label: '已投稿' },
  { value: 'draft', label: '草稿' },
  { value: 'unknown', label: '未知' },
]

/** 摄入状态 */
export const INGESTION_STATE_OPTIONS = [
  { value: 'pending', label: '待处理' },
  { value: 'parsing', label: '解析中' },
  { value: 'parsed', label: '已解析' },
  { value: 'failed', label: '失败' },
  { value: 'skipped', label: '跳过' },
]

/** 优先级 */
export const PRIORITY_OPTIONS = [
  { value: 'P0', label: 'P0 - 紧急' },
  { value: 'P1', label: 'P1 - 高' },
  { value: 'P2', label: 'P2 - 中' },
  { value: 'P3', label: 'P3 - 低' },
]

/** 隔离原因 */
export const QUARANTINE_REASON_OPTIONS = [
  { value: 'duplicate', label: '重复文献' },
  { value: 'low_quality', label: '低质量' },
  { value: 'off_topic', label: '主题不符' },
  { value: 'retracted', label: '已撤稿' },
  { value: 'spam', label: '垃圾内容' },
  { value: 'test', label: '测试数据' },
  { value: 'other', label: '其他' },
]

/** 审核状态 */
export const REVIEW_STATUS_OPTIONS = [
  { value: 'pending', label: '待审' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'needs_fix', label: '需修正' },
  { value: 'quarantined', label: '已隔离' },
]

/** 置信度等级 */
export const CONFIDENCE_LEVEL_OPTIONS = [
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

/** 主题成熟度 */
export const TOPIC_MAP_STATUS_OPTIONS = [
  { value: 'seedling', label: '萌芽' },
  { value: 'proposed', label: '提议' },
  { value: 'mapped', label: '已映射' },
]

/** 发现检索模式 */
export const DISCOVERY_MODE_OPTIONS = [
  { value: 'topic', label: '按主题' },
  { value: 'name', label: '按名称' },
  { value: 'title', label: '按标题' },
  { value: 'url', label: '按URL' },
]

/** 状态 → 颜色映射 */
export const STATUS_COLOR_MAP = {
  approved: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', border: 'var(--ok-border)' },
  succeeded: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', border: 'var(--ok-border)' },
  accepted: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', border: 'var(--ok-border)' },
  ok: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', border: 'var(--ok-border)' },
  pending: { bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', border: 'var(--warn-border)' },
  planned: { bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', border: 'var(--warn-border)' },
  running: { bg: 'var(--info-bg)', fg: 'var(--info-fg)', border: 'var(--info-border)' },
  rejected: { bg: 'var(--bad-bg)', fg: 'var(--bad-fg)', border: 'var(--bad-border)' },
  failed: { bg: 'var(--bad-bg)', fg: 'var(--bad-fg)', border: 'var(--bad-border)' },
  quarantined: { bg: 'var(--neutral-bg)', fg: 'var(--neutral-fg)', border: 'var(--neutral-border)' },
  needs_fix: { bg: 'var(--fix-bg)', fg: 'var(--fix-fg)', border: 'var(--warn-border)' },
  seedling: { bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', border: 'var(--warn-border)' },
  proposed: { bg: 'var(--info-bg)', fg: 'var(--info-fg)', border: 'var(--info-border)' },
  mapped: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', border: 'var(--ok-border)' },
  unknown: { bg: 'var(--neutral-bg)', fg: 'var(--neutral-fg)', border: 'var(--neutral-border)' },
}
