import { ref } from 'vue'

/**
 * 异步操作 Composable
 * 统一 loading/error/data 模式
 *
 * @param {Function} asyncFn - 异步函数
 * @param {object} [options]
 * @param {boolean} [options.immediate=false] - 是否立即执行
 * @returns {object} 操作状态和方法
 *
 * @example
 * const { loading, error, data, execute, reset } = useAsyncOperation(fetchData)
 * await execute(params)
 */
export function useAsyncOperation(asyncFn, options = {}) {
  const { immediate = false } = options

  const loading = ref(false)
  const error = ref(null)
  const data = ref(null)

  /**
   * 执行异步操作
   * @param  {...any} args - 传递给异步函数的参数
   * @returns {Promise<any>} 异步函数的返回值
   */
  async function execute(...args) {
    loading.value = true
    error.value = null
    try {
      data.value = await asyncFn(...args)
      return data.value
    } catch (e) {
      error.value = e
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * 重置状态
   */
  function reset() {
    loading.value = false
    error.value = null
    data.value = null
  }

  if (immediate) {
    execute()
  }

  return {
    loading,
    error,
    data,
    execute,
    reset,
  }
}
