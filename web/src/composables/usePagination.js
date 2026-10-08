import { ref, computed } from 'vue'

/**
 * Unified pagination composable.
 * @param {Object} options
 * @param {number} options.perPage - items per page (default 20)
 * @param {string} options.mode - 'page' for page/per_page API, 'offset' for limit/offset API
 */
export function usePagination({ perPage = 20, mode = 'page' } = {}) {
  const page = ref(1)
  const total = ref(0)

  const params = computed(() => {
    if (mode === 'offset') {
      return { limit: perPage, offset: (page.value - 1) * perPage }
    }
    return { page: page.value, per_page: perPage }
  })

  const totalPages = computed(() => Math.ceil(total.value / perPage))

  function reset() {
    page.value = 1
  }

  return { page, total, totalPages, params, reset }
}
