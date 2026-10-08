import { ref } from 'vue'

/**
 * PDF 抽屉控制 Composable
 * 统一 MetadataReview/ClassificationReview 的 PDF 抽屉逻辑
 *
 * @returns {object} PDF 抽屉状态和方法
 *
 * @example
 * const { showPdfDrawer, activePdfWorkId, pdfPreviewKey, openPdf, closePdf, togglePdf } = usePdfDrawer()
 */
export function usePdfDrawer() {
  const showPdfDrawer = ref(false)
  const activePdfWorkId = ref(null)
  const pdfPreviewKey = ref(0)

  /**
   * 打开 PDF 预览
   * @param {string} workId - 文献 ID
   */
  function openPdf(workId) {
    activePdfWorkId.value = workId
    showPdfDrawer.value = true
    pdfPreviewKey.value++
  }

  /**
   * 关闭 PDF 预览
   */
  function closePdf() {
    showPdfDrawer.value = false
    activePdfWorkId.value = null
  }

  /**
   * 切换 PDF 预览
   * @param {string} workId - 文献 ID
   */
  function togglePdf(workId) {
    if (showPdfDrawer.value && activePdfWorkId.value === workId) {
      closePdf()
    } else {
      openPdf(workId)
    }
  }

  return {
    showPdfDrawer,
    activePdfWorkId,
    pdfPreviewKey,
    openPdf,
    closePdf,
    togglePdf,
  }
}
