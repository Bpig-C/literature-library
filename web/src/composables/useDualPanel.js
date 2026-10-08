import { ref, computed } from 'vue'

/**
 * 双面板布局 Composable
 * 统一 IntakeReview/InboxReview/Duplicates/MetadataReview/ClassificationReview 的双面板逻辑
 *
 * @param {object} [options]
 * @param {number} [options.defaultListWidth=480] - 默认列表宽度
 * @param {number} [options.minListWidth=280] - 最小列表宽度
 * @param {number} [options.maxListWidth=600] - 最大列表宽度
 * @returns {object} 布局状态和方法
 *
 * @example
 * const { listWidth, listCollapsed, detailWidth, layoutStyle, toggleList, onResize } = useDualPanel()
 */
export function useDualPanel(options = {}) {
  const {
    defaultListWidth = 480,
    minListWidth = 280,
    maxListWidth = 600,
  } = options

  const listWidth = ref(defaultListWidth)
  const listCollapsed = ref(false)
  const savedWidth = ref(defaultListWidth)

  const detailWidth = computed(() => {
    if (listCollapsed.value) return '1fr'
    return `calc(100% - ${listWidth.value}px)`
  })

  const layoutStyle = computed(() => ({
    display: 'grid',
    gridTemplateColumns: listCollapsed.value
      ? '0 1fr'
      : `${listWidth.value}px 1fr`,
    gap: '0',
    height: '100%',
  }))

  /**
   * 切换列表折叠状态
   */
  function toggleList() {
    if (listCollapsed.value) {
      listCollapsed.value = false
      listWidth.value = savedWidth.value
    } else {
      savedWidth.value = listWidth.value
      listCollapsed.value = true
    }
  }

  /**
   * 处理列表宽度调整
   * @param {number} delta - 宽度变化量（正数向右，负数向左）
   */
  function onResize(delta) {
    const newWidth = listWidth.value + delta
    listWidth.value = Math.max(minListWidth, Math.min(maxListWidth, newWidth))
  }

  /**
   * 重置列表宽度
   */
  function resetWidth() {
    listWidth.value = defaultListWidth
  }

  return {
    listWidth,
    listCollapsed,
    detailWidth,
    layoutStyle,
    toggleList,
    onResize,
    resetWidth,
    minListWidth,
    maxListWidth,
  }
}
