import { ref } from 'vue'
import { quarantineWork, quarantineFromReview, quarantineFromClassificationReview } from '../api'
import { showError } from '../error-handler'

/**
 * 隔离操作 Composable
 * 统一 Works/WorkDetail/MetadataReview/ClassificationReview 的隔离逻辑
 *
 * @param {object} [options]
 * @param {'work'|'metadata'|'classification'} [options.type='work'] - 隔离类型
 * @param {Function} [options.onSuccess] - 隔离成功回调
 * @returns {object} 隔离相关状态和方法
 *
 * @example
 * const { showQuarantineModal, quarantineReason, openQuarantine, doQuarantine } = useQuarantine({
 *   type: 'metadata',
 *   onSuccess: () => reload()
 * })
 */
export function useQuarantine(options = {}) {
  const { type = 'work', onSuccess } = options

  const showQuarantineModal = ref(false)
  const quarantineReason = ref('')
  const quarantineTargetId = ref(null)
  const quarantineLoading = ref(false)

  /**
   * 隔离原因列表
   */
  const QUARANTINE_REASONS = [
    { key: 'bad_source', label: '坏源：PDF 内容为空、反爬页、扫描损坏等' },
    { key: 'out_of_scope', label: '不在范围：不属于当前研究主题或综述范围' },
    { key: 'not_literature', label: '非文献：不是论文、报告、标准等目标文献' },
    { key: 'duplicate_residual', label: '重复残留：已由其他 work 覆盖' },
    { key: 'needs_rerun', label: '待重跑：主题对，但上传文档本身有问题，需替换后重新抽取' },
    { key: 'user_removed', label: '用户移除：明确不想保留' },
  ]

  /**
   * 打开隔离弹窗
   * @param {string} [targetId] - 要隔离的目标 ID（work_id 或 extraction_id）
   */
  function openQuarantine(targetId) {
    quarantineTargetId.value = targetId || null
    quarantineReason.value = ''
    showQuarantineModal.value = true
  }

  /**
   * 关闭隔离弹窗
   */
  function closeQuarantine() {
    showQuarantineModal.value = false
    quarantineReason.value = ''
    quarantineTargetId.value = null
  }

  /**
   * 执行隔离操作
   * @param {string} [overrideId] - 覆盖目标 ID（用于列表项直接隔离）
   */
  async function doQuarantine(overrideId) {
    const targetId = overrideId || quarantineTargetId.value
    if (!targetId || !quarantineReason.value) {
      showError(new Error('请选择隔离原因'))
      return
    }

    quarantineLoading.value = true
    try {
      switch (type) {
        case 'metadata':
          await quarantineFromReview(targetId, quarantineReason.value)
          break
        case 'classification':
          await quarantineFromClassificationReview(targetId, quarantineReason.value)
          break
        case 'work':
        default:
          await quarantineWork(targetId, quarantineReason.value)
          break
      }

      showQuarantineModal.value = false
      if (onSuccess) onSuccess()
    } catch (e) {
      showError(e)
    } finally {
      quarantineLoading.value = false
    }
  }

  return {
    QUARANTINE_REASONS,
    showQuarantineModal,
    quarantineReason,
    quarantineTargetId,
    quarantineLoading,
    openQuarantine,
    closeQuarantine,
    doQuarantine,
  }
}
