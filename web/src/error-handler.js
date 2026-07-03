import { ApiError, TimeoutError } from './api.js'

/**
 * 全局错误处理器
 * 三层防御: L1 Vue渲染异常 / L2 非Vue异步异常 / L3 统一提示函数
 */

/**
 * 根据错误类型显示友好的用户提示
 * @param {Error} error - 捕获的错误
 * @param {object} [options] - 配置项
 * @param {boolean} [options.showNotification=true] - 是否显示通知
 * @returns {{ type: string, message: string }} 错误信息
 */
export function showError(error, options = {}) {
  const { showNotification = true } = options
  let type = 'error'
  let message = '操作失败'

  if (error instanceof TimeoutError) {
    type = 'warning'
    message = error.message
  } else if (error instanceof ApiError) {
    switch (error.code) {
      case 'NETWORK_ERROR':
        type = 'warning'
        message = '网络连接失败，请检查网络后重试'
        break
      case 'TIMEOUT':
        type = 'warning'
        message = '请求超时，请稍后重试'
        break
      case 'SERVER_ERROR':
        message = `服务器错误 (${error.status})，请稍后重试`
        break
      case 'CLIENT_ERROR':
        if (error.status === 401) {
          type = 'warning'
          message = '登录已过期，请刷新页面'
        } else if (error.status === 403) {
          type = 'warning'
          message = '没有权限执行此操作'
        } else if (error.status === 404) {
          type = 'info'
          message = '请求的资源不存在'
        } else {
          message = error.message || `请求错误 (${error.status})`
        }
        break
      case 'PARSE_ERROR':
        message = '数据解析失败，请刷新页面重试'
        break
      default:
        message = error.message || '操作失败'
    }
  } else if (error instanceof Error) {
    message = error.message || '操作失败'
  } else {
    type = 'warning'
    message = '发生了未知错误'
  }

  if (showNotification && typeof window !== 'undefined') {
    // 优先使用 Naive UI 的 message API（如果已挂载）
    if (window.__naive_message) {
      const api = window.__naive_message
      if (type === 'warning') api.warning(message)
      else if (type === 'info') api.info(message)
      else api.error(message)
    } else {
      console.error(`[ErrorHandler] ${type}: ${message}`, error)
    }
  }

  return { type, message }
}

/**
 * 配置全局错误处理
 * @param {import('vue').App} app - Vue 应用实例
 */
export function setupErrorHandler(app) {
  // L1: Vue 渲染异常
  app.config.errorHandler = (err, instance, info) => {
    console.error('[Vue Error]', err, info)
    showError(err)
  }

  // L2: 非 Vue 异步异常
  window.onerror = (message, source, lineno, colno, error) => {
    console.error('[Window Error]', message, source, lineno, colno, error)
    showError(error || new Error(message))
  }

  // L2: 未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[Unhandled Rejection]', event.reason)
    showError(event.reason instanceof Error ? event.reason : new Error(String(event.reason)))
  })
}

/**
 * 挂载 Naive UI message API（在 App.vue 的 setup 中调用）
 * @param {object} messageApi - Naive UI 的 message API
 */
export function mountMessageApi(messageApi) {
  window.__naive_message = messageApi
}
